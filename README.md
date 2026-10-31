<p align="center">
  <img src="assets/icons/brand_banner.png" alt="Windows Update & Build Center" width="760">
</p>

# Windows Update & Build Center

Windows Update & Build Center is a Windows desktop application for discovering Windows builds, searching official Microsoft update packages, downloading UUP/KB content, managing downloads, creating ISO media and preparing bootable USB installation drives from a single interface.

**Current version:** v6.06  
**Developer:** Bünyamin KAYA  
**Website:** bunyaminkaya.com  
**Contact:** bunyaminkaya@gmail.com

## Main features

- **UUP Center v6** — Latest build list, version/channel/architecture filters, multi-language and edition selection, resumable UUP downloads, automatic ISO creation and ISO SHA-256 validation.
- **Startup reliability** — A failed optional page no longer prevents the main window from opening; startup errors are logged and surfaced to the user.

- **Microsoft Update Center** — Search Microsoft Update Catalog by KB or Windows build number and access official packages.
- **Windows Build Tracker** — Follow current Windows build and KB records using the tracker data published on bunyaminkaya.com.
- **UUP Center** — Find UUP packages and create Windows ISO media.
- **Download Manager** — Queue, pause, resume, retry and monitor multiple downloads.
- **USB Installation Center** — Prepare bootable Windows installation media with GPT/MBR and FAT32/NTFS options.
- **Languages** — Turkish and English (Settings > General > Language; automatic by default, follows the Windows display language).
- **Driver Backup** — Back up third-party (OEM) drivers with `pnputil`, copy them onto the installation USB and restore them after a clean install.
- **Windows 11 compatibility options** — Optional TPM 2.0, Secure Boot and minimum RAM requirement bypass when preparing installation media.
- **Integrated feedback** — Send bug reports, suggestions and recommendations from the application.
- **System & Update Center (6–12)** — Hardware/update compatibility, installed KB inventory, Build Tracker gap checks, KB/package detail and automatic package scoring.
- **Download security gate** — Microsoft HTTPS/source validation before download and automatic SHA-256 + signature verification after download.
- **Safe installation** — Verified-package-only installation, restore-point option, admin check, MSU/CAB/EXE handling, reboot detection and Turkish error explanations.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer for running from source
- Internet connection for Microsoft/UUP/Build Tracker operations
- Administrator privileges for operations that require disk formatting or ISO conversion

## Run from source

```bat
python -m pip install -r requirements.txt
python main.py
```

You can also double-click `calistir.bat`.

## Build the Windows application

Double-click:

```text
EXE_Olustur.bat
```

The script installs the required build tools and creates the application under the `dist` folder using the current version from `app/version.py`.

## GitHub update workflow

For the first upload and later updates, run:

```text
GitHub_Guncelle.bat
```

The script automatically initializes Git when needed, connects the project to:

```text
https://github.com/bunyaminkaya/Windows-Update-Build-Center.git
```

and then stages, commits and pushes the current project files.

On the first push, Git/GitHub may ask you to sign in through the browser or Git Credential Manager.

## Safety notes

Operations that write bootable media can erase the selected USB drive. Always verify the target drive before confirming a destructive operation.

The project uses official Microsoft sources where applicable, but it is an independent third-party application and is not affiliated with or endorsed by Microsoft.

## Data source

Windows Build Tracker data:

```text
https://bunyaminkaya.com/windows-build-tracker/
```

## License

Copyright © 2026 Bünyamin KAYA. All rights reserved. See `LICENSE` for details.
