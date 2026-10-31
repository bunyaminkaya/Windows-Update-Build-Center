from services.build_tracker_service import BuildTrackerRecord
from services.build_watch_service import BuildWatchService


def _record(**overrides):
    values = {
        "build_number": "26300.9278",
        "kb_number": "KB5120998",
        "windows_version": "26H2",
        "channel": "Release Preview",
    }
    values.update(overrides)
    return BuildTrackerRecord(**values)


def test_disabled_watchlist_accepts_every_record():
    assert BuildWatchService.matches(_record(), {"watchlist_enabled": False})


def test_matches_tracked_version():
    settings = {"watchlist_enabled": True, "tracked_versions": ["26H2"]}
    assert BuildWatchService.matches(_record(), settings)


def test_matches_tracked_channel():
    settings = {"watchlist_enabled": True, "notification_channels": ["Beta"]}
    assert BuildWatchService.matches(_record(channel="Beta"), settings)


def test_matches_exact_kb():
    settings = {"watchlist_enabled": True, "tracked_terms": ["kb5120998"]}
    assert BuildWatchService.matches(_record(), settings)


def test_matches_build_family():
    settings = {"watchlist_enabled": True, "tracked_terms": ["26300"]}
    assert BuildWatchService.matches(_record(), settings)


def test_rejects_untracked_record():
    settings = {
        "watchlist_enabled": True,
        "tracked_versions": ["26H1"],
        "notification_channels": ["Canary"],
        "tracked_terms": ["28120"],
    }
    assert not BuildWatchService.matches(_record(), settings)


def test_empty_enabled_watchlist_rejects_records():
    assert not BuildWatchService.matches(_record(), {"watchlist_enabled": True})
