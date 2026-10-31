"""Sürücü yedekleme / geri yükleme servisi (yalnızca Windows).

Yalnızca Windows'un kendi komutlarını kullanır:
  * Listeleme  : Win32_PnPSignedDriver (CIM) – yönetici yetkisi gerekmez.
  * Yedekleme  : pnputil /export-driver <oemN.inf> <klasör>  – yönetici yetkisi gerekir.
  * Geri yükle : pnputil /add-driver <klasör>\\*.inf /subdirs /install – yönetici yetkisi gerekir.
  * Sorunlu aygıtlar: Win32_PnPEntity.ConfigManagerErrorCode – yönetici yetkisi gerekmez.

Yalnızca üçüncü taraf (OEM) sürücüler oemN.inf adıyla DriverStore'a girer; Windows'un
kendi sürücüleri bu paketlerde yer almaz. Bu bilinçli bir sınırdır ve arayüzde yazılıdır.

Yükseltilmiş işlem, ana programdan ayrı bir PowerShell sürecidir. İlerleme ve iptal,
geçici bir ilerleme dosyası ile iptal bayrağı dosyası üzerinden yürür; böylece UAC
penceresi tek kez çıkar.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from services.usb_media_service import UsbMediaService

# oem12.inf gibi: DriverStore'a sonradan eklenen (üçüncü taraf) paketler
_OEM_INF = re.compile(r"^oem\d+\.inf$", re.IGNORECASE)

CLASS_NAMES_TR = {
    "DISPLAY": "Ekran",
    "NET": "Ağ",
    "MEDIA": "Ses / Medya",
    "SYSTEM": "Sistem",
    "USB": "USB",
    "BLUETOOTH": "Bluetooth",
    "HIDCLASS": "Giriş aygıtı",
    "HDC": "Disk denetleyici",
    "SCSIADAPTER": "Depolama",
    "DISKDRIVE": "Disk",
    "PRINTER": "Yazıcı",
    "PRINTQUEUE": "Yazıcı",
    "CAMERA": "Kamera",
    "IMAGE": "Kamera / Tarayıcı",
    "FIRMWARE": "Üretici yazılımı",
    "SOFTWAREDEVICE": "Yazılım aygıtı",
    "SOFTWARECOMPONENT": "Yazılım bileşeni",
    "EXTENSION": "Uzantı",
    "BIOMETRIC": "Biyometrik",
    "MONITOR": "Monitör",
    "PROCESSOR": "İşlemci",
    "SENSOR": "Sensör",
    "KEYBOARD": "Klavye",
    "MOUSE": "Fare",
    "BATTERY": "Pil",
    "PORTS": "Bağlantı noktası",
    "SMARTCARDREADER": "Akıllı kart okuyucu",
    "WPD": "Taşınabilir aygıt",
    "NETSERVICE": "Ağ hizmeti",
    "NETCLIENT": "Ağ istemcisi",
    "NETTRANS": "Ağ protokolü",
    "AUDIOENDPOINT": "Ses uç noktası",
}

# Aygıt Yöneticisi hata kodları (kısa Türkçe açıklama, gerçekten sürücü sorunu mu?)
PROBLEM_CODES = {
    1: ("Aygıt doğru yapılandırılmamış", True),
    3: ("Bellek yetersiz ya da sürücü bozuk", True),
    10: ("Aygıt başlatılamıyor", True),
    12: ("Kaynak çakışması", True),
    14: ("Yeniden başlatma gerekiyor", False),
    18: ("Sürücü yeniden yüklenmeli", True),
    19: ("Kayıt defteri bilgisi bozuk", True),
    21: ("Windows aygıtı kaldırıyor", False),
    22: ("Aygıt devre dışı", False),
    24: ("Aygıt yok ya da düzgün çalışmıyor", True),
    28: ("Sürücü yüklü değil", True),
    31: ("Aygıt düzgün çalışmıyor", True),
    32: ("Sürücü devre dışı", True),
    37: ("Sürücü başlatılamadı", True),
    39: ("Sürücü yüklenemedi (bozuk ya da eksik)", True),
    40: ("Kayıt defteri bilgisi eksik", True),
    41: ("Aygıt yüklendi ama bulunamadı", True),
    43: ("Aygıt sorun bildirdiği için durduruldu", True),
    45: ("Aygıt şu an bağlı değil", False),
    52: ("Sürücü imzası doğrulanamıyor", True),
}


@dataclass
class DriverInfo:
    inf_name: str            # oem12.inf
    device_name: str         # ilk aygıtın adı
    device_count: int = 1    # bu paketi kullanan aygıt sayısı
    provider: str = ""
    class_name: str = ""     # Türkçe sınıf adı
    class_raw: str = ""
    version: str = ""
    date: str = ""
    signed: bool = True
    selected: bool = True
    size_bytes: int = 0      # sürücü deposundaki paket boyutu (0 = bilinmiyor)

    @property
    def display_name(self) -> str:
        if self.device_count > 1:
            return f"{self.device_name} (+{self.device_count - 1})"
        return self.device_name


@dataclass
class ProblemDevice:
    name: str
    class_name: str
    code: int
    reason: str
    driver_related: bool


@dataclass
class BackupResult:
    folder: Path
    total: int
    ok: int
    failed: list[str] = field(default_factory=list)
    cancelled: bool = False
    size_bytes: int = 0
    inf_count: int = 0


def is_third_party_inf(inf_name: str) -> bool:
    return bool(_OEM_INF.match((inf_name or "").strip()))


def format_size(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def folder_size(path: Path) -> int:
    total = 0
    try:
        for item in Path(path).rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def count_inf_files(path: Path) -> int:
    try:
        return sum(1 for _ in Path(path).rglob("*.inf"))
    except OSError:
        return 0


# Türkçe Windows'ta PowerShell çıktısı OEM kod sayfasıyla (857) gelir; program UTF-8 okuduğu için
# "ı, ş, ğ, ü, ö, ç" gibi harfler "�" olurdu. Çıktıyı UTF-8'e zorlarız.
_PS_UTF8 = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
    "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
)


def _ps_quote(value: str) -> str:
    """PowerShell tek tırnaklı dize: içindeki tırnaklar ikiye katlanır."""
    return "'" + str(value).replace("'", "''") + "'"


class DriverBackupService:
    # ------------------------------------------------------------------ listeleme
    @staticmethod
    def is_supported_platform() -> bool:
        return UsbMediaService.is_supported_platform()

    @staticmethod
    def is_admin() -> bool:
        return UsbMediaService._is_windows_admin()

    @staticmethod
    def parse_drivers(raw: str) -> list[DriverInfo]:
        """PowerShell'in JSON çıktısını üçüncü taraf paket başına tek satıra indirger."""
        raw = (raw or "").strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        grouped: dict[str, DriverInfo] = {}
        for item in data:
            inf = str(item.get("InfName") or "").strip()
            if not is_third_party_inf(inf):
                continue
            key = inf.lower()
            device = str(item.get("DeviceName") or "").strip() or "Bilinmeyen aygıt"
            if key in grouped:
                grouped[key].device_count += 1
                continue
            class_raw = str(item.get("DeviceClass") or "").strip()
            grouped[key] = DriverInfo(
                inf_name=inf,
                device_name=device,
                provider=str(item.get("Provider") or item.get("Manufacturer") or "").strip(),
                class_name=CLASS_NAMES_TR.get(class_raw.upper(), class_raw.title() if class_raw else "Diğer"),
                class_raw=class_raw,
                version=str(item.get("DriverVersion") or "").strip(),
                date=str(item.get("DriverDate") or "").strip(),
                signed=bool(item.get("IsSigned", True)),
            )
        return sorted(
            grouped.values(),
            key=lambda d: (d.class_name.lower(), d.device_name.lower()),
        )

    @classmethod
    def list_drivers(cls) -> list[DriverInfo]:
        if not cls.is_supported_platform():
            return []
        script = r'''
$items = Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
    Where-Object { $_.InfName -match '^oem\d+\.inf$' } |
    ForEach-Object {
        [PSCustomObject]@{
            InfName = [string]$_.InfName
            DeviceName = [string]$_.DeviceName
            Provider = [string]$_.DriverProviderName
            Manufacturer = [string]$_.Manufacturer
            DeviceClass = [string]$_.DeviceClass
            DriverVersion = [string]$_.DriverVersion
            DriverDate = if ($_.DriverDate) { ([datetime]$_.DriverDate).ToString('yyyy-MM-dd') } else { '' }
            IsSigned = [bool]$_.IsSigned
        }
    }
$items | ConvertTo-Json -Compress
'''
        raw = UsbMediaService._powershell(_PS_UTF8 + script, timeout=90)
        return cls.parse_drivers(raw)

    @staticmethod
    def parse_size_map(raw: str) -> dict[str, int]:
        """PowerShell'in {"oem42.inf": bayt} JSON çıktısını sözlüğe çevirir."""
        raw = (raw or "").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in data.items():
            try:
                size = int(value)
            except (TypeError, ValueError):
                continue
            if size > 0:
                result[str(key).lower()] = size
        return result

    @classmethod
    def estimate_sizes(cls, drivers: list[DriverInfo]) -> dict[str, int]:
        """Her paketin sürücü deposundaki boyutunu bulur (yönetici izni gerekmez).

        C:\\Windows\\INF\\oemNN.inf dosyasının SHA-1'i, DriverStore\\FileRepository içindeki özgün .inf ile
        eşleştirilir; eşleşen klasörün toplam boyutu paketin boyutudur. Eşleşmeyen paketler sonuçta yer almaz.
        """
        if not cls.is_supported_platform() or not drivers:
            return {}
        names = ", ".join(_ps_quote(d.inf_name) for d in drivers)
        script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$names = @({names})
