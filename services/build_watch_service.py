from __future__ import annotations

import re

from services.build_tracker_service import BuildTrackerRecord


class BuildWatchService:
    """Build Tracker kayıtlarını kullanıcının takip ölçütleriyle eşleştirir."""

    @staticmethod
    def normalize_terms(value) -> list[str]:
        if isinstance(value, str):
            raw_items = re.split(r"[,;\n]+", value)
        elif isinstance(value, (list, tuple, set)):
            raw_items = list(value)
        else:
            raw_items = []
        result: list[str] = []
        for item in raw_items:
            term = " ".join(str(item).strip().upper().split())
            if term and term not in result:
                result.append(term)
        return result

    @classmethod
    def matches(cls, record: BuildTrackerRecord, tracker_settings: dict) -> bool:
        if not tracker_settings.get("watchlist_enabled", False):
            return True

        versions = {str(value).strip().upper() for value in tracker_settings.get("tracked_versions", []) if str(value).strip()}
        channels = {str(value).strip().casefold() for value in tracker_settings.get("notification_channels", []) if str(value).strip()}
        terms = cls.normalize_terms(tracker_settings.get("tracked_terms", []))

        version_match = bool(versions and (record.windows_version or "").strip().upper() in versions)
        channel_match = bool(channels and (record.channel or "").strip().casefold() in channels)

        kb = (record.kb_number or "").strip().upper()
        build = (record.build_number or "").strip().upper()
        term_match = any(
            (term.startswith("KB") and kb == term)
            or (not term.startswith("KB") and (build == term or build.startswith(term + ".")))
            for term in terms
        )
        return version_match or channel_match or term_match

    @classmethod
    def summary(cls, tracker_settings: dict) -> str:
        if not tracker_settings.get("watchlist_enabled", False):
            return "Tüm yeni Build Tracker kayıtları takip ediliyor."
        parts: list[str] = []
        versions = tracker_settings.get("tracked_versions", [])
        channels = tracker_settings.get("notification_channels", [])
        terms = cls.normalize_terms(tracker_settings.get("tracked_terms", []))
        if versions:
            parts.append("Sürümler: " + ", ".join(versions))
        if channels:
            parts.append("Kanallar: " + ", ".join(channels))
        if terms:
            parts.append("KB/Build: " + ", ".join(terms))
        return " • ".join(parts) if parts else "Takip listesi boş; bildirim gönderilmeyecek."
