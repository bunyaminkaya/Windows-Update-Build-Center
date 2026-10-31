from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.paths import SETTINGS_PATH

logger = logging.getLogger(__name__)


DEFAULT_SETTINGS: dict[str, Any] = {
    "appearance": {"theme": "light"},
    "iso_center": {"scan_folders": []},
    "general": {
        "open_last_page": True,
        "last_page": "Güncelleme Merkezi",
        "check_tracker_on_start": True,
        "run_in_background": False,
        "minimize_to_tray": False,
        "start_with_windows": False,
        "check_app_updates": True,
        "show_welcome_on_start": False,
        "language": "auto",
    },
    "downloads": {
        "default_folder": "",
        "max_concurrent": 3,
        "open_folder_on_complete": False,
        "resume_incomplete": True,
        "duplicate_policy": "Benzersiz ad oluştur",
        "speed_limit_kbps": 0,
        "schedule_enabled": False,
        "schedule_start": "01:00",
        "schedule_end": "07:00",
    },
    "uup_iso": {
        "default_architecture": "Sistem varsayılanı",
        "default_language": "Sistem varsayılanı",
        "default_edition": "Windows 11 Pro",
        "work_folder": "",
        "output_folder": "",
        "open_iso_folder_on_complete": False,
        "clean_temp_files": False,
        "auto_create_iso": True,   # UUP indirmesi bitince ISO'yu kendiliğinden oluştur
    },
    "usb_media": {
        "partition_scheme": "GPT",
        "file_system": "Otomatik",
        "bypass_hardware_checks": False,
    },
    "build_tracker": {
        "source_url": "https://bunyaminkaya.com/windows-build-tracker/",
        "refresh_on_start": True,
        "refresh_interval_minutes": 60,
        "notifications_enabled": True,
        "watchlist_enabled": False,
        "tracked_versions": [],
        "tracked_terms": [],
        "notification_channels": [
            "GA / Retail", "Release Preview", "Beta",
            "Experimental", "Dev", "Canary",
        ],
    },
    "advanced": {
        "confirm_destructive_actions": True,
    },
    "onboarding": {
        "welcome_shown": False,
    },
}


class SettingsService:
    @classmethod
    def load(cls) -> dict[str, Any]:
        data = deepcopy(DEFAULT_SETTINGS)
        try:
            if SETTINGS_PATH.exists():
                raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    cls._deep_merge(data, raw)
        except Exception as exc:
            logger.exception("Ayarlar dosyası okunamadı: %s", exc)
            backup = SETTINGS_PATH.with_suffix(".json.bak")
            try:
                if backup.exists():
                    raw = json.loads(backup.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        cls._deep_merge(data, raw)
                        logger.warning("Ayarlar yedek dosyadan kurtarıldı: %s", backup)
            except Exception as backup_exc:
                logger.exception("Ayar yedeği de okunamadı: %s", backup_exc)
        return data

    @classmethod
    def save(cls, data: dict[str, Any]) -> None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(data, ensure_ascii=False, indent=2)
        temp_path = SETTINGS_PATH.with_suffix(".json.tmp")
        backup_path = SETTINGS_PATH.with_suffix(".json.bak")
        try:
            temp_path.write_text(encoded, encoding="utf-8")
            # Keep last known-good settings before atomically replacing the file.
            if SETTINGS_PATH.exists():
                try:
                    backup_path.write_bytes(SETTINGS_PATH.read_bytes())
                except Exception as backup_exc:
                    logger.warning("Ayar yedeği oluşturulamadı: %s", backup_exc)
            temp_path.replace(SETTINGS_PATH)
        except Exception:
            logger.exception("Ayarlar atomik olarak kaydedilemedi")
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                logger.exception("Geçici ayar dosyası temizlenemedi")
            raise

    @classmethod
    def reset(cls) -> dict[str, Any]:
        data = deepcopy(DEFAULT_SETTINGS)
        cls.save(data)
        return data

    @classmethod
    def update_value(cls, section: str, key: str, value: Any) -> dict[str, Any]:
        data = cls.load()
        data.setdefault(section, {})[key] = value
        cls.save(data)
        return data

    @classmethod
    def _deep_merge(cls, target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                cls._deep_merge(target[key], value)
            else:
                target[key] = value


def auto_create_iso_enabled() -> bool:
    """İndirme bitince ISO'nun otomatik oluşturulup oluşturulmayacağı (varsayılan: açık)."""
    try:
        return bool(SettingsService.load().get("uup_iso", {}).get("auto_create_iso", True))
    except Exception:
        return True
