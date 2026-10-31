from datetime import datetime

import services.build_history_service as history_module
from services.build_history_service import BuildHistoryService
from services.build_tracker_service import BuildTrackerRecord


def test_records_success_and_failure(tmp_path):
    history_module.BUILD_HISTORY_PATH = tmp_path / "history.json"
    record = BuildTrackerRecord(
        build_number="26300.9278", kb_number="KB5120998",
        windows_version="26H2", channel="Release Preview",
    )
    BuildHistoryService.record_success([record], [record], "30.08.2026 14:30")
    BuildHistoryService.record_failure("Bağlantı kurulamadı")
    entries = BuildHistoryService.load()
    assert len(entries) == 2
    assert entries[0]["status"] == "failed"
    assert entries[1]["new_count"] == 1
    assert entries[1]["new_records"][0]["build"] == "26300.9278"


def test_period_summary(tmp_path):
    history_module.BUILD_HISTORY_PATH = tmp_path / "history.json"
    BuildHistoryService._save([
        {"checked_at": "2026-08-30T10:00:00", "status": "success", "new_count": 2},
        {"checked_at": "2026-08-29T10:00:00", "status": "failed", "new_count": 0},
        {"checked_at": "2026-08-01T10:00:00", "status": "success", "new_count": 3},
        {"checked_at": "2026-07-31T10:00:00", "status": "success", "new_count": 9},
    ])
    summary = BuildHistoryService.summary(datetime(2026, 8, 30, 15, 0, 0))
    assert summary["today"] == {"checks": 1, "new": 2, "failed": 0}
    assert summary["week"] == {"checks": 2, "new": 2, "failed": 1}
    assert summary["month"] == {"checks": 3, "new": 5, "failed": 1}


def test_history_limit(tmp_path):
    history_module.BUILD_HISTORY_PATH = tmp_path / "history.json"
    entries = [
        {"checked_at": f"2026-08-30T10:{index % 60:02d}:00", "status": "success", "new_count": 0}
        for index in range(520)
    ]
    BuildHistoryService._save(entries)
    assert len(BuildHistoryService.load()) == 500


def test_release_groups_use_publish_dates():
    records = [
        BuildTrackerRecord(build_number="1", release_date="2026-08-30"),
        BuildTrackerRecord(build_number="2", release_date="2026-08-27"),
        BuildTrackerRecord(build_number="3", release_date="2026-08-21"),
        BuildTrackerRecord(build_number="4", release_date="2026-07-31"),
    ]
    groups = BuildHistoryService.release_groups(records, datetime(2026, 8, 30, 15, 30))
    assert [record.build_number for record in groups["today"]] == ["1"]
    assert [record.build_number for record in groups["week"]] == ["1", "2"]
    assert [record.build_number for record in groups["month"]] == ["1", "2", "3"]
