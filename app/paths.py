from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "assets" / "icons"

APP_DATA_ROOT = Path(
    os.environ.get("LOCALAPPDATA")
    or (Path.home() / "AppData" / "Local")
) / "Windows Update & Build Center"
DATA_DIR = APP_DATA_ROOT / "data"
LOG_DIR = APP_DATA_ROOT / "logs"
DB_PATH = DATA_DIR / "app.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_PATH = LOG_DIR / "app.log"
DOWNLOAD_STATE_PATH = DATA_DIR / "download_state.json"
ISO_TASKS_PATH = DATA_DIR / "iso_tasks.json"
BUILD_HISTORY_PATH = DATA_DIR / "build_tracker_history.json"

LEGACY_PROJECT_DATA_DIR = ROOT / "data"
LEGACY_PROJECT_LOG_DIR = ROOT / "logs"
LEGACY_LOCAL_DIR = Path.home() / "AppData" / "Local" / "MicrosoftDirektLinkBulucu"


def _copy_if_missing(source: Path, target: Path) -> None:
    try:
        if source.exists() and source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    except Exception:
        # Migration failure must never stop application startup.
        pass


def migrate_legacy_user_data() -> None:
    """One-time, non-destructive migration from old project-local storage."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    for name in (
        "settings.json",
        "app.db",
        "build_tracker_cache.json",
        "windows_build_tracker_cache.json",
        "official_build_cache.json",
        "build_tracker_history.json",
    ):
        _copy_if_missing(LEGACY_PROJECT_DATA_DIR / name, DATA_DIR / name)

    _copy_if_missing(LEGACY_PROJECT_LOG_DIR / "app.log", LOG_PATH)
    _copy_if_missing(LEGACY_LOCAL_DIR / "download_state.json", DOWNLOAD_STATE_PATH)
    _copy_if_missing(LEGACY_LOCAL_DIR / "iso_tasks.json", ISO_TASKS_PATH)


for folder in (DATA_DIR, LOG_DIR):
    folder.mkdir(parents=True, exist_ok=True)

migrate_legacy_user_data()
