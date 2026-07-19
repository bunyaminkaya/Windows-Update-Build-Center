from __future__ import annotations

import ctypes
import concurrent.futures
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from ctypes import wintypes
from typing import Callable


class _TransferEstimator:
    """Stable speed/ETA estimator for long USB copy operations.

    Startup metadata work and directory creation can make the first few samples
    look extremely slow.  The estimator therefore waits for a minimum amount of
    time/data, measures throughput over a rolling window and limits abrupt ETA
    jumps.
    """

    WARMUP_SECONDS = 15.0
    MIN_BYTES_FOR_ETA = 32 * 1024 * 1024
    WINDOW_SECONDS = 30.0

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.samples: deque[tuple[float, int]] = deque()
        self.last_eta: float | None = None

    def update(self, done: int, total: int) -> tuple[float, float | None]:
        now = time.monotonic()
        done = max(0, int(done))
        total = max(1, int(total))
        self.samples.append((now, done))

        while len(self.samples) > 2 and now - self.samples[0][0] > self.WINDOW_SECONDS:
            self.samples.popleft()

        if len(self.samples) < 2:
            return 0.0, None

        first_time, first_done = self.samples[0]
        span = max(0.001, now - first_time)
        delta = max(0, done - first_done)
        speed = delta / span if delta > 0 else 0.0

        elapsed = now - self.started
        transferred_since_window = delta
        if (
            elapsed < self.WARMUP_SECONDS
            or transferred_since_window < self.MIN_BYTES_FOR_ETA
            or speed <= 0
        ):
            return speed, None

        raw_eta = max(0, total - done) / speed

        # Once ETA becomes visible, smooth impossible-looking jumps caused by
        # batches of many tiny files or delayed filesystem flushes.
        if self.last_eta is not None:
            upper = self.last_eta * 1.20 + 3.0
            lower = max(0.0, self.last_eta * 0.65 - 3.0)
            raw_eta = min(upper, max(lower, raw_eta))

        self.last_eta = raw_eta
        return speed, raw_eta