$infDir = Join-Path $env:windir 'INF'
$repo = Join-Path $env:windir 'System32\\DriverStore\\FileRepository'
$byHash = @{{}}; $lens = @{{}}
foreach ($n in $names) {{
    $p = Join-Path $infDir $n
    $fi = Get-Item -LiteralPath $p
    if ($fi) {{ $lens[[string]$fi.Length] = $true; $byHash[(Get-FileHash -Algorithm SHA1 -LiteralPath $p).Hash] = $n }}
}}
$res = @{{}}
foreach ($f in Get-ChildItem -LiteralPath $repo -Recurse -Depth 1 -Filter '*.inf' -File) {{
    if (-not $lens.ContainsKey([string]$f.Length)) {{ continue }}
    $h = (Get-FileHash -Algorithm SHA1 -LiteralPath $f.FullName).Hash
    if ($byHash.ContainsKey($h)) {{
        $n = $byHash[$h]
        $size = (Get-ChildItem -LiteralPath $f.Directory.FullName -Recurse -File | Measure-Object Length -Sum).Sum
        if (-not $res.ContainsKey($n) -or $size -gt $res[$n]) {{ $res[$n] = [int64]$size }}
    }}
}}
$res | ConvertTo-Json -Compress
"""
        raw = UsbMediaService._powershell(_PS_UTF8 + script, timeout=180)
        return cls.parse_size_map(raw)

    @staticmethod
    def estimate_total(drivers: list[DriverInfo]) -> tuple[int, int]:
        """(tahmini toplam bayt, boyutu bilinen paket sayısı). Bilinmeyenler için bilinenlerin ortancası kullanılır."""
        known = sorted(d.size_bytes for d in drivers if d.size_bytes > 0)
        if not known:
            return 0, 0
        median = known[len(known) // 2]
        unknown = len(drivers) - len(known)
        return sum(known) + unknown * median, len(known)

    @staticmethod
    def parse_problem_devices(raw: str) -> list[ProblemDevice]:
        raw = (raw or "").strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        result: list[ProblemDevice] = []
        for item in data:
            try:
                code = int(item.get("Code"))
            except (TypeError, ValueError):
                continue
            if code == 0:
                continue
            reason, related = PROBLEM_CODES.get(code, (f"Hata kodu {code}", True))
            class_raw = str(item.get("Class") or "").strip()
            result.append(
                ProblemDevice(
                    name=str(item.get("Name") or "Bilinmeyen aygıt").strip(),
                    class_name=CLASS_NAMES_TR.get(class_raw.upper(), class_raw.title() if class_raw else "Diğer"),
                    code=code,
                    reason=reason,
                    driver_related=related,
                )
            )
        # Sürücü sorunu olanlar önce
        result.sort(key=lambda p: (not p.driver_related, p.name.lower()))
        return result

    @classmethod
    def list_problem_devices(cls) -> list[ProblemDevice]:
        if not cls.is_supported_platform():
            return []
        script = r'''
$items = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
    Where-Object { $_.ConfigManagerErrorCode -ne 0 } |
    ForEach-Object {
        [PSCustomObject]@{
            Name = [string]$_.Name
            Class = [string]$_.PNPClass
            Code = [int]$_.ConfigManagerErrorCode
        }
    }
$items | ConvertTo-Json -Compress
'''
        raw = UsbMediaService._powershell(_PS_UTF8 + script, timeout=90)
        return cls.parse_problem_devices(raw)

    # ------------------------------------------------------------ yedek klasörü
    @staticmethod
    def default_backup_root() -> Path:
        docs = Path.home() / "Documents"
        return docs if docs.exists() else Path.home()

    @staticmethod
    def new_backup_folder(parent: Path) -> Path:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        host = re.sub(r"[^A-Za-z0-9_-]", "", socket.gethostname()) or "PC"
        base = Path(parent) / f"Surucu_Yedegi_{host}_{stamp}"
        folder, n = base, 2
        while folder.exists():
            folder = Path(f"{base}_{n}")
            n += 1
        return folder

    @staticmethod
    def check_free_space(path: Path) -> tuple[int, str | None]:
        """Boş alanı ve (varsa) uyarı metnini döner. Yedek boyutu önceden kesin bilinmez."""
        probe = Path(path)
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        free = shutil.disk_usage(probe).free
        gib = 1024 ** 3
        if free < 1 * gib:
            return free, f"Hedefte yalnızca {format_size(free)} boş alan var. Sürücü yedekleri çoğu bilgisayarda 1-5 GB tutar."
        if free < 3 * gib:
            return free, f"Hedefte {format_size(free)} boş alan var. Ekran kartı sürücüleri çoksa bu yetmeyebilir."
        return free, None

    @staticmethod
    def restore_batch_text() -> str:
        """Yedek klasörüne konan, yeni kurulumdan sonra çift tıklanan geri yükleme dosyası."""
        return (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "title Surucu geri yukleme\r\n"
            "net session >nul 2>&1\r\n"
            "if %errorlevel% neq 0 (\r\n"
            "  echo Yonetici izni isteniyor...\r\n"
            "  powershell -NoProfile -Command \"Start-Process -FilePath '%~f0' -Verb RunAs\"\r\n"
            "  exit /b\r\n"
            ")\r\n"
            "echo Suruculer yedek klasorunden yukleniyor. Bu islem birkac dakika surebilir...\r\n"
            "pnputil /add-driver \"%~dp0Drivers\\*.inf\" /subdirs /install\r\n"
            "echo.\r\n"
            "echo Bitti. Gerekirse bilgisayari yeniden baslatin.\r\n"
            "pause\r\n"
        )

    @classmethod
    def write_manifest(cls, folder: Path, drivers: list[DriverInfo], result: BackupResult) -> None:
        """Yedeğin yanına okunabilir bir özet ve geri yükleme dosyası yazar (hata sessiz)."""
        try:
            manifest = {
                "app": "Windows Update & Build Center",
                "created": datetime.now().isoformat(timespec="seconds"),
                "computer": socket.gethostname(),
                "driver_count": result.ok,
                "drivers": [
                    {
                        "inf": d.inf_name,
                        "device": d.display_name,
                        "provider": d.provider,
                        "class": d.class_name,
                        "version": d.version,
                        "date": d.date,
                    }
                    for d in drivers
                ],
                "failed": result.failed,
                "note": "Yalnızca üçüncü taraf (OEM) sürücüler yedeklenir; Windows'un kendi sürücüleri dahil değildir.",
            }
            (folder / "yedek_bilgisi.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (folder / "Suruculeri_Geri_Yukle.bat").write_text(cls.restore_batch_text(), encoding="utf-8")
            (folder / "OKU.txt").write_text(
                "Bu klasor 'Windows Update & Build Center' ile alinan surucu yedegidir.\r\n"
                "Yeni kurulumdan sonra 'Suruculeri_Geri_Yukle.bat' dosyasina cift tiklayin.\r\n"
                "Yalnizca ayni bilgisayar icin onerilir; farkli donanimda sorun cikarabilir.\r\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ yedekleme
    @staticmethod
    def build_backup_script(infs: list[str], dest: Path, list_file: Path, progress: Path, cancel: Path) -> str:
        """Yükseltilmiş PowerShell betiği: her paketi pnputil ile dışa aktarır."""
        return (
            "$ErrorActionPreference = 'Continue'\r\n"
            f"$dest = {_ps_quote(str(dest))}\r\n"
            f"$list = Get-Content -LiteralPath {_ps_quote(str(list_file))} -Encoding UTF8\r\n"
            f"$prog = {_ps_quote(str(progress))}\r\n"
            f"$cancel = {_ps_quote(str(cancel))}\r\n"
            "$total = @($list).Count\r\n"
            "$i = 0\r\n"
            "foreach ($inf in $list) {\r\n"
            "  if (Test-Path -LiteralPath $cancel) { Add-Content -LiteralPath $prog -Value 'CANCELLED'; break }\r\n"
            "  $i++\r\n"
            "  $null = & pnputil.exe /export-driver $inf $dest 2>&1\r\n"
            "  if ($LASTEXITCODE -eq 0) { Add-Content -LiteralPath $prog -Value (\"OK|$i|$total|$inf\") }\r\n"
            "  else { Add-Content -LiteralPath $prog -Value (\"FAIL|$i|$total|$inf\") }\r\n"
            "}\r\n"
            "Add-Content -LiteralPath $prog -Value 'END'\r\n"
            "exit 0\r\n"
        )

    @staticmethod
    def parse_progress_line(line: str) -> tuple[str, int, int, str] | None:
        parts = (line or "").strip().split("|")
        if len(parts) == 4 and parts[0] in ("OK", "FAIL"):
            try:
                return parts[0], int(parts[1]), int(parts[2]), parts[3]
            except ValueError:
                return None
        return None

    @classmethod
    def _run_elevated_powershell(
        cls,
        script_text: str,
        *,
        timeout: int,
        poll: Callable[[], None] | None = None,
        workdir: Path,
        name: str,
    ) -> None:
        """Betiği .ps1 olarak kaydeder, UAC ile çalıştırır; bitene dek poll() çağırır."""
        script_path = workdir / f"{name}.ps1"
        # PowerShell 5.1 BOM'suz UTF-8'i ANSI sanır; Türkçe yollar için BOM şart.
        script_path.write_text(script_text, encoding="utf-8-sig")
        error: list[BaseException] = []

        def target() -> None:
            try:
                UsbMediaService._run_privileged(
                    [
                        "powershell.exe", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-File", str(script_path),
                    ],
                    timeout=timeout,
                )
            except BaseException as exc:  # noqa: BLE001 - üst iş parçacığına aktarılır
                error.append(exc)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        while thread.is_alive():
            if poll:
                try:
                    poll()
                except Exception:
                    pass
            thread.join(0.4)
        if poll:
            try:
                poll()
            except Exception:
                pass
        if error:
            raise error[0]

    @classmethod
    def backup(
        cls,
        drivers: list[DriverInfo],
        dest_parent: Path,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> BackupResult:
        if not cls.is_supported_platform():
            raise RuntimeError("Sürücü yedekleme yalnızca Windows üzerinde çalışır.")
        if not drivers:
            raise RuntimeError("Yedeklenecek sürücü seçilmedi.")
        folder = cls.new_backup_folder(Path(dest_parent))
        drivers_dir = folder / "Drivers"
        drivers_dir.mkdir(parents=True, exist_ok=True)

        work = Path(tempfile.mkdtemp(prefix="wubc_drv_"))
        list_file = work / "list.txt"
        progress = work / "progress.txt"
        cancel_flag = work / "cancel.flag"
        list_file.write_text("\n".join(d.inf_name for d in drivers), encoding="utf-8")
        progress.write_text("", encoding="utf-8")
        total = len(drivers)
        result = BackupResult(folder=folder, total=total, ok=0)
        seen = {"lines": 0}
        ok_infs: set[str] = set()

        def poll() -> None:
            if cancelled and cancelled() and not cancel_flag.exists():
                cancel_flag.write_text("1", encoding="ascii")
            try:
                lines = progress.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                return
            for line in lines[seen["lines"]:]:
                if line.strip() == "CANCELLED":
                    result.cancelled = True
                    continue
                parsed = cls.parse_progress_line(line)
                if not parsed:
                    continue
                state, index, count, inf = parsed
                if state == "OK":
                    result.ok += 1
                    ok_infs.add(inf.lower())
                else:
                    result.failed.append(inf)
                if on_progress:
                    on_progress(index, count, inf)
            seen["lines"] = len(lines)

        try:
            script = cls.build_backup_script(
                [d.inf_name for d in drivers], drivers_dir, list_file, progress, cancel_flag
            )
            cls._run_elevated_powershell(
                script, timeout=3600, poll=poll, workdir=work, name="export"
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

        result.size_bytes = folder_size(drivers_dir)
        result.inf_count = count_inf_files(drivers_dir)
        cls.write_manifest(folder, [d for d in drivers if d.inf_name.lower() in ok_infs], result)
        return result

    # ----------------------------------------------------------------- geri yükleme
    @staticmethod
    def build_restore_script(source: Path, log: Path, rc_file: Path, restore_point: bool) -> str:
        """Yükseltilmiş PowerShell betiği: her .inf paketini tek tek yükler.

        Ne olursa olsun (hata, beklenmedik durum) sonuç dosyası yazılır; ayrıntılar günlüğe düşer.
        Sonuç kodu: 0 başarılı, 3010 yeniden başlatma gerekli, 259 yeni sürücü yok,
        4000+N N sürücü yüklenemedi (diğerleri yüklendi), 2 INF bulunamadı, 1 hiçbiri yüklenemedi.
        """
        lines = [
            "$ErrorActionPreference = 'Continue'",
            f"$src = {_ps_quote(str(source))}",
            f"$log = {_ps_quote(str(log))}",
            f"$rcf = {_ps_quote(str(rc_file))}",
            "$rc = 1",
            "function Log($t) { try { Add-Content -LiteralPath $log -Value $t -Encoding UTF8 } catch {} }",
            "try {",
        ]
        if restore_point:
            lines += [
                "  try {",
                "    Enable-ComputerRestore -Drive \"$env:SystemDrive\\\" -ErrorAction Stop",
                "    Checkpoint-Computer -Description 'Surucu geri yukleme oncesi' -RestorePointType MODIFY_SETTINGS -ErrorAction Stop",
                "    Log 'GERI YUKLEME NOKTASI: olusturuldu'",
                "  } catch {",
                "    Log ('GERI YUKLEME NOKTASI: olusturulamadi - ' + $_.Exception.Message)",
                "  }",
            ]
        lines += [
            "  $infs = @(Get-ChildItem -LiteralPath $src -Filter '*.inf' -File -Recurse -ErrorAction SilentlyContinue)",
            "  Log ('Bulunan INF sayisi: ' + $infs.Count)",
            "  $ok = 0; $fail = 0; $none = 0; $reboot = $false",
            "  foreach ($f in $infs) {",
            "    $o = (& pnputil.exe /add-driver $f.FullName /install 2>&1 | Out-String)",
            "    $c = $LASTEXITCODE",
            "    Log ('[' + $c + '] ' + $f.FullName)",
            "    Log $o",
            "    if ($c -eq 0) { $ok++ }",
            "    elseif ($c -eq 3010) { $ok++; $reboot = $true }",
            "    elseif ($c -eq 259) { $none++ }",
            "    else { $fail++ }",
            "  }",
            "  Log ('Ozet: yuklenen=' + $ok + ' zaten-yuklu=' + $none + ' hata=' + $fail)",
            "  if ($infs.Count -eq 0) { $rc = 2 }",
            "  elseif ($fail -gt 0 -and ($ok + $none) -eq 0) { $rc = 1 }",
            "  elseif ($fail -gt 0) { $rc = 4000 + $fail }",
            "  elseif ($reboot) { $rc = 3010 }",
            "  elseif ($ok -eq 0 -and $none -gt 0) { $rc = 259 }",
            "  else { $rc = 0 }",
            "} catch {",
            "  Log ('BETIK HATASI: ' + $_.Exception.Message)",
            "  $rc = 1",
            "} finally {",
            "  Log ('RC=' + $rc)",
            "  try { [System.IO.File]::WriteAllText($rcf, [string]$rc, [System.Text.Encoding]::ASCII) } catch {}",
            "}",
            "exit 0",
        ]
        return "\r\n".join(lines) + "\r\n"

    @staticmethod
    def interpret_restore_code(code: int) -> tuple[bool, bool, str]:
        """(başarılı mı, yeniden başlatma gerekli mi, açıklama)"""
        if code == 0:
            return True, False, "Sürücüler yüklendi."
        if code == 3010:
            return True, True, "Sürücüler yüklendi. Değişikliklerin geçerli olması için bilgisayarı yeniden başlatın."
        if code == 259:
            return True, False, "Yüklenecek yeni sürücü bulunamadı (hepsi zaten yüklü olabilir)."
        if code == 2:
            return False, False, "Yedek klasöründe .inf sürücü dosyası bulunamadı."
        if code >= 4000:
            return True, True, (
                f"Sürücülerin çoğu yüklendi; {code - 4000} sürücü yüklenemedi (ayrıntı için günlüğe bakın). "
                "Değişikliklerin geçerli olması için bilgisayarı yeniden başlatın."
            )
        if code == 1:
            return False, False, "Hiçbir sürücü yüklenemedi. Ayrıntı için günlüğe bakın."
        return False, False, f"pnputil işlemi hata koduyla bitti: {code}."

    @staticmethod
    def parse_restore_log_code(detail: str) -> int | None:
        """Günlükteki son 'RC=<kod>' satırından sonuç kodunu okur (sonuç dosyası okunamazsa yedek yol)."""
        found = re.findall(r"^\s*RC=(-?\d+)\s*$", detail or "", flags=re.MULTILINE)
        return int(found[-1]) if found else None

    @staticmethod
    def _keep_restore_log(log: Path) -> str:
        """Geçici klasör silinmeden önce günlüğü kalıcı bir konuma kopyalar (sorun giderme için)."""
        try:
            target = Path(tempfile.gettempdir()) / "wubc_surucu_geri_yukleme.log"
            shutil.copyfile(log, target)
            return str(target)
        except OSError:
            return ""

    @classmethod
    def restore(
        cls,
        source: Path,
        *,
        restore_point: bool = True,
    ) -> tuple[bool, bool, str, str]:
        """Yedekten toplu geri yükleme. (başarılı, yeniden başlatma, özet, ayrıntı günlüğü)"""
        if not cls.is_supported_platform():
            raise RuntimeError("Sürücü geri yükleme yalnızca Windows üzerinde çalışır.")
        source = Path(source)
        drivers_dir = source / "Drivers" if (source / "Drivers").is_dir() else source
        if count_inf_files(drivers_dir) == 0:
            raise RuntimeError("Seçilen klasörde .inf sürücü dosyası bulunamadı.")

        work = Path(tempfile.mkdtemp(prefix="wubc_drv_"))
        log = work / "restore.log"
        rc_file = work / "rc.txt"
        log.write_text("", encoding="utf-8")
        try:
            script = cls.build_restore_script(drivers_dir, log, rc_file, restore_point)
            cls._run_elevated_powershell(
                script, timeout=3600, workdir=work, name="restore"
            )
            detail = UsbMediaService._decode_command_log(log)
            code: int | None
            try:
                code = int(rc_file.read_text(encoding="utf-8-sig", errors="replace").strip())
            except (OSError, ValueError):
                code = cls.parse_restore_log_code(detail)
            if code is None:
                kept = cls._keep_restore_log(log)
                message = "Geri yükleme sonucu okunamadı. İşlem iptal edilmiş olabilir."
                if detail.strip():
                    message += f"\n\nAyrıntı:\n{detail.strip()[-1500:]}"
                if kept:
                    message += f"\n\nGünlük dosyası: {kept}"
                raise RuntimeError(message)
            ok, reboot, summary = cls.interpret_restore_code(code)
            cls._keep_restore_log(log)
            return ok, reboot, summary, detail
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ------------------------------------------------------------------ USB hedefleri
    @staticmethod
    def usb_targets() -> list[tuple[str, Path]]:
        """Harf atanmış USB bellekler: (görünen ad, kök yol)."""
        targets: list[tuple[str, Path]] = []
        for drive in UsbMediaService.list_usb_drives():
            letter = (drive.drive_letter or "").strip().rstrip(":")
            if letter:
                targets.append((f"{letter}: – {drive.display_name}", Path(f"{letter}:\\")))
        return targets
