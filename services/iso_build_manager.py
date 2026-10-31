from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import threading
from pathlib import Path
from app.paths import ISO_TASKS_PATH

import requests
from PySide6.QtCore import QObject, QThread, Signal, QTimer


MANIFEST_URL = (
    "https://git.uupdump.net/uup-dump/misc/raw/branch/master/"
    "autodl_files/converter_windows"
)


class IsoBuildWorker(QObject):
    status = Signal(str, str)
    finished = Signal(str, str, str)
    failed = Signal(str, str)
    cancelled = Signal(str, str)

    def __init__(self, batch_id: str, metadata: dict):
        super().__init__()
        self.batch_id = batch_id
        self.metadata = dict(metadata or {})
        self._cancel_requested = False
        self._launcher = None
        self._elevated_process_handle = None
        self._elevated_process_id = 0
        # Incremental converter-log reader state. Reading only the final line made
        # the UI appear frozen whenever the converter kept the same trailing line.
        self._log_offset = 0
        self._log_remainder = ""
        self._log_last_activity = 0.0

    def cancel(self):
        self._cancel_requested = True

        if os.name == "nt" and self._elevated_process_id:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self._elevated_process_id), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=(subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
                )
            except Exception:
                pass

        launcher = self._launcher
        if launcher is not None:
            try:
                if launcher.poll() is None:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(launcher.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=(subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
                        )
                    else:
                        launcher.terminate()
            except Exception:
                try:
                    launcher.kill()
                except Exception:
                    pass

    def _check_cancelled(self):
        if self._cancel_requested:
            raise InterruptedError("ISO oluşturma işlemi kullanıcı tarafından durduruldu.")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest().lower()

    @staticmethod
    def _safe_name(value: str) -> str:
        value = re.sub(r'[^A-Za-z0-9._-]+', '_', value.strip())
        return value.strip('_') or "Windows_UUP"

    @staticmethod
    def _directory_size(path: Path) -> int:
        total = 0
        try:
            for item in path.rglob("*"):
                try:
                    if item.is_file():
                        total += item.stat().st_size
                except OSError:
                    continue
        except Exception:
            pass
        return total

    @staticmethod
    def required_space_for_size(uup_size: int) -> int:
        """UUP paketleri `uup_size` bayt olduğunda ISO dönüştürme için gereken çalışma alanı (tahmin)."""
        gib = 1024 ** 3
        return max(24 * gib, int(uup_size * 3.25) + 8 * gib)

    @classmethod
    def estimate_required_free_space(cls, uup_dir: Path) -> int:
        """Conservative workspace estimate for UUP -> WIM/ISO conversion.

        The converter can temporarily hold reference ESD/WIM data, an expanded
        Windows image and the final ISO at the same time. A simple UUP-size-only
        check therefore underestimates the real workspace requirement.
        """
        gib = 1024 ** 3
        uup_size = cls._directory_size(uup_dir)
        # Keep at least 24 GiB available; larger UUP sets scale up automatically.
        return cls.required_space_for_size(uup_size)

    def _check_disk_space(self, project_dir: Path, uup_dir: Path):
        required = self.estimate_required_free_space(uup_dir)
        usage = shutil.disk_usage(project_dir)
        free = int(usage.free)
        self.status.emit(
            self.batch_id,
            f"Disk alanı kontrol ediliyor: gerekli yaklaşık {required / (1024**3):.1f} GB, "
            f"boş {free / (1024**3):.1f} GB"
        )
        if free < required:
            raise RuntimeError(
                "YETERSIZ_DISK_ALANI|"
                f"{required}|{free}|{project_dir}|"
                "ISO oluşturma için çalışma diskinde yeterli boş alan yok."
            )

    def _download_file(self, session, url: str, destination: Path):
        self._check_cancelled()
        with session.get(url, stream=True, timeout=(20, 180)) as response:
            response.raise_for_status()
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)

    def _parse_manifest(self, text: str) -> list[dict]:
        entries = []
        current = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                if current.get("url") and current.get("out"):
                    entries.append(current)
                current = {}
                continue
            if line.startswith("http://") or line.startswith("https://"):
                current["url"] = line
            elif line.startswith("out="):
                current["out"] = line.split("=", 1)[1].strip()
            elif line.lower().startswith("checksum=sha-256="):
                current["sha256"] = line.split("=", 2)[2].strip().lower()
        if current.get("url") and current.get("out"):
            entries.append(current)
        return entries

    def _ensure_converter(self, project_dir: Path) -> Path:
        converter_cmd = project_dir / "convert-UUP.cmd"
        if converter_cmd.exists():
            return converter_cmd

        self.status.emit(self.batch_id, "ISO dönüştürme araçları hazırlanıyor...")
        cache_dir = (
            ISO_TASKS_PATH.parent
            / "tools"
            / "uup_converter"
        )
        cache_dir.mkdir(parents=True, exist_ok=True)

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150 Safari/537.36"
            )
        })

        manifest_response = session.get(MANIFEST_URL, timeout=30)
        manifest_response.raise_for_status()
        entries = self._parse_manifest(manifest_response.text)
        if not entries:
            raise RuntimeError("UUP converter indirme listesi okunamadı.")

        files = {}
        for entry in entries:
            target = cache_dir / entry["out"]
            expected = entry.get("sha256", "")
            valid = target.exists()
            if valid and expected:
                valid = self._sha256(target) == expected
            if not valid:
                self.status.emit(
                    self.batch_id,
                    f"Gerekli araç indiriliyor: {entry['out']}"
                )
                self._download_file(session, entry["url"], target)
                if expected and self._sha256(target) != expected:
                    target.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"Araç bütünlük kontrolü başarısız: {entry['out']}"
                    )
            files[entry["out"].lower()] = target

        seven_zip = files.get("7zr.exe")
        archive = files.get("uup-converter-wimlib.7z")
        if seven_zip is None or archive is None:
            raise RuntimeError("UUP converter paketinin gerekli dosyaları eksik.")

        self.status.emit(self.batch_id, "UUP converter çalışma klasörüne çıkarılıyor...")
        process = subprocess.run(
            [str(seven_zip), "x", "-y", str(archive)],
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
        if process.returncode != 0:
            raise RuntimeError(
                "UUP converter çıkarılamadı.\n" + process.stdout[-2000:]
            )

        converter_cmd = project_dir / "convert-UUP.cmd"
        if not converter_cmd.exists():
            candidates = list(project_dir.rglob("convert-UUP.cmd"))
            if candidates:
                source = candidates[0]
                # Keep the converter in its extracted directory if nested.
                return source
            raise RuntimeError("convert-UUP.cmd bulunamadı.")
        return converter_cmd

    def _ensure_convert_config(self, converter_dir: Path):
        # The converter archive ships with its own default config. We always
        # overwrite it with the application's unattended configuration so the
        # converter never stops at the interactive menu.
        config = converter_dir / "ConvertConfig.ini"
        config.write_text(
            """[convert-UUP]
AutoStart =1
AddUpdates =1
Cleanup =1
ResetBase =0
NetFx3 =0
StartVirtual =0
wim2esd =0
wim2swm =0
SkipISO =0
SkipWinRE =0
LCUwinre =0
LCUmsuExpand =0
UpdtBootFiles=0
ForceDism =0
RefESD =0
SkipLCUmsu =0
SkipEdge =0
AutoExit =1
DisableUpdatingUpgrade=0
AddDrivers =0
Drv_Source =\\Drivers

[Store_Apps]
SkipApps =0
AppsLevel =0
StubAppsFull =0
CustomList =0

[create_virtual_editions]
vUseDism =1
vAutoStart =1
vDeleteSource=0
vPreserve =0
vwim2esd =0
vwim2swm =0
vSkipISO =0
vAutoEditions=
vSortEditions=
""",
            encoding="utf-8",
        )

    @staticmethod
    def _is_windows_admin() -> bool:
        if os.name != "nt":
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @staticmethod
    def _hidden_startupinfo():
        if os.name != "nt":
            return None
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return startupinfo

    def _emit_log_progress(self, log_path: Path, last_text: str) -> str:
        """Tail every newly written converter line instead of sampling only EOF.

        UUP Converter often prints many lines while its final line remains unchanged.
        The old EOF-only reader therefore left the UI on a stale 20% milestone even
        though conversion was progressing. This incremental tailer preserves partial
        lines and emits all fresh non-empty output in order.
        """
        try:
            if not log_path.exists():
                return last_text

            size = log_path.stat().st_size
            if size < self._log_offset:
                # Converter recreated/truncated its log.
                self._log_offset = 0
                self._log_remainder = ""

            if size == self._log_offset:
                return last_text

            with log_path.open("rb") as handle:
                handle.seek(self._log_offset)
                raw = handle.read()
                self._log_offset = handle.tell()

            if not raw:
                return last_text

            chunk = raw.decode("utf-8", errors="replace")
            combined = self._log_remainder + chunk
            lines = combined.splitlines(keepends=True)
            self._log_remainder = ""

            if lines and not lines[-1].endswith(("\n", "\r")):
                self._log_remainder = lines.pop()

            latest = last_text
            # Limit a single UI burst while still preserving the newest meaningful
            # activity if a tool writes hundreds of lines at once.
            cleaned_lines = [line.strip() for line in lines if line.strip()]
            for line in cleaned_lines[-80:]:
                latest = line[-360:]
                self.status.emit(self.batch_id, latest)
                self._log_last_activity = time.monotonic()

            return latest
        except Exception:
            return last_text

    def _start_elevated_hidden(self, executable: str, parameters: str, cwd: Path):
        """Start an elevated process with a real process handle via ShellExecuteEx.

        PowerShell Start-Process introduced an extra launcher layer and fragile nested
        quoting around CMD files. In some environments the PowerShell process stayed
        alive while the converter wrapper never started, leaving the UI forever on
        the first stage. ShellExecuteEx gives us the actual elevated cmd.exe process
        handle so startup, completion and cancellation can be tracked reliably.
        """
        if os.name != "nt":
            raise RuntimeError("Yönetici süreci yalnızca Windows üzerinde kullanılabilir.")

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
        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
        info.lpVerb = "runas"
        info.lpFile = executable
        info.lpParameters = parameters
        info.lpDirectory = str(cwd)
        info.nShow = SW_HIDE

        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error == 1223:
                raise RuntimeError("Yönetici izni kullanıcı tarafından iptal edildi.")
            raise RuntimeError(f"ISO dönüştürücü yönetici olarak başlatılamadı. Windows hata kodu: {error}")
        if not info.hProcess:
            raise RuntimeError("ISO dönüştürücünün işlem tanıtıcısı alınamadı.")

        pid = int(kernel32.GetProcessId(info.hProcess))
        self._elevated_process_handle = info.hProcess
        self._elevated_process_id = pid
        return info.hProcess, pid

    @staticmethod
    def _process_exit_code(process_handle):
        STILL_ACTIVE = 259
        code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(process_handle, ctypes.byref(code)):
            return None
        if code.value == STILL_ACTIVE:
            return None
        return int(code.value)

    def _close_elevated_handle(self):
        handle = self._elevated_process_handle
        self._elevated_process_handle = None
        self._elevated_process_id = 0
        if handle:
            try:
                ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                pass

    def _run_windows_converter_hidden(
        self,
        converter_dir: Path,
        converter_cmd: Path,
        log_path: Path,
    ) -> int:
        """Run UUP Converter hidden and monitor the real converter process.

        The previous PowerShell-based elevation could get stuck before the wrapper
        started, producing no converter log at all. This version launches elevated
        cmd.exe directly via ShellExecuteEx and validates that the wrapper actually
        creates its log shortly after startup.
        """
        started_file = converter_dir / "_mdl_iso_started.txt"
        done_file = converter_dir / "_mdl_iso_done.txt"
        exit_file = converter_dir / "_mdl_iso_exit.txt"
        wrapper = converter_dir / "_mdl_iso_background.cmd"

        for marker in (started_file, done_file, exit_file, log_path):
            try:
                marker.unlink(missing_ok=True)
            except Exception:
                pass

        # Keep the wrapper strictly ASCII and use only relative paths. Windows
        # cmd.exe reads batch files using the active system code page; embedding
        # absolute UTF-8 paths such as C:\Users\Bünyamin... can corrupt marker
        # and log paths even when the elevated process exits with code 0.
        wrapper.write_text(
            "@echo off\r\n"
            "setlocal EnableExtensions DisableDelayedExpansion\r\n"
            "cd /d \"%~dp0\"\r\n"
            "> \"_mdl_iso_started.txt\" echo STARTED\r\n"
            "> \"iso_conversion.log\" echo [MDL] UUP Converter baslatiliyor...\r\n"
            f"call \"{converter_cmd.name}\" >> \"iso_conversion.log\" 2>&1\r\n"
            "set \"MDL_EXIT=%ERRORLEVEL%\"\r\n"
            "> \"_mdl_iso_exit.txt\" echo %MDL_EXIT%\r\n"
            "> \"_mdl_iso_done.txt\" echo DONE\r\n"
            "exit /b %MDL_EXIT%\r\n",
            encoding="ascii",
        )

        self.status.emit(self.batch_id, "UUP Converter işlemi başlatılıyor...")

        if self._is_windows_admin():
            creationflags = (
                subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            )
            launcher = subprocess.Popen(
                ["cmd.exe", "/d", "/c", str(wrapper)],
                cwd=str(converter_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                startupinfo=self._hidden_startupinfo(),
            )
            self._launcher = launcher
            process_handle = None
        else:
            # cmd.exe receives the wrapper path as a normal /c argument. ShellExecuteEx
            # handles elevation itself, avoiding the nested PowerShell quoting layer.
            params = f'/d /c ""{wrapper}""'
            process_handle, _pid = self._start_elevated_hidden(
                os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe"),
                params,
                converter_dir,
            )
            launcher = None

        last_text = ""
        last_emit = 0.0
        started_at = time.monotonic()
        hard_timeout = 12 * 60 * 60
        startup_deadline = started_at + 45

        try:
            while True:
                if self._cancel_requested:
                    self.cancel()
                    raise InterruptedError("ISO oluşturma işlemi kullanıcı tarafından durduruldu.")

                if done_file.exists():
                    break

                if launcher is not None:
                    launcher_code = launcher.poll()
                    if launcher_code is not None and not done_file.exists():
                        tail = ""
                        try:
                            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2500:]
                        except Exception:
                            pass
                        raise RuntimeError(
                            "ISO dönüştürücü wrapper tamamlanmadan kapandı. "
                            f"Çıkış kodu: {launcher_code}.\n{tail}"
                        )
                elif process_handle:
                    exit_code = self._process_exit_code(process_handle)
                    if exit_code is not None and not done_file.exists():
                        tail = ""
                        try:
                            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2500:]
                        except Exception:
                            pass
                        raise RuntimeError(
                            "Yönetici yetkili ISO dönüştürücü tamamlanma işaretini oluşturmadan kapandı. "
                            f"Çıkış kodu: {exit_code}.\n{tail}"
                        )

                now = time.monotonic()
                if now > startup_deadline and not started_file.exists():
                    self.cancel()
                    raise RuntimeError(
                        "ISO dönüştürücü wrapper 45 saniye içinde çalışmaya başlamadı. "
                        "Yönetici izni, Windows güvenlik yazılımı veya komut dosyası çalıştırma ilkesi işlemi engelliyor olabilir."
                    )

                if now - started_at > hard_timeout:
                    self.cancel()
                    raise RuntimeError("ISO dönüştürme işlemi 12 saatlik güvenlik süresini aştı.")

                if now - last_emit >= 1.0:
                    last_text = self._emit_log_progress(log_path, last_text)
                    last_emit = now

                time.sleep(0.35)

            if launcher is not None:
                try:
                    launcher.wait(timeout=30)
                except Exception:
                    pass

            last_text = self._emit_log_progress(log_path, last_text)
            if not started_file.exists():
                raise RuntimeError("ISO dönüştürücü wrapper hiç başlatılamadı.")
            if not done_file.exists():
                raise RuntimeError("ISO dönüştürücü tamamlanma işaretini oluşturmadı.")
            try:
                return int(exit_file.read_text(encoding="utf-8", errors="replace").strip())
            except Exception:
                if launcher is not None:
                    return int(launcher.returncode or 0)
                exit_code = self._process_exit_code(process_handle) if process_handle else 0
                return int(exit_code or 0)
        finally:
            self._close_elevated_handle()

    def _run_converter(self, project_dir: Path, converter_cmd: Path) -> Path:
        self.status.emit(
            self.batch_id,
            "UUP dosyaları Windows kurulum imajına dönüştürülüyor. Bu işlem uzun sürebilir..."
        )

        log_path = project_dir / "iso_conversion.log"
        conversion_started_wall = time.time() - 5

        converter_dir = converter_cmd.parent
        self._ensure_convert_config(converter_dir)
        # The official converter expects a UUPs directory relative to itself.
        expected_uups = converter_dir / "UUPs"
        source_uups = Path(self.metadata["uup_dir"])
        if expected_uups.resolve() != source_uups.resolve():
            if expected_uups.exists() or expected_uups.is_symlink():
                if expected_uups.is_dir() and not expected_uups.is_symlink():
                    shutil.rmtree(expected_uups, ignore_errors=True)
                else:
                    expected_uups.unlink(missing_ok=True)
            try:
                # A directory junction avoids duplicating several GB of UUP data.
                if os.name == "nt":
                    subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(expected_uups), str(source_uups)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW
                            if hasattr(subprocess, "CREATE_NO_WINDOW")
                            else 0
                        ),
                        check=True,
                    )
                else:
                    expected_uups.symlink_to(source_uups, target_is_directory=True)
            except Exception:
                # Fallback: converter can live in project root where UUPs already exists.
                if source_uups.name.lower() == "uups" and source_uups.parent == converter_dir:
                    pass
                else:
                    raise RuntimeError(
                        "UUP klasörü ISO dönüştürücüye bağlanamadı."
                    )

        if log_path.exists():
            try:
                log_path.unlink()
            except Exception:
                pass
        self._log_offset = 0
        self._log_remainder = ""
        self._log_last_activity = time.monotonic()

        if os.name == "nt":
            self.status.emit(
                self.batch_id,
                "ISO dönüştürme işlemi arka planda başlatılıyor..."
            )
            return_code = self._run_windows_converter_hidden(
                converter_dir,
                converter_cmd,
                log_path,
            )
        else:
            cmd = [str(converter_cmd)]
            with log_path.open("w", encoding="utf-8", errors="replace") as log:
                process = subprocess.Popen(
                    cmd,
                    cwd=str(converter_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                self._launcher = process
                last_status = 0.0
                for line in iter(process.stdout.readline, ""):
                    if self._cancel_requested:
                        self.cancel()
                        raise InterruptedError("ISO oluşturma işlemi kullanıcı tarafından durduruldu.")
                    log.write(line)
                    log.flush()
                    now = time.monotonic()
                    if now - last_status > 3:
                        cleaned = line.strip()
                        if cleaned:
                            self.status.emit(self.batch_id, cleaned[-220:])
                        last_status = now
                return_code = process.wait()

        if return_code != 0:
            tail = ""
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            except Exception:
                pass
            if "no space left on device" in tail.lower() or "not enough space" in tail.lower():
                required = self.estimate_required_free_space(Path(self.metadata["uup_dir"]))
                try:
                    free = int(shutil.disk_usage(project_dir).free)
                except Exception:
                    free = 0
                raise RuntimeError(
                    "YETERSIZ_DISK_ALANI|"
                    f"{required}|{free}|{project_dir}|"
                    "Dönüştürme sırasında çalışma diskindeki boş alan tükendi."
                )
            raise RuntimeError(
                f"ISO dönüştürme işlemi {return_code} koduyla sona erdi.\n{tail}"
            )

        # UUP Converter versions can place the ISO either in their own folder,
        # the project folder, or the parent folder. Search all relevant roots and
        # prefer files created/updated by this conversion run.
        source_uups = Path(self.metadata["uup_dir"])
        search_roots = []
        for root in (
            project_dir,
            converter_dir,
            source_uups.parent,
            project_dir.parent,
        ):
            try:
                resolved = root.resolve()
            except Exception:
                resolved = root
            if root.exists() and resolved not in [r.resolve() for r in search_roots]:
                search_roots.append(root)

        candidates = []
        seen = set()
        for root in search_roots:
            try:
                for iso in root.rglob("*.iso"):
                    resolved = iso.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    try:
                        if iso.stat().st_mtime >= conversion_started_wall:
                            candidates.append(iso)
                    except OSError:
                        continue
            except Exception:
                continue

        if not candidates:
            # Last-resort scan for any ISO in the project/converter trees. This is
            # useful when filesystem timestamps are rounded by the host filesystem.
            for root in search_roots[:3]:
                try:
                    for iso in root.rglob("*.iso"):
                        if iso.resolve() not in seen:
                            candidates.append(iso)
                            seen.add(iso.resolve())
                except Exception:
                    continue

        if not candidates:
            tail = ""
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-2500:]
            except Exception:
                pass
            raise RuntimeError(
                "Dönüştürme tamamlandı ancak ISO dosyası bulunamadı. "
                f"Ayrıntılar: {log_path}\n{tail}"
            )
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def run(self):
        try:
            uup_dir = Path(self.metadata.get("uup_dir", ""))
            project_dir = Path(self.metadata.get("project_dir", ""))
            if not uup_dir.exists():
                raise RuntimeError(f"UUP klasörü bulunamadı: {uup_dir}")
            if not project_dir:
                project_dir = uup_dir.parent
            project_dir.mkdir(parents=True, exist_ok=True)

            # Fail fast before spending minutes on conversion only to run out of
            # disk space while exporting install.wim. The user can then move only
            # the ISO workspace to another drive without redownloading UUP files.
            self._check_disk_space(project_dir, uup_dir)

            converter_cmd = self._ensure_converter(project_dir)
            iso_path = self._run_converter(project_dir, converter_cmd)

            build = self._safe_name(str(self.metadata.get("build", "Windows")))
            arch = self._safe_name(str(self.metadata.get("architecture", "")))
            lang = self._safe_name(str(self.metadata.get("language", "")))
            desired = project_dir / f"Windows_11_{build}_{arch}_{lang}.iso"
            if iso_path.resolve() != desired.resolve():
                if desired.exists():
                    desired.unlink()
                shutil.move(str(iso_path), str(desired))
                iso_path = desired

            self.status.emit(self.batch_id, "ISO dosyası doğrulanıyor ve SHA-256 hesaplanıyor...")
            self._check_cancelled()
            if not iso_path.exists() or iso_path.stat().st_size < 10 * 1024 * 1024:
                raise RuntimeError("Oluşturulan ISO dosyası geçersiz veya beklenenden küçük.")
            sha256 = self._sha256(iso_path)
            self._check_cancelled()
            self.finished.emit(self.batch_id, str(iso_path), sha256)
        except InterruptedError as exc:
            self.cancelled.emit(self.batch_id, str(exc))
        except Exception as exc:
            self.failed.emit(self.batch_id, str(exc))


class IsoBuildManager(QObject):
    status_changed = Signal(str, str)
    build_started = Signal(str)
    build_finished = Signal(str, str, str)
    build_failed = Signal(str, str)
    build_cancelled = Signal(str, str)
    queue_changed = Signal()

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._threads = {}
        self._workers = {}
        self._states = {}
        self._queue = []
        self._active_batch = None
        self._pending_retries = set()
        self._lock = threading.RLock()
        self._state_file = (
            ISO_TASKS_PATH
            if os.name == "nt"
            else Path.home() / ".microsoft_direkt_link_bulucu" / "iso_tasks.json"
        )
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_states()

    def _load_states(self):
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._states = raw
        except Exception:
            self._states = {}
        # Running work cannot survive an application restart. Make it retryable.
        for state in self._states.values():
            if state.get("status") in {"Hazırlanıyor", "Dönüştürülüyor", "Doğrulanıyor"}:
                state["status"] = "Bekliyor"
                state["message"] = "Uygulama yeniden başlatıldı; görev yeniden başlatılabilir."
        self._save_states()

    def _save_states(self):
        try:
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._states, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._state_file)
        except Exception:
            pass

    def state(self, batch_id: str) -> dict:
        return dict(self._states.get(batch_id, {}))

    def all_states(self) -> dict:
        return {key: dict(value) for key, value in self._states.items()}

    def _set_state(self, batch_id: str, **updates):
        with self._lock:
            state = self._states.setdefault(batch_id, {})
            state.update(updates)
            state["updated_at"] = time.time()
            self._save_states()
        self.queue_changed.emit()

    def start_build(self, batch_id: str, metadata: dict):
        metadata = dict(metadata or {})
        with self._lock:
            if batch_id in self._threads or batch_id in self._queue:
                return

            previous = self._states.get(batch_id, {})
            iso_path_value = previous.get("iso_path", "") or metadata.get("iso_path", "")
            iso_path = Path(iso_path_value) if iso_path_value else None
            if iso_path is not None and iso_path.is_file() and iso_path.suffix.lower() == ".iso":
                sha256 = previous.get("sha256", "")
                self._set_state(
                    batch_id, status="Hazır", message="ISO hazır",
                    iso_path=str(iso_path), sha256=sha256, metadata=metadata or previous.get("metadata", {})
                )
                self.build_finished.emit(batch_id, str(iso_path), sha256)
                return

            self._set_state(
                batch_id, status="Bekliyor", message="ISO oluşturma kuyruğunda bekliyor",
                iso_path="", sha256="", metadata=metadata
            )
            self._queue.append(batch_id)
        self.status_changed.emit(batch_id, "ISO oluşturma kuyruğuna eklendi...")
        self._pump_queue()

    READY_STATUS = "İndirme Tamamlandı"

    def mark_ready(self, batch_id: str, metadata: dict):
        """İndirme bitti ama ISO otomatik başlatılmayacak: kullanıcı düğmeyle başlatır."""
        metadata = dict(metadata or {})
        with self._lock:
            if batch_id in self._threads or batch_id in self._queue:
                return
            previous = self._states.get(batch_id, {})
            if previous.get("status") == "Hazır":
                return
            self._set_state(
                batch_id, status=self.READY_STATUS,
                message="İndirme tamamlandı; ISO'yu oluşturmak için düğmeye basın",
                iso_path="", sha256="", metadata=metadata or previous.get("metadata", {}),
            )

    def retry_build(self, batch_id: str):
        state = self._states.get(batch_id, {})
        metadata = dict(state.get("metadata", {}) or {})
        if not metadata:
            return False

        # The failed/cancelled worker may still be in its final QThread cleanup
        # for a few milliseconds. Accept the click immediately and enqueue the
        # retry from _cleanup instead of silently ignoring the user's action.
        if batch_id in self._threads:
            self._pending_retries.add(batch_id)
            self._set_state(
                batch_id, status="Bekliyor",
                message="Mevcut işlem kapatılıyor; görev birazdan yeniden başlatılacak",
                iso_path="", sha256=""
            )
            self.status_changed.emit(
                batch_id, "Mevcut ISO süreci temizleniyor; yeniden deneme otomatik başlayacak..."
            )
            return True

        if batch_id in self._queue:
            self._queue.remove(batch_id)
        self._set_state(batch_id, status="Bekliyor", message="ISO görevi yeniden denenecek", iso_path="", sha256="")
        self._queue.append(batch_id)
        self.status_changed.emit(batch_id, "ISO görevi yeniden sıraya alındı...")
        self._pump_queue()
        return True

    def required_space(self, batch_id: str) -> int:
        state = self._states.get(batch_id, {})
        metadata = dict(state.get("metadata", {}) or {})
        raw = metadata.get("uup_dir", "")
        path = Path(raw) if raw else None
        if path is None or not path.exists():
            return 24 * (1024 ** 3)
        return IsoBuildWorker.estimate_required_free_space(path)

    def change_work_dir_and_retry(self, batch_id: str, project_dir: str) -> bool:
        state = self._states.get(batch_id, {})
        metadata = dict(state.get("metadata", {}) or {})
        if not metadata or not project_dir:
            return False
        target = Path(project_dir)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False
        metadata["project_dir"] = str(target)
        self._set_state(
            batch_id, metadata=metadata, status="Bekliyor",
            message="Yeni ISO çalışma konumu seçildi; görev yeniden başlatılacak",
            iso_path="", sha256=""
        )
        return self.retry_build(batch_id)

    def cancel_build(self, batch_id: str):
        if batch_id in self._queue:
            self._queue.remove(batch_id)
            self._set_state(batch_id, status="İptal", message="ISO görevi kullanıcı tarafından iptal edildi")
            self.build_cancelled.emit(batch_id, "ISO görevi kullanıcı tarafından iptal edildi.")
            return True
        worker = self._workers.get(batch_id)
        if worker:
            worker.cancel()
            self._set_state(batch_id, status="İptal ediliyor", message="ISO işlemi durduruluyor...")
            return True
        return False

    def _pump_queue(self):
        with self._lock:
            if self._active_batch is not None or not self._queue:
                return
            batch_id = self._queue.pop(0)
            state = self._states.get(batch_id, {})
            metadata = dict(state.get("metadata", {}) or {})
            if not metadata:
                self._set_state(batch_id, status="Hata", message="ISO görev bilgileri bulunamadı")
                self.build_failed.emit(batch_id, "ISO görev bilgileri bulunamadı.")
                QTimer.singleShot(0, self._pump_queue)
                return
            self._active_batch = batch_id

        self._set_state(batch_id, status="Hazırlanıyor", message="ISO oluşturma işlemi hazırlanıyor")
        self.build_started.emit(batch_id)
        self.status_changed.emit(batch_id, "ISO oluşturma işlemi hazırlanıyor...")

        thread = QThread(self)
        worker = IsoBuildWorker(batch_id, metadata)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(self._on_status)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(lambda bid=batch_id: self._cleanup(bid))
        self._threads[batch_id] = thread
        self._workers[batch_id] = worker
        thread.start()

    def shutdown(self, timeout_ms: int = 1500) -> None:
        """Program kapanırken iş parçacıklarının "çalışırken yok edildi" hatasıyla çökmesini önler."""
        for thread in list(self._threads.values()):
            try:
                thread.quit()
                thread.wait(300)  # çalışan dönüştürme süreci bilerek kesilmez; süreç sonlanırken bırakılır
            except RuntimeError:
                pass

    def _on_status(self, batch_id: str, message: str):
        lower = message.lower()
        status = "Dönüştürülüyor"
        if "doğrulan" in lower or "sha-256" in lower:
            status = "Doğrulanıyor"
        elif "hazırl" in lower or "converter" in lower or "araç" in lower:
            status = "Hazırlanıyor"
        self._set_state(batch_id, status=status, message=message)
        self.status_changed.emit(batch_id, message)

    def _on_finished(self, batch_id: str, iso_path: str, sha256: str):
        previous = self._states.get(batch_id, {})
        size = 0
        try:
            size = Path(iso_path).stat().st_size
        except Exception:
            pass
        self._set_state(
            batch_id, status="Hazır", message="ISO başarıyla oluşturuldu ve doğrulandı",
            iso_path=iso_path, sha256=sha256, size=size, metadata=previous.get("metadata", {})
        )
        self.build_finished.emit(batch_id, iso_path, sha256)

    def _on_failed(self, batch_id: str, message: str):
        previous = self._states.get(batch_id, {})
        self._set_state(
            batch_id, status="Hata", message=message, iso_path="",
            metadata=previous.get("metadata", {})
        )
        self.build_failed.emit(batch_id, message)

    def _on_cancelled(self, batch_id: str, message: str):
        previous = self._states.get(batch_id, {})
        self._set_state(
            batch_id, status="İptal", message=message, iso_path="",
            metadata=previous.get("metadata", {})
        )
        self.build_cancelled.emit(batch_id, message)

    def _cleanup(self, batch_id: str):
        worker = self._workers.pop(batch_id, None)
        thread = self._threads.pop(batch_id, None)
        if worker:
            worker.deleteLater()
        if thread:
            thread.deleteLater()
        with self._lock:
            if self._active_batch == batch_id:
                self._active_batch = None
            should_retry = batch_id in self._pending_retries
            if should_retry:
                self._pending_retries.discard(batch_id)
                if batch_id not in self._queue:
                    self._queue.append(batch_id)
        if should_retry:
            self.status_changed.emit(batch_id, "ISO görevi yeniden başlatılıyor...")
        self.queue_changed.emit()
        QTimer.singleShot(0, self._pump_queue)