@dataclass(frozen=True)
class UsbDrive:
    disk_number: int
    friendly_name: str
    size_bytes: int
    drive_letter: str = ""

    @property
    def size_text(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{self.size_bytes} B"

    @property
    def display_name(self) -> str:
        letter = f" • {self.drive_letter}:" if self.drive_letter else ""
        return f"Disk {self.disk_number} • {self.friendly_name} • {self.size_text}{letter}"


class UsbMediaService:
    """Windows-only helper for creating bootable Windows installation media.

    The implementation deliberately targets physical disks whose BusType is USB.
    Fixed/system disks are not returned by list_usb_drives().
    """

    @staticmethod
    def is_supported_platform() -> bool:
        return os.name == "nt"

    @staticmethod
    def _run(
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=check,
            creationflags=flags,
        )


    @staticmethod
    def _is_windows_admin() -> bool:
        if os.name != "nt":
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @classmethod
    def _run_elevated_windows(
        cls,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
    ) -> int:
        """Run a command with UAC elevation and wait for the real process.

        DiskPart and BootSect need administrator rights. Starting them with the
        normal subprocess API from a non-elevated application raises WinError 740.
        ShellExecuteEx with the ``runas`` verb lets Windows show the standard UAC
        prompt while the main application stays non-elevated.
        """
        if os.name != "nt":
            raise RuntimeError("Yönetici yetkisi yalnızca Windows üzerinde kullanılabilir.")
        if not args:
            raise RuntimeError("Yükseltilmiş işlem için komut belirtilmedi.")

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", wintypes.LPVOID),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SEE_MASK_NOASYNC = 0x00000100
        SW_HIDE = 0
        WAIT_OBJECT_0 = 0x00000000
        WAIT_TIMEOUT = 0x00000102
        INFINITE = 0xFFFFFFFF

        executable = str(args[0])
        parameters = subprocess.list2cmdline([str(v) for v in args[1:]])

        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
        info.lpVerb = "runas"
        info.lpFile = executable
        info.lpParameters = parameters
        info.lpDirectory = str(cwd) if cwd else None
        info.nShow = SW_HIDE

        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        ctypes.set_last_error(0)
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error == 1223:
                raise RuntimeError("Yönetici izni kullanıcı tarafından iptal edildi.")
            raise RuntimeError(
                f"İşlem yönetici yetkisiyle başlatılamadı. Windows hata kodu: {error}"
            )
        if not info.hProcess:
            raise RuntimeError("Yükseltilmiş işlemin süreç tanıtıcısı alınamadı.")

        try:
            wait_ms = INFINITE if timeout is None else max(1, int(timeout * 1000))
            wait_result = kernel32.WaitForSingleObject(info.hProcess, wait_ms)
            if wait_result == WAIT_TIMEOUT:
                try:
                    kernel32.TerminateProcess(info.hProcess, 1)
                except Exception:
                    pass
                raise RuntimeError("Yönetici işlemi zaman aşımına uğradı.")
            if wait_result != WAIT_OBJECT_0:
                raise RuntimeError(
                    f"Yönetici işlemi beklenirken Windows hata kodu oluştu: {wait_result}"
                )

            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
                raise RuntimeError("Yönetici işleminin çıkış kodu alınamadı.")
            return int(exit_code.value)
        finally:
            kernel32.CloseHandle(info.hProcess)

    @classmethod
    def _run_privileged(
        cls,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
    ) -> None:
        """Run a command normally when already elevated, otherwise request UAC."""
        if cls._is_windows_admin():
            cls._run(args, cwd=cwd, timeout=timeout)
            return

        exit_code = cls._run_elevated_windows(args, cwd=cwd, timeout=timeout)
        if exit_code != 0:
            raise RuntimeError(
                f"Yönetici yetkisiyle çalışan işlem başarısız oldu. Çıkış kodu: {exit_code}"
            )

    @classmethod
    def _powershell(cls, script: str, *, timeout: int = 60) -> str:
        result = cls._run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            timeout=timeout,
        )
        return result.stdout.strip()

    @classmethod
    def list_usb_drives(cls) -> list[UsbDrive]:
        if not cls.is_supported_platform():
            return []

        script = r'''
$items = Get-Disk | Where-Object { $_.BusType -eq 'USB' -and -not $_.IsBoot -and -not $_.IsSystem } | ForEach-Object {
    $disk = $_
    $letters = @(
        Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue |
        Where-Object DriveLetter |
        Select-Object -ExpandProperty DriveLetter
    )
    [PSCustomObject]@{
        Number = [int]$disk.Number
        FriendlyName = [string]$disk.FriendlyName
        Size = [int64]$disk.Size
        DriveLetter = if ($letters.Count -gt 0) { [string]$letters[0] } else { '' }
    }
}
$items | ConvertTo-Json -Compress
'''
        try:
            raw = cls._powershell(script)
            if not raw:
                return []
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            drives: list[UsbDrive] = []
            for item in data:
                drives.append(
                    UsbDrive(
                        disk_number=int(item.get("Number", -1)),
                        friendly_name=str(item.get("FriendlyName") or "USB Disk"),
                        size_bytes=int(item.get("Size") or 0),
                        drive_letter=str(item.get("DriveLetter") or ""),
                    )
                )
            return [d for d in drives if d.disk_number >= 0 and d.size_bytes > 0]
        except Exception:
            return []

    @staticmethod
    def validate_iso(iso_path: Path) -> None:
        if not iso_path.exists() or not iso_path.is_file():
            raise RuntimeError("Seçilen ISO dosyası bulunamadı.")
        if iso_path.suffix.lower() != ".iso":
            raise RuntimeError("Lütfen geçerli bir .iso dosyası seçin.")
        if iso_path.stat().st_size < 100 * 1024 * 1024:
            raise RuntimeError("Seçilen ISO dosyası beklenenden küçük görünüyor.")

    @staticmethod
    def validate_target(
        drive: UsbDrive,
        iso_path: Path | None = None,
        file_system: str | None = None,
    ) -> None:
        if drive.disk_number < 0:
            raise RuntimeError("Geçerli bir USB disk seçilmedi.")
        if drive.size_bytes < 8 * 1024**3:
            raise RuntimeError("Windows kurulum medyası için en az 8 GB USB bellek gerekir.")
        if iso_path is None:
            return

        iso_size = int(iso_path.stat().st_size)
        reserve = max(512 * 1024**2, int(iso_size * 0.05))
        required = iso_size + reserve
        usable = int(drive.size_bytes)
        if str(file_system or "").upper() == "FAT32" and drive.size_bytes > 34 * 1024**3:
            usable = min(usable, 32700 * 1024**2)

        if required > usable:
            def gib(value: int) -> str:
                return f"{value / 1024**3:.2f} GB"
            raise RuntimeError(
                "USB kapasitesi seçilen ISO için yetersiz. "
                f"ISO ve güvenlik payı yaklaşık {gib(required)} alan gerektiriyor; "
                f"kullanılabilir hedef alan {gib(usable)}. USB silinmeden işlem durduruldu."
            )

    @classmethod
    def _mount_iso(cls, iso_path: Path) -> str:
        escaped = str(iso_path).replace("'", "''")
        script = rf'''
$img = Mount-DiskImage -ImagePath '{escaped}' -PassThru -ErrorAction Stop
$vol = $img | Get-Volume | Where-Object DriveLetter | Select-Object -First 1
if (-not $vol) {{ throw 'ISO sürücü harfi alınamadı.' }}
$vol.DriveLetter
'''
        letter = cls._powershell(script, timeout=120).strip().replace(":", "")
        if len(letter) != 1:
            raise RuntimeError("ISO bağlandı ancak sürücü harfi belirlenemedi.")
        return letter.upper()

    @classmethod
    def _dismount_iso(cls, iso_path: Path) -> None:
        escaped = str(iso_path).replace("'", "''")
        try:
            cls._powershell(
                f"Dismount-DiskImage -ImagePath '{escaped}' -ErrorAction SilentlyContinue",
                timeout=60,
            )
        except Exception:
            pass

    @staticmethod
    def sanitize_volume_label(label: str, file_system: str) -> str:
        fs = file_system.strip().upper()
        max_len = 11 if fs == "FAT32" else 32
        invalid_chars = '"*/:<>?\\|+,;=[]'
        cleaned = ''.join(
            ch for ch in label.upper().strip()
            if ch not in invalid_chars and ord(ch) >= 32
        )
        cleaned = ' '.join(cleaned.split())
        if not cleaned:
            cleaned = 'WIN11USB' if fs == 'FAT32' else 'WINDOWS_USB'
        fallback = 'WIN11USB' if fs == 'FAT32' else 'WINDOWS_USB'
        return cleaned[:max_len].rstrip(' .') or fallback

    @classmethod
    def _verify_drive_identity(cls, drive: UsbDrive) -> None:
        script = rf'''
$disk = Get-Disk -Number {drive.disk_number} -ErrorAction Stop
[PSCustomObject]@{{
    Number = [int]$disk.Number
    BusType = [string]$disk.BusType
    IsBoot = [bool]$disk.IsBoot
    IsSystem = [bool]$disk.IsSystem
    Size = [int64]$disk.Size
}} | ConvertTo-Json -Compress
'''
        raw = cls._powershell(script, timeout=30)
        data = json.loads(raw)
        if str(data.get('BusType', '')).upper() != 'USB':
            raise RuntimeError('Güvenlik kontrolü başarısız: seçilen hedef artık USB disk olarak görünmüyor.')
        if bool(data.get('IsBoot')) or bool(data.get('IsSystem')):
            raise RuntimeError('Güvenlik kontrolü başarısız: sistem veya önyükleme diski hedef olarak kullanılamaz.')
        actual_size = int(data.get('Size') or 0)
        tolerance = max(64 * 1024**2, int(drive.size_bytes * 0.01))
        if abs(actual_size - drive.size_bytes) > tolerance:
            raise RuntimeError('USB disk kimliği değişti. Yanlış diskin silinmesini önlemek için listeyi yenileyip tekrar seçin.')

    @staticmethod
    def _decode_command_log(path: Path) -> str:
        if not path.exists():
            return ''
        raw = path.read_bytes()
        for enc in ('utf-8', 'cp1254', 'cp850', 'utf-16', 'latin-1'):
            try:
                text = raw.decode(enc)
                if text.strip():
                    return text.strip()
            except Exception:
                continue
        return raw.decode('utf-8', errors='replace').strip()

    @classmethod
    def _run_privileged_logged(
        cls,
        args: list[str],
        *,
        log_path: Path,
        cwd: Path | None = None,
        timeout: int | None = None,
    ) -> None:
        fd, wrapper_name = tempfile.mkstemp(prefix='wubc_admin_', suffix='.cmd')
        os.close(fd)
        wrapper = Path(wrapper_name)
        command = subprocess.list2cmdline([str(x) for x in args])
        quoted_log = subprocess.list2cmdline([str(log_path)])
        try:
            wrapper.write_text(
                '@echo off\r\n'
                + f'{command} > {quoted_log} 2>&1\r\n'
                + 'set WUBC_RC=%ERRORLEVEL%\r\n'
                + 'exit /b %WUBC_RC%\r\n',
                encoding='ascii',
                errors='ignore',
            )
            cls._run_privileged(['cmd.exe', '/d', '/c', str(wrapper)], cwd=cwd, timeout=timeout)
        except Exception as exc:
            detail = cls._decode_command_log(log_path)
            if detail:
                raise RuntimeError(f'{exc}\n\nDisk işlemi ayrıntıları:\n{detail}') from exc
            raise
        finally:
            wrapper.unlink(missing_ok=True)

    _FAT32_MIN_CLUSTERS = 65527  # DiskPart/format.exe reject FAT32 below this cluster count

    @classmethod
    def _cluster_size_bytes(cls, file_system: str, partition_size_bytes: int) -> int | None:
        """Allocation unit size to request during format, if any.

        Windows install media is made up of many thousands of small files
        (drivers, localization resources, servicing manifests, ...). The
        default "quick format" allocation unit on a FAT32 volume is only
        4 KB, which means the FAT table has to be walked and updated once
        per ~4 KB of every file — on a flash device that turns into a very
        large number of tiny metadata writes and is the main reason copying
        feels much slower than tools like Rufus. Rufus avoids this by
        defaulting large FAT32 boot media to a 32 KB cluster (Microsoft's
        own recommended maximum for FAT32), which cuts the number of FAT
        metadata operations roughly eightfold without affecting Windows
        Setup compatibility.

        FAT32 also requires the resulting cluster count to stay at or above
        ~65,527 (format/diskpart error out otherwise), so the biggest legal
        size is picked for the actual partition size instead of assuming
        32 KB always fits — this keeps very small FAT32 targets working
        exactly as before instead of risking a failed format.

        NTFS already stores small files/metadata efficiently via the MFT,
        so its default allocation unit is left untouched here.
        """
        if file_system.lower() != "fat32":
            return None
        for candidate in (32768, 16384, 8192):
            if partition_size_bytes // candidate >= cls._FAT32_MIN_CLUSTERS:
                return candidate
        return None

    @classmethod
    def _build_diskpart_script(
        cls,
        drive: UsbDrive,
        partition_scheme: str,
        file_system: str,
        label: str,
    ) -> list[str]:
        fs = file_system.lower()
        safe_label = UsbMediaService.sanitize_volume_label(label, fs)
        if fs not in {"fat32", "ntfs"}:
            raise RuntimeError("Desteklenmeyen dosya sistemi seçildi.")
        scheme = partition_scheme.upper()
        if scheme not in {"GPT", "MBR"}:
            raise RuntimeError("Desteklenmeyen bölüm düzeni seçildi.")

        create_partition = "create partition primary"
        partition_size_bytes = drive.size_bytes
        if fs == "fat32" and drive.size_bytes > 34 * 1024**3:
            create_partition = "create partition primary size=32700"
            partition_size_bytes = 32700 * 1024 * 1024

        lines = [
            f"select disk {drive.disk_number}",
            "clean",
            # The USB may already use the requested partition style. DiskPart
            # reports that as an error (for example, convert gpt on an already-GPT
            # disk). In scripted mode noerr keeps the safe preparation sequence
            # running instead of aborting before partition creation.
            f"convert {scheme.lower()} noerr",
            create_partition,
            # DiskPart does not reliably keep the newly created partition as the
            # selected object when the script is executed elevated/non-interactively.
            # Explicitly selecting it prevents: "There is no volume selected".
            "select partition 1",
        ]
        if scheme == "MBR":
            lines.append("active")
        cluster = cls._cluster_size_bytes(fs, partition_size_bytes)
        unit_clause = f" unit={cluster}" if cluster else ""
        lines.extend([
            f'format fs={fs} quick label="{safe_label}"{unit_clause}',
            "assign",
            "exit",
        ])
        return lines

    @classmethod
    def _build_partition_powershell_script(
        cls,
        drive: UsbDrive,
        partition_scheme: str,
        file_system: str,
        label: str,
        marker_path: Path,
    ) -> str:
        """Build the elevated Storage-module script used to prepare the USB.

        DiskPart can lose its selected-object context after a failed convert
        command. Using explicit Storage cmdlet objects avoids that stateful
        failure mode on repeated GPT/MBR preparations.
        """
        fs = file_system.upper()
        scheme = partition_scheme.upper()
        if fs not in {"FAT32", "NTFS"}:
            raise RuntimeError("Desteklenmeyen dosya sistemi seçildi.")
        if scheme not in {"GPT", "MBR"}:
            raise RuntimeError("Desteklenmeyen bölüm düzeni seçildi.")

        safe_label = cls.sanitize_volume_label(label, fs).replace("'", "''")
        marker = str(marker_path).replace("'", "''")
        partition_size_bytes = drive.size_bytes
        size_arg = "-UseMaximumSize"
        if fs == "FAT32" and drive.size_bytes > 34 * 1024**3:
            partition_size_bytes = 32700 * 1024 * 1024
            size_arg = "-Size 32700MB"
        cluster = cls._cluster_size_bytes(fs, partition_size_bytes)
        cluster_arg = f" -AllocationUnitSize {cluster}" if cluster else ""
        active_line = "$part | Set-Partition -IsActive $true -ErrorAction Stop" if scheme == "MBR" else ""

        return rf'''$ErrorActionPreference = 'Stop'
$diskNumber = {drive.disk_number}
$disk = Get-Disk -Number $diskNumber -ErrorAction Stop
if ($disk.IsOffline) {{ Set-Disk -Number $diskNumber -IsOffline $false -ErrorAction Stop }}
if ($disk.IsReadOnly) {{ Set-Disk -Number $diskNumber -IsReadOnly $false -ErrorAction Stop }}
Clear-Disk -Number $diskNumber -RemoveData -RemoveOEM -Confirm:$false -ErrorAction Stop

# Windows can auto-refresh/claim removable media immediately after Clear-Disk.
# Wait until the Storage provider settles, then initialize only RAW disks.
# If the disk is already initialized, keep it when the style matches or
# convert the empty disk explicitly when it does not.
$targetStyle = '{scheme}'
$disk = $null
for ($i = 0; $i -lt 20; $i++) {{
    try {{ Update-Disk -Number $diskNumber -ErrorAction SilentlyContinue | Out-Null }} catch {{}}
    $disk = Get-Disk -Number $diskNumber -ErrorAction Stop
    if ($disk.PartitionStyle -eq 'RAW' -or $disk.PartitionStyle -eq $targetStyle) {{ break }}
    Start-Sleep -Milliseconds 250
}}

if ($disk.PartitionStyle -eq 'RAW') {{
    Initialize-Disk -Number $diskNumber -PartitionStyle $targetStyle -ErrorAction Stop | Out-Null
}} elseif ($disk.PartitionStyle -ne $targetStyle) {{
    # Clear-Disk already removed all partitions, so changing the style is safe.
    Set-Disk -Number $diskNumber -PartitionStyle $targetStyle -ErrorAction Stop
}}

$disk = Get-Disk -Number $diskNumber -ErrorAction Stop
if ($disk.PartitionStyle -ne $targetStyle) {{
    throw "USB bölüm düzeni hazırlanamadı. Beklenen: $targetStyle, mevcut: $($disk.PartitionStyle)"
}}

$part = New-Partition -DiskNumber $diskNumber {size_arg} -AssignDriveLetter -ErrorAction Stop
{active_line}
$part | Format-Volume -FileSystem {fs} -NewFileSystemLabel '{safe_label}' -Confirm:$false -Force{cluster_arg} -ErrorAction Stop | Out-Null
$letter = (Get-Partition -DiskNumber $diskNumber -ErrorAction Stop | Where-Object DriveLetter | Select-Object -First 1).DriveLetter
if (-not $letter) {{ throw 'USB sürücü harfi atanamadı.' }}
Set-Content -LiteralPath '{marker}' -Value ([string]$letter) -Encoding ASCII
'''

    @classmethod
    def _prepare_disk(
        cls,
        drive: UsbDrive,
        partition_scheme: str,
        file_system: str,
        label: str,
    ) -> str:
        cls._verify_drive_identity(drive)

        fd, script_name = tempfile.mkstemp(prefix='wubc_prepare_usb_', suffix='.ps1')
        os.close(fd)
        script_path = Path(script_name)
        log_path = script_path.with_suffix('.log')
        marker_path = script_path.with_suffix('.letter')
        try:
            script = cls._build_partition_powershell_script(
                drive,
                partition_scheme,
                file_system,
                label,
                marker_path,
            )
            script_path.write_text(script, encoding='utf-8-sig')
            cls._run_privileged_logged(
                [
                    'powershell.exe',
                    '-NoProfile',
                    '-NonInteractive',
                    '-ExecutionPolicy',
                    'Bypass',
                    '-File',
                    str(script_path),
                ],
                log_path=log_path,
                timeout=420,
            )

            letter = ''
            for _ in range(20):
                if marker_path.exists():
                    letter = marker_path.read_text(encoding='ascii', errors='ignore').strip().replace(':', '')
                    if len(letter) == 1 and letter.isalpha():
                        break
                time.sleep(0.5)

            if len(letter) != 1:
                query = rf'''$part = Get-Partition -DiskNumber {drive.disk_number} -ErrorAction SilentlyContinue |
    Where-Object DriveLetter | Select-Object -First 1
if ($part) {{ [string]$part.DriveLetter }}'''
                for _ in range(10):
                    try:
                        letter = cls._powershell(query, timeout=30).strip().replace(':', '')
                        if len(letter) == 1 and letter.isalpha():
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)

            if len(letter) != 1:
                detail = cls._decode_command_log(log_path)
                extra = f'\n\nUSB hazırlama günlüğü:\n{detail}' if detail else ''
                raise RuntimeError('USB biçimlendirildi ancak sürücü harfi belirlenemedi.' + extra)
            return letter.upper()
        finally:
            script_path.unlink(missing_ok=True)
            marker_path.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)

    @staticmethod
    def _install_wim(source_root: Path) -> Path | None:
        candidates = [source_root / "sources" / "install.wim", source_root / "sources" / "install.esd"]
        return next((p for p in candidates if p.exists()), None)

    @staticmethod
    def _tree_size(root: Path) -> int:
        total = 0
        if not root.exists():
            return 0
        for base, _dirs, files in os.walk(root):
            for name in files:
                try:
                    total += (Path(base) / name).stat().st_size
                except OSError:
                    pass
        return total

    @staticmethod
    def _format_capacity(value: int) -> str:
        size = float(max(0, int(value)))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{value} B"

    @staticmethod
    def _required_wim_workspace_bytes(wim_size: int) -> int:
        """Conservative free-space requirement for DISM Split-Image.

        The split output is approximately the size of the source WIM and DISM
        also needs scratch/metadata space. Reserving 35% plus a 2 GiB floor
        avoids starting a destructive USB operation when the local workspace
        cannot finish the WIM preparation phase.
        """
        wim_size = max(0, int(wim_size))
        return max(wim_size + 2 * 1024**3, int(wim_size * 1.35))

    @staticmethod
    def _drive_key(path: Path) -> str:
        try:
            drive = path.resolve().drive
        except Exception:
            drive = path.drive
        return drive.rstrip("\\/").upper()

    @classmethod
    def _fixed_drive_roots(cls) -> list[Path]:
        if os.name != "nt":
            return []
        roots: list[Path] = []
        try:
            kernel32 = ctypes.windll.kernel32
            mask = int(kernel32.GetLogicalDrives())
            DRIVE_FIXED = 3
            for index in range(26):
                if not (mask & (1 << index)):
                    continue
                root = f"{chr(ord('A') + index)}:\\"
                if int(kernel32.GetDriveTypeW(root)) == DRIVE_FIXED:
                    roots.append(Path(root))
        except Exception:
            return []
        return roots

    @classmethod
    def _wim_workspace_candidates(
        cls,
        preferred_dir: Path | None,
        target_root: Path,
    ) -> list[Path]:
        """Return writable local workspace candidates in preferred order."""
        raw: list[Path] = []
        if preferred_dir:
            raw.append(Path(preferred_dir))

        temp_dir = Path(tempfile.gettempdir())
        raw.append(temp_dir)

        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            raw.append(Path(local_app_data) / "Temp")

        for root in cls._fixed_drive_roots():
            raw.append(root / "WUBC_Temp")

        target_key = cls._drive_key(target_root)
        seen: set[str] = set()
        result: list[Path] = []
        for candidate in raw:
            try:
                key = str(candidate.resolve()).casefold()
            except Exception:
                key = str(candidate).casefold()
            if key in seen:
                continue
            seen.add(key)
            if target_key and cls._drive_key(candidate) == target_key:
                # Never use the USB target itself as the fast local WIM workspace.
                continue
            result.append(candidate)
        return result

    @classmethod
    def _select_wim_workspace_base(
        cls,
        install_image: Path,
        *,
        preferred_dir: Path | None,
        target_root: Path,
    ) -> tuple[Path, int, int]:
        """Select a writable local disk with enough free space for DISM.

        Returns ``(base_directory, required_bytes, free_bytes)``. The ISO's
        original folder is preferred, then the Windows temp area, then any
        fixed local disk with enough capacity. This prevents DISM error 112
        when the system drive is nearly full.
        """
        required = cls._required_wim_workspace_bytes(install_image.stat().st_size)
        inspected: list[tuple[Path, int]] = []
        viable: list[tuple[int, int, Path]] = []

        for priority, candidate in enumerate(
            cls._wim_workspace_candidates(preferred_dir, target_root)
        ):
            try:
                # Check capacity on the nearest existing parent before creating
                # anything. Then verify that the current user can actually write.
                probe_parent = candidate
                while not probe_parent.exists() and probe_parent.parent != probe_parent:
                    probe_parent = probe_parent.parent
                free = int(shutil.disk_usage(probe_parent).free)
                inspected.append((candidate, free))
                if free < required:
                    continue

                candidate.mkdir(parents=True, exist_ok=True)
                probe = candidate / f".wubc_write_test_{os.getpid()}_{time.time_ns()}"
                probe.write_bytes(b"ok")
                probe.unlink(missing_ok=True)
                # Prefer the ISO's own local folder, otherwise choose the disk
                # with the most free space. Lower priority value wins ties.
                viable.append((priority, -free, candidate))
            except Exception:
                continue

        if viable:
            viable.sort(key=lambda item: (item[0] if item[0] == 0 else 1, item[1], item[0]))
            chosen = viable[0][2]
            free = int(shutil.disk_usage(chosen).free)
            return chosen, required, free

        best = max((free for _path, free in inspected), default=0)
        locations = ", ".join(
            f"{path} ({cls._format_capacity(free)} boş)"
            for path, free in sorted(inspected, key=lambda item: item[1], reverse=True)[:4]
        ) or "uygun yerel disk bulunamadı"
        raise RuntimeError(
            "install.wim dosyasını hazırlamak için yerel diskte yeterli boş alan yok. "
            f"Gerekli yaklaşık alan: {cls._format_capacity(required)}. "
            f"Bulunan en yüksek boş alan: {cls._format_capacity(best)}. "
            f"Kontrol edilen konumlar: {locations}. USB silinmiş olabilir; "
            "yerel diskte alan açtıktan sonra işlemi yeniden başlatın."
        )

    @staticmethod
    def _format_speed(value: float) -> str:
        if value <= 0:
            return "—"
        units = ("B/sn", "KB/sn", "MB/sn", "GB/sn")
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{value:.1f} B/sn"

    @staticmethod
    def _format_eta(seconds: float) -> str:
        if seconds <= 0 or seconds == float("inf"):
            return "hesaplanıyor"
        seconds = int(seconds)
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours} sa {minutes} dk"
        if minutes:
            return f"{minutes} dk {secs} sn"
        return f"{secs} sn"

    @classmethod
    def _progress_text(cls, percent: int, speed: float, eta: float | None) -> str:
        if eta is None:
            speed_text = cls._format_speed(speed) if speed > 0 else "—"
            return f"{percent}% • {speed_text} • kalan süre hesaplanıyor..."
        return (
            f"{percent}% • {cls._format_speed(speed)} • "
            f"yaklaşık {cls._format_eta(eta)} kaldı"
        )

    @classmethod
    def _run_robocopy(
        cls,
        source_root: Path,
        target_root: Path,
        *,
        exclude_install_wim: bool,
    ) -> None:
        args = [
            "robocopy.exe",
            str(source_root),
            str(target_root),
            "/E",
            "/MT:16",
            "/R:1",
            "/W:1",
            "/J",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
        ]
        if exclude_install_wim:
            args.extend(["/XF", "install.wim"])
        result = cls._run(args, timeout=7200, check=False)
        if result.returncode > 7:
            raise RuntimeError(f"Dosyalar kopyalanamadı. Robocopy kodu: {result.returncode}")

    @classmethod
    def _wait_until_readable(cls, path: Path, *, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + max(0.5, timeout)
        while time.monotonic() < deadline:
            try:
                with path.open("rb", buffering=0) as handle:
                    handle.read(1)
                return True
            except PermissionError:
                time.sleep(0.5)
            except OSError:
                time.sleep(0.35)
        return False

    @classmethod
    def _restore_workspace_access(cls, workspace: Path) -> None:
        """Restore access to files created by elevated DISM.

        The application itself normally runs non-elevated while DISM is started
        through UAC. Some Windows configurations create the resulting SWM files
        with an administrator-only ACL. Granting the current user's SID access to
        the temporary workspace avoids PermissionError without making the whole
        application run as administrator.
        """
        if os.name != "nt":
            return
        sid_script = (
            "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"
        )
        sid = cls._powershell(sid_script, timeout=30).strip()
        if not sid:
            return
        # Re-enable inheritance first, then explicitly grant the interactive
        # user full access to the directory and all generated SWM files.
        cls._run_privileged(
            [
                "icacls.exe",
                str(workspace),
                "/inheritance:e",
                "/T",
                "/C",
                "/Q",
            ],
            timeout=120,
        )
        cls._run_privileged(
            [
                "icacls.exe",
                str(workspace),
                "/grant",
                f"*{sid}:(OI)(CI)F",
                "/T",
                "/C",
                "/Q",
            ],
            timeout=120,
        )

    @classmethod
    def _split_wim_to_workspace(
        cls,
        install_image: Path,
        workspace: Path,
        *,
        progress: Callable[[str], None],
    ) -> list[Path]:
        workspace.mkdir(parents=True, exist_ok=True)
        swm = workspace / "install.swm"
        scratch = workspace / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        required = cls._required_wim_workspace_bytes(install_image.stat().st_size)
        free = int(shutil.disk_usage(workspace).free)
        if free < required:
            raise RuntimeError(
                "WIM geçici çalışma alanında yeterli boş alan yok. "
                f"Gerekli yaklaşık: {cls._format_capacity(required)}, "
                f"boş: {cls._format_capacity(free)}, konum: {workspace}."
            )
        progress(
            "install.wim hızlı yerel çalışma alanında bölünüyor: "
            f"{workspace} • boş alan {cls._format_capacity(free)}."
        )
        try:
            cls._run_privileged(
                [
                    "dism.exe",
                    "/English",
                    "/Split-Image",
                    f"/ImageFile:{install_image}",
                    f"/SWMFile:{swm}",
                    "/FileSize:3800",
                    f"/ScratchDir:{scratch}",
                ],
                timeout=7200,
            )
        except RuntimeError as exc:
            if "Çıkış kodu: 112" in str(exc) or "error 112" in str(exc).lower():
                current_free = int(shutil.disk_usage(workspace).free)
                raise RuntimeError(
                    "DISM, install.wim dosyasını bölerken çalışma diskinde yer kalmadı "
                    "(Windows hata kodu 112). "
                    f"Çalışma alanı: {workspace}; "
                    f"kalan boş alan: {cls._format_capacity(current_free)}. "
                    "Yerel diskte alan açıp işlemi yeniden başlatın."
                ) from exc
            raise
        parts = sorted(workspace.glob("install*.swm"))
        if not parts:
            raise RuntimeError(
                "DISM install.wim dosyasını böldü ancak SWM parçaları oluşturulamadı."
            )

        # DISM runs elevated. On some Windows systems the generated SWM files
        # inherit an ACL that the non-elevated application process cannot read.
        # First wait briefly in case Windows/AV still holds a transient handle;
        # if access is still denied, restore inherited permissions and grant the
        # current interactive user full access to the temporary workspace.
        unreadable = [part for part in parts if not cls._wait_until_readable(part, timeout=4.0)]
        if unreadable:
            progress(
                "DISM tarafından oluşturulan SWM dosyalarının erişim izinleri düzeltiliyor."
            )
            cls._restore_workspace_access(workspace)
            unreadable = [part for part in parts if not cls._wait_until_readable(part, timeout=20.0)]

        if unreadable:
            names = ", ".join(part.name for part in unreadable[:4])
            raise RuntimeError(
                "SWM dosyaları oluşturuldu ancak uygulama bu dosyaları okuyamıyor: "
                f"{names}. Geçici klasör erişim izni düzeltilemedi."
            )
        return parts

    @classmethod
    def _copy_swm_parts(
        cls,
        parts: list[Path],
        sources_dir: Path,
        *,
        progress: Callable[[str], None],
        on_progress: Callable[[int, str], None],
        cancelled: Callable[[], bool],
    ) -> None:
        """Copy split WIM files without Robocopy and verify every file.

        SWM files are few but very large. Copying them sequentially with a large
        buffer is more predictable on removable flash media than starting a
        multi-threaded Robocopy job. Every file is written to a temporary target,
        retried on transient I/O errors, then size-verified before it replaces the
        final destination file.
        """
        parts = [Path(part) for part in parts if Path(part).exists()]
        if not parts:
            raise RuntimeError("Kopyalanacak SWM parçası bulunamadı.")

        total_bytes = sum(part.stat().st_size for part in parts)
        try:
            free_bytes = shutil.disk_usage(sources_dir).free
        except OSError:
            free_bytes = total_bytes
        required_bytes = total_bytes + (64 * 1024**2)
        if free_bytes < required_bytes:
            raise RuntimeError(
                "SWM parçaları için USB bellekte yeterli boş alan yok. "
                f"Gerekli: {required_bytes / 1024**3:.2f} GB, "
                f"Boş: {free_bytes / 1024**3:.2f} GB."
            )

        copied_total = 0
        estimator = _TransferEstimator()
        chunk_size = 16 * 1024 * 1024

        for index, source in enumerate(parts, start=1):
            destination = sources_dir / source.name
            temp_destination = destination.with_name(destination.name + ".wubc-part")
            source_size = source.stat().st_size
            progress(f"SWM {index}/{len(parts)} kopyalanıyor: {source.name}")

            last_error: Exception | None = None
            for attempt in range(1, 4):
                try:
                    if temp_destination.exists():
                        temp_destination.unlink()

                    file_copied = 0
                    with source.open("rb", buffering=0) as src, temp_destination.open("wb", buffering=0) as dst:
                        while True:
                            if cancelled():
                                raise RuntimeError("İşlem kullanıcı tarafından iptal edildi.")
                            block = src.read(chunk_size)
                            if not block:
                                break
                            dst.write(block)
                            file_copied += len(block)
                            current_total = copied_total + file_copied
                            speed, eta = estimator.update(current_total, total_bytes)
                            percent = 70 + min(29, int((current_total / max(1, total_bytes)) * 29))
                            on_progress(percent, cls._progress_text(percent, speed, eta))

                        dst.flush()
                        try:
                            os.fsync(dst.fileno())
                        except OSError:
                            pass

                    if temp_destination.stat().st_size != source_size:
                        raise OSError(
                            f"Boyut doğrulaması başarısız: {source.name} "
                            f"({temp_destination.stat().st_size} / {source_size} bayt)"
                        )

                    if destination.exists():
                        destination.unlink()
                    temp_destination.replace(destination)

                    if destination.stat().st_size != source_size:
                        raise OSError(f"Son dosya doğrulaması başarısız: {source.name}")

                    copied_total += source_size
                    last_error = None
                    break
                except RuntimeError:
                    raise
                except Exception as exc:
                    last_error = exc
                    progress(
                        f"{source.name} kopyalanamadı (deneme {attempt}/3): {exc}. "
                        "Kısa süre sonra tekrar denenecek."
                    )
                    try:
                        if temp_destination.exists():
                            temp_destination.unlink()
                    except OSError:
                        pass
                    if attempt < 3:
                        time.sleep(1.5 * attempt)

            if last_error is not None:
                raise RuntimeError(
                    f"SWM parçası USB'ye kopyalanamadı: {source.name}. "
                    f"Ayrıntı: {last_error}"
                )


    @classmethod
    def _copy_tree(
        cls,
        source_root: Path,
        target_root: Path,
        *,
        split_large_wim: bool,
        workspace_hint: Path | None = None,
        progress: Callable[[str], None] | None = None,
        on_progress: Callable[[int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        progress = progress or (lambda _msg: None)
        on_progress = on_progress or (lambda _percent, _text: None)
        cancelled = cancelled or (lambda: False)
        install_image = cls._install_wim(source_root)

        if split_large_wim:
            oversized: list[Path] = []
            limit = 4 * 1024**3 - 64 * 1024**2
            for root, _dirs, files in os.walk(source_root):
                for name in files:
                    path = Path(root) / name
                    try:
                        if path.stat().st_size > limit:
                            oversized.append(path)
                    except OSError:
                        continue
            unsupported = [path for path in oversized if path.name.lower() != 'install.wim']
            if unsupported:
                names = ', '.join(path.name for path in unsupported[:4])
                raise RuntimeError(
                    "FAT32 hedefinde 4 GB'tan büyük ve otomatik bölünemeyen dosya bulundu: "
                    f'{names}. Dosya sistemi olarak NTFS seçin.'
                )

        large_wim = (
            install_image is not None
            and install_image.name.lower() == "install.wim"
            and install_image.stat().st_size > 4 * 1024**3 - 64 * 1024**2
        )

        if split_large_wim and large_wim:
            progress(
                "Hızlandırılmış mod: Windows dosyaları USB'ye kopyalanırken "
                "install.wim aynı anda SSD üzerinde hazırlanıyor."
            )
            source_total = cls._tree_size(source_root)
            wim_size = install_image.stat().st_size
            other_total = max(1, source_total - wim_size)
            # Stage-3 progress is split into two explicit phases:
            #   0-70%  regular files copy + WIM split preparation
            #   70-100% prepared SWM parts copied to USB
            # This prevents the progress display from appearing stuck around
            # the middle while the next phase is actually about to start.
            prepare_work = max(1, other_total + wim_size)

            workspace_base, required_space, free_space = cls._select_wim_workspace_base(
                install_image,
                preferred_dir=workspace_hint,
                target_root=target_root,
            )
            progress(
                "WIM çalışma diski seçildi: "
                f"{workspace_base} • gerekli yaklaşık {cls._format_capacity(required_space)} • "
                f"boş {cls._format_capacity(free_space)}."
            )
            with tempfile.TemporaryDirectory(prefix="WUBC_WIM_", dir=str(workspace_base)) as tmp_dir:
                workspace = Path(tmp_dir)
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    copy_future = pool.submit(
                        cls._run_robocopy,
                        source_root,
                        target_root,
                        exclude_install_wim=True,
                    )
                    split_future = pool.submit(
                        cls._split_wim_to_workspace,
                        install_image,
                        workspace,
                        progress=progress,
                    )

                    estimator = _TransferEstimator()
                    while not (copy_future.done() and split_future.done()):
                        if cancelled():
                            raise RuntimeError("İşlem kullanıcı tarafından iptal edildi.")
                        copied = min(other_total, cls._tree_size(target_root))
                        split_done = min(wim_size, cls._tree_size(workspace))
                        done = min(prepare_work, copied + split_done)
                        speed, eta = estimator.update(done, prepare_work)
                        percent = max(1, min(69, int((done / prepare_work) * 69)))
                        on_progress(percent, cls._progress_text(percent, speed, eta))
                        time.sleep(0.6)

                    # Surface errors from either parallel task.
                    copy_future.result()
                    parts = split_future.result()

                sources_dir = target_root / "sources"
                sources_dir.mkdir(parents=True, exist_ok=True)
                progress(f"{len(parts)} SWM parçası USB'ye güvenli şekilde kopyalanıyor.")
                on_progress(70, "70% • SWM parçaları USB'ye kopyalanıyor")
                cls._copy_swm_parts(
                    parts,
                    sources_dir,
                    progress=progress,
                    on_progress=on_progress,
                    cancelled=cancelled,
                )
                on_progress(100, "100% • Windows dosyaları hazır")
            return

        # Normal path: use multi-threaded Robocopy and poll copied bytes so the UI
        # can show a real transfer rate and a stable ETA.
        total = max(1, cls._tree_size(source_root))
        args = [
            "robocopy.exe",
            str(source_root),
            str(target_root),
            "/E",
            "/MT:16",
            "/R:1",
            "/W:1",
            "/J",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
        ]
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        estimator = _TransferEstimator()
        while process.poll() is None:
            if cancelled():
                try:
                    process.terminate()
                except Exception:
                    pass
                raise RuntimeError("İşlem kullanıcı tarafından iptal edildi.")
            current = min(total, cls._tree_size(target_root))
            speed, eta = estimator.update(current, total)
            percent = min(99, int(current / total * 100))
            on_progress(percent, cls._progress_text(percent, speed, eta))
            time.sleep(0.6)
        if process.returncode > 7:
            raise RuntimeError(f"Dosyalar kopyalanamadı. Robocopy kodu: {process.returncode}")
        on_progress(100, "100% • Windows dosyaları hazır")

    @staticmethod
    def _write_hardware_bypass(target_root: Path) -> None:
        xml = r'''<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <RunSynchronous>
        <RunSynchronousCommand wcm:action="add"><Order>1</Order><Path>reg.exe add "HKLM\SYSTEM\Setup\LabConfig" /v BypassTPMCheck /t REG_DWORD /d 1 /f</Path></RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add"><Order>2</Order><Path>reg.exe add "HKLM\SYSTEM\Setup\LabConfig" /v BypassSecureBootCheck /t REG_DWORD /d 1 /f</Path></RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add"><Order>3</Order><Path>reg.exe add "HKLM\SYSTEM\Setup\LabConfig" /v BypassRAMCheck /t REG_DWORD /d 1 /f</Path></RunSynchronousCommand>
      </RunSynchronous>
    </component>
  </settings>
</unattend>
'''
        (target_root / "autounattend.xml").write_text(xml, encoding="utf-8")

    @classmethod
    def _make_mbr_bootable(cls, source_root: Path, target_letter: str) -> None:
        bootsect = source_root / "boot" / "bootsect.exe"
        if bootsect.exists():
            cls._run_privileged([str(bootsect), "/nt60", f"{target_letter}:", "/mbr"], timeout=180)

    @staticmethod
    def resolve_file_system(partition_scheme: str, requested: str) -> str:
        if requested != "Otomatik":
            return requested
        return "FAT32" if partition_scheme == "GPT" else "NTFS"

    @classmethod
    def create_media(
        cls,
        iso_path: Path,
        drive: UsbDrive,
        partition_scheme: str,
        requested_file_system: str,
        label: str,
        bypass_hardware_checks: bool,
        *,
        on_stage: Callable[[int, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        on_progress: Callable[[int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        on_stage = on_stage or (lambda _stage, _text: None)
        on_log = on_log or (lambda _text: None)
        on_progress = on_progress or (lambda _percent, _text: None)
        cancelled = cancelled or (lambda: False)

        cls.validate_iso(iso_path)
        file_system = cls.resolve_file_system(partition_scheme, requested_file_system)
        cls.validate_target(drive, iso_path, file_system)
        if not cls.is_supported_platform():
            raise RuntimeError("USB Kurulum Merkezi yalnızca Windows üzerinde çalışır.")
        iso_letter = ""
        try:
            on_stage(1, "ISO ve USB doğrulanıyor")
            if cancelled():
                raise RuntimeError("İşlem kullanıcı tarafından iptal edildi.")
            iso_letter = cls._mount_iso(iso_path)
            source_root = Path(f"{iso_letter}:\\")
            on_log(f"ISO bağlandı: {iso_letter}:\\")

            on_stage(2, "USB bölümlendiriliyor")
            if cancelled():
                raise RuntimeError("İşlem kullanıcı tarafından iptal edildi.")
            if not cls._is_windows_admin():
                on_log("USB disk işlemi için Windows yönetici izni isteniyor. UAC penceresinde Evet seçin.")
            if file_system == "FAT32" and drive.size_bytes > 34 * 1024**3:
                on_log(
                    "USB 32 GB'tan büyük olduğu için Windows uyumlu 31,9 GB FAT32 "
                    "önyükleme bölümü oluşturulacak. Kalan alan şimdilik ayrılmamış olarak bırakılır."
                )
            effective_label = cls.sanitize_volume_label(label, file_system)
            if effective_label != label:
                on_log(f"USB etiketi {file_system} sınırlarına göre '{effective_label}' olarak düzenlendi.")
            target_letter = cls._prepare_disk(drive, partition_scheme, file_system, effective_label)
            target_root = Path(f"{target_letter}:\\")
            on_log(f"USB hazırlandı: {target_letter}:\\ • {partition_scheme} • {file_system}")

            on_stage(3, "Windows dosyaları kopyalanıyor")
            if cancelled():
                raise RuntimeError("İşlem kullanıcı tarafından iptal edildi.")
            cls._copy_tree(
                source_root,
                target_root,
                split_large_wim=(file_system == "FAT32"),
                workspace_hint=iso_path.parent,
                progress=on_log,
                on_progress=on_progress,
                cancelled=cancelled,
            )

            on_stage(4, "Önyükleme yapısı hazırlanıyor")
            if partition_scheme == "MBR":
                cls._make_mbr_bootable(source_root, target_letter)
            elif not (target_root / "EFI" / "BOOT").exists():
                raise RuntimeError("ISO içinde UEFI önyükleme dosyaları bulunamadı.")

            on_stage(5, "Windows 11 uyumluluk seçenekleri uygulanıyor")
            if bypass_hardware_checks:
                cls._write_hardware_bypass(target_root)
                on_log("TPM 2.0, Secure Boot ve RAM kontrollerini atlama profili eklendi.")
            else:
                (target_root / "autounattend.xml").unlink(missing_ok=True)

            on_stage(6, "Kurulum medyası doğrulanıyor")
            required = [target_root / "sources", target_root / "boot"]
            if partition_scheme == "GPT":
                required.append(target_root / "EFI")
            missing = [str(p) for p in required if not p.exists()]
            if missing:
                raise RuntimeError("USB doğrulaması başarısız. Eksik yapı: " + ", ".join(missing))

            return f"{target_letter}:\\"
        finally:
            if iso_letter:
                cls._dismount_iso(iso_path)

    @staticmethod
    def system_summary() -> str:
        return f"{platform.system()} {platform.release()} • {platform.machine()}"
