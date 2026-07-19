from __future__ import annotations

import json
from pathlib import Path

from app.paths import DATA_DIR
from services.search_result import SearchResult


class OfficialCacheService:
    def __init__(self) -> None:
        self.path = DATA_DIR / "official_build_cache.json"

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().upper().replace(" ", "")

    def search(self, query: str) -> list[SearchResult]:
        if not self.path.exists():
            return []

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

        needle = self._normalize(query)
        results: list[SearchResult] = []

        for record in payload.get("records", []):
            keys = {
                self._normalize(str(value))
                for value in record.get("keys", [])
            }
            if needle not in keys:
                continue

            results.append(
                SearchResult(
                    update_id=record.get("update_id", ""),
                    title=record.get("title", ""),
                    product=record.get("product", ""),
                    classification=record.get("classification", ""),
                    last_updated=record.get("last_updated", ""),
                    version=record.get("version", ""),
                    size=record.get("size", "—"),
                    source=record.get("source", "Microsoft"),
                    source_url=record.get("source_url", ""),
                    channel=record.get("channel", ""),
                )
            )

        return results
