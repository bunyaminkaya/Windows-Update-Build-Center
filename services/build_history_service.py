from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from app.paths import BUILD_HISTORY_PATH
from services.build_tracker_service import BuildTrackerRecord


class BuildHistoryService:
    MAX_ENTRIES = 500

    @classmethod
    def load(cls) -> list[dict[str, Any]]:
        try:
            if not BUILD_HISTORY_PATH.exists():
                return []
            payload = json.loads(BUILD_HISTORY_PATH.read_text(encoding="utf-8"))
            entries = payload.get("entries", []) if isinstance(payload, dict) else []
            return [entry for entry in entries if isinstance(entry, dict)]
        except Exception:
            return []

    @classmethod
    def _save(cls, entries: list[dict[str, Any]]) -> None:
        BUILD_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": entries[: cls.MAX_ENTRIES]}
        temp = BUILD_HISTORY_PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(BUILD_HISTORY_PATH)

    @classmethod
    def _prepend(cls, entry: dict[str, Any]) -> None:
        try:
            entries = cls.load()
            entries.insert(0, entry)
            cls._save(entries)
        except Exception:
            # Geçmiş kaydı hiçbir zaman canlı Build Tracker yenilemesini bozmasın.
            pass

    @classmethod
    def record_success(
        cls,
        records: list[BuildTrackerRecord],
        new_records: list[BuildTrackerRecord],
        source_last_update: str = "",
    ) -> None:
        cls._prepend({
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "status": "success",
            "new_count": len(new_records),
            "total_count": len(records),
            "source_last_update": source_last_update,
            "new_records": [
                {
                    "build": record.build_number,
                    "kb": record.kb_number,
                    "version": record.windows_version,
                    "channel": record.channel,
                    "release_date": record.release_date,
                }
                for record in new_records[:25]
            ],
        })

    @classmethod
    def record_failure(cls, message: str) -> None:
        cls._prepend({
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "status": "failed",
            "new_count": 0,
            "total_count": 0,
            "message": " ".join((message or "Bilinmeyen hata").split())[:500],
            "new_records": [],
        })

    @staticmethod
    def _entry_datetime(entry: dict[str, Any]) -> datetime | None:
        try:
            return datetime.fromisoformat(str(entry.get("checked_at", "")))
        except Exception:
            return None

    @classmethod
    def summary(cls, now: datetime | None = None) -> dict[str, dict[str, int]]:
        current = now or datetime.now()
        today_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        result = {
            "today": {"checks": 0, "new": 0, "failed": 0},
            "week": {"checks": 0, "new": 0, "failed": 0},
            "month": {"checks": 0, "new": 0, "failed": 0},
        }
        for entry in cls.load():
            stamp = cls._entry_datetime(entry)
            if stamp is None:
                continue
            for key, start in (("today", today_start), ("week", week_start), ("month", month_start)):
                if stamp >= start:
                    result[key]["checks"] += 1
                    result[key]["new"] += int(entry.get("new_count", 0) or 0)
                    if entry.get("status") == "failed":
                        result[key]["failed"] += 1
        return result

    @classmethod
    def release_groups(
        cls,
        records: list[BuildTrackerRecord],
        now: datetime | None = None,
    ) -> dict[str, list[BuildTrackerRecord]]:
        """Tracker kayıtlarını program kontrolüne değil gerçek yayın tarihine göre gruplar."""
        current = now or datetime.now()
        today = current.replace(hour=0, minute=0, second=0, microsecond=0)
        week = today - timedelta(days=today.weekday())
        month = today.replace(day=1)
        groups: dict[str, list[BuildTrackerRecord]] = {"today": [], "week": [], "month": []}
        for record in records:
            try:
                stamp = datetime.strptime(record.release_date, "%Y-%m-%d")
            except Exception:
                continue
            if stamp >= month:
                groups["month"].append(record)
            if stamp >= week:
                groups["week"].append(record)
            if stamp >= today:
                groups["today"].append(record)
        return groups
