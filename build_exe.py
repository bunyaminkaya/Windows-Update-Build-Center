from __future__ import annotations

import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
LOG_PATH = PROJECT_DIR / "EXE_Build.log"


def log(message: str = "") -> None:
    print(message, flush=True)
    with LOG_PATH.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(message + "\n")


def run(command: list[str], title: str, cwd: Path = PROJECT_DIR) -> None:
    log(f"\n[{title}]")
    log("Komut: " + subprocess.list2cmdline(command))
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip("\r\n")
        print(line, flush=True)
        with LOG_PATH.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(line + "\n")
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"{title} başarısız oldu. Çıkış kodu: {code}")


def read_version() -> str:
    namespace: dict[str, object] = {}
    version_file = PROJECT_DIR / "app" / "version.py"
    exec(compile(version_file.read_text(encoding="utf-8-sig"), str(version_file), "exec"), namespace)
    version = str(namespace.get("APP_VERSION", "")).strip()
    if not version:
        raise RuntimeError("app/version.py içinden APP_VERSION okunamadı.")
    return version


def ensure_build_dependencies() -> None:
    required = ["PyInstaller", "PySide6", "requests", "bs4"]
    missing: list[str] = []
    import importlib.util
    for module in required:
        if importlib.util.find_spec(module) is None:
            missing.append(module)
    if missing:
        log("Eksik derleme bağımlılıkları kuruluyor...")
        run(
            [sys.executable, "-m", "pip", "install", "-r", str(PROJECT_DIR / "requirements.txt"), "pyinstaller>=6,<7"],
            "Derleme bağımlılıkları kuruluyor",
        )
    # PyInstaller modülünü ayrıca doğrula.
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError("PyInstaller kurulamadı.")


def main() -> int:
    LOG_PATH.write_text(
        "Windows Update & Build Center - EXE Build Log\n"
        f"Tarih: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"Python: {sys.executable}\n"
        f"Python sürümü: {sys.version}\n"
        f"Proje: {PROJECT_DIR}\n",
        encoding="utf-8",
    )

    try:
        os.chdir(PROJECT_DIR)
        version = read_version()
        # PyInstaller çalışma adında nokta kullanmıyoruz. Bu, bazı sistemlerde
        # build alt klasörünün oluşturulmasıyla ilgili sorunları engeller.
        safe_version = version.replace(".", "_")
        exe_name = f"Windows_Update_and_Build_Center_{safe_version}"
        icon_path = PROJECT_DIR / "assets" / "icons" / "app_logo.ico"
        main_path = PROJECT_DIR / "main.py"
        work_root = PROJECT_DIR / "build"
        work_dir = work_root / exe_name
        dist_root = PROJECT_DIR / "dist"
        spec_root = PROJECT_DIR / ".pyinstaller_spec"

        log("=" * 68)
        log("Windows Update & Build Center - EXE Oluşturma")
        log("=" * 68)
        log(f"Sürüm: {version}")
        log(f"Çıktı adı: {exe_name}.exe")

        if not main_path.is_file():
            raise FileNotFoundError(f"main.py bulunamadı: {main_path}")
        if not icon_path.is_file():
            raise FileNotFoundError(f"Uygulama simgesi bulunamadı: {icon_path}")

        ensure_build_dependencies()

        for path in (work_root, dist_root, spec_root):
            if path.exists():
                log(f"Eski klasör temizleniyor: {path.name}")
                shutil.rmtree(path, ignore_errors=False)

        # PyInstaller'ın base_library.zip yazdığı alt çalışma klasörünü önceden
        # oluşturuyoruz. v5.77'de bu klasör yoksa FileNotFoundError oluşabiliyordu.
        work_dir.mkdir(parents=True, exist_ok=True)
        dist_root.mkdir(parents=True, exist_ok=True)
        spec_root.mkdir(parents=True, exist_ok=True)

        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir",
            "--name", exe_name,
            "--icon", str(icon_path),
            "--workpath", str(work_root),
            "--distpath", str(dist_root),
            "--specpath", str(spec_root),
            "--paths", str(PROJECT_DIR),
            "--add-data", f"{PROJECT_DIR / 'assets'}{os.pathsep}assets",
            # Projede kullanılmayan büyük bilimsel/ML paketlerinin global Python
            # ortamından yanlışlıkla toplanmasını engeller.
            "--exclude-module", "torch",
            "--exclude-module", "torchvision",
            "--exclude-module", "torchaudio",
            "--exclude-module", "tensorflow",
            "--exclude-module", "sklearn",
            "--exclude-module", "scipy",
            "--exclude-module", "matplotlib",
            "--exclude-module", "pandas",
            "--exclude-module", "cv2",
            "--exclude-module", "nltk",
            str(main_path),
        ]
        run(command, "PyInstaller paketleme")

        suffix = ".exe" if os.name == "nt" else ""
        output_dir = dist_root / exe_name
        output_file = output_dir / f"{exe_name}{suffix}"
        if not output_file.is_file():
            found = "\n".join(str(item) for item in dist_root.rglob("*")) if dist_root.exists() else "(dist klasörü yok)"
            raise FileNotFoundError(
                f"PyInstaller tamamlandı ancak beklenen çıktı bulunamadı: {output_file}\n"
                f"Dist içeriği:\n{found[:8000]}"
            )

        log("\n" + "=" * 68)
        log("BAŞARILI: Uygulama paketi oluşturuldu.")
        log(f"Konum: {output_file}")
        log("=" * 68)

        if os.name == "nt":
            try:
                subprocess.Popen(["explorer.exe", "/select,", str(output_file)])
            except Exception as exc:
                log(f"Dosya Gezgini açılamadı: {exc}")
        return 0
    except Exception as exc:
        log("\n" + "=" * 68)
        log("HATA: EXE oluşturma tamamlanamadı.")
        log(str(exc))
        log(traceback.format_exc())
        log(f"Ayrıntılı log: {LOG_PATH}")
        log("=" * 68)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
