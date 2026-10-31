from datetime import datetime

from app.version import APP_VERSION
from services.app_update_service import AppUpdateService
from services.build_tracker_service import BuildTrackerRecord as R
from services.local_build_service import LocalBuild, LocalBuildService


def test_version_compare():
    assert AppUpdateService.is_newer("v6.06", "v6.05")
    assert AppUpdateService.is_newer("v6.10", "v6.9")
    assert not AppUpdateService.is_newer("v6.05", "v6.05")
    assert not AppUpdateService.is_newer("v6.4", "v6.05")
    assert not AppUpdateService.is_newer("", APP_VERSION)


def _records():
    return [
        R("26200.4602", "KB1", "25H2", "GA / Retail", release_date="2026-10-14"),
        R("26200.4700", "KB2", "25H2", "GA / Retail", release_date="2026-10-20"),
        R("28000.1000", "", "26H1", "Canary", release_date="2026-09-30"),
    ]


def test_local_build_compare():
    behind = LocalBuildService.compare(_records(), LocalBuild("Windows 11", "25H2", "26200", 4602))
    assert behind["status"] == "behind" and behind["behind"] == 1
    assert behind["latest"].build_number == "26200.4700"
    assert LocalBuildService.compare(_records(), LocalBuild("W", "", "26200", 4700))["status"] == "latest"
    assert LocalBuildService.compare(_records(), LocalBuild("W", "", "99999", 1))["status"] == "unknown"
    assert LocalBuildService.compare(_records(), None)["status"] == "unknown"


def test_download_schedule_window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from services.download_manager import DownloadManager
    dm = DownloadManager.instance()
    dm.apply_settings({"schedule_enabled": True, "schedule_start": "23:00", "schedule_end": "06:00"})
    assert dm.schedule_open(datetime(2026, 1, 1, 23, 30)) and dm.schedule_open(datetime(2026, 1, 1, 3, 0))
    assert not dm.schedule_open(datetime(2026, 1, 1, 12, 0))
    dm.apply_settings({"schedule_enabled": False})
    assert dm.schedule_open(datetime(2026, 1, 1, 12, 0))


def test_theme_color_mapping():
    from ui import theme
    theme._dark = True
    try:
        assert theme.bg_hex("#FFFFFF") != "#FFFFFF"           # beyaz zemin koyulaşır
        assert theme.fg_hex("#14213D") != "#14213D"           # koyu metin açılır
        assert theme.bg_hex("#2167D5") == "#2167D5"           # doygun vurgu aynen kalır
        out = theme.transform_qss("QPushButton { background:#2167D5; color:#14213D; }")
        assert "color:#14213D" in out                          # vurgu zemin üstündeki metin korunur
        side = theme.transform_qss("QFrame#sidebar { background:#0A1A31; }")
        assert "#0A1A31" in side                               # yan menü dönüştürülmez
    finally:
        theme._dark = False
