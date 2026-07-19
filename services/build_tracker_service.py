from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from time import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from app.paths import DATA_DIR

TRACKER_URL = "https://bunyaminkaya.com/windows-build-tracker/"
CACHE_PATH = DATA_DIR / "build_tracker_cache.json"

MONTHS_TR = {
    "OCA": 1, "ŞUB": 2, "SUB": 2, "MAR": 3, "NİS": 4, "NIS": 4,
    "MAY": 5, "HAZ": 6, "TEM": 7, "AĞU": 8, "AGU": 8,
    "EYL": 9, "EKİ": 10, "EKI": 10, "KAS": 11, "ARA": 12,
}


@dataclass
class BuildTrackerRecord:
    build_number: str
    kb_number: str = ""
    windows_version: str = ""
    channel: str = ""
    release_group: str = ""
    release_date: str = ""
    description: str = ""
    microsoft_url: str = ""
    article_url: str = ""
    article_title: str = ""

    @property
    def search_text(self) -> str:
        return " ".join(
            [
                self.build_number,
                self.kb_number,
                self.windows_version,
                self.channel,
                self.release_group,
                self.description,
                self.article_title,
            ]
        ).lower()


class BuildTrackerService:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
        })

    @staticmethod
    def _text(node) -> str:
        if node is None:
            return ""
        return " ".join(node.get_text(" ", strip=True).split())

    @staticmethod
    def _date_from_group(group) -> str:
        day = BuildTrackerService._text(group.select_one(".bk-wbt-date-day"))
        month = BuildTrackerService._text(group.select_one(".bk-wbt-date-month")).upper()
        year = BuildTrackerService._text(group.select_one(".bk-wbt-date-year"))
        try:
            month_no = MONTHS_TR.get(month)
            if day and month_no and year:
                return f"{int(year):04d}-{month_no:02d}-{int(day):02d}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_last_update(soup: BeautifulSoup) -> str:
        candidates = [
            soup.select_one(".bk-wbt-freshness-info"),
            soup.select_one(".bk-wbt-update-value"),
        ]
        for candidate in candidates:
            text = BuildTrackerService._text(candidate)
            match = re.search(r"(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})", text)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _release_date_for_card(card) -> str:
        # Önce doğrudan veri özniteliklerini dene. İleride sayfa yapısı değişse bile
        # yeni kayıtların tarihini kaybetmemek için birden fazla ad desteklenir.
        for attr in ("data-release-date", "data-date", "data-published"):
            value = (card.get(attr) or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return value
            match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", value)
            if match:
                return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

        group = card.find_parent(class_="bk-wbt-date-group")
        if group is not None:
            value = BuildTrackerService._date_from_group(group)
            if value:
                return value

        # Son çare: kartın yakınındaki metinden dd.mm.yyyy tarihini yakala.
        nearby = BuildTrackerService._text(group if group is not None else card.parent)
        match = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", nearby)
        if match:
            return f"{int(match.group(3)):04d}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"
        return ""

    def fetch(self) -> tuple[list[BuildTrackerRecord], str]:
        # WordPress/CDN sayfa önbelleği nedeniyle eski tracker HTML'i dönmemesi için
        # her canlı kontrolde benzersiz sorgu parametresi kullanılır.
        cache_buster = str(int(time() * 1000))
        response = self.session.get(
            TRACKER_URL,
            params={"mdl_refresh": cache_buster},
            headers={
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
            timeout=30,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        records: list[BuildTrackerRecord] = []
        seen: set[tuple[str, str, str, str]] = set()

        # Kartları tarih gruplarının içinden değil doğrudan tüm sayfadan tara.
        # Böylece yeni sürümde HTML sarmalayıcısı değişse bile güncel kartlar okunur.
        for card in soup.select(".bk-wbt-card"):
            build = self._text(card.select_one(".bk-wbt-build-number"))
            if not build:
                # data-build gibi olası gelecekteki öznitelikleri de destekle.
                build = (card.get("data-build") or card.get("data-build-number") or "").strip()
            if not build:
                continue

            version = (card.get("data-version") or "").strip()
            channel = (card.get("data-channel") or "").strip()
            release_group = (card.get("data-release-group") or "").strip()
            release_date = self._release_date_for_card(card)
            description = self._text(card.select_one(".bk-wbt-build-highlight"))
            kb = self._text(card.select_one(".bk-wbt-badge.is-kb"))

            if not kb:
                all_text = self._text(card)
                match = re.search(r"\bKB\d{6,8}\b", all_text, flags=re.I)
                if match:
                    kb = match.group(0).upper()

            microsoft_link = card.select_one(".bk-wbt-row-link")
            if microsoft_link is None:
                microsoft_link = card.select_one(".bk-wbt-build-source a")
            microsoft_url = (microsoft_link.get("href") if microsoft_link else "") or ""

            article_link = card.select_one(".bk-wbt-details-link")
            article_url = (article_link.get("href") if article_link else "") or ""
            article_title = ""
            if article_link:
                article_title = article_link.get("title") or self._text(article_link)

            key = (build, version, channel, release_date)
            if key in seen:
                continue
            seen.add(key)

            records.append(BuildTrackerRecord(
                build_number=build,
                kb_number=kb,
                windows_version=version,
                channel=channel,
                release_group=release_group,
                release_date=release_date,
                description=description,
                microsoft_url=microsoft_url,
                article_url=article_url,
                article_title=article_title,
            ))

        if not records:
            raise RuntimeError(
                "Windows Build Tracker sayfasından kayıt okunamadı. "
                "Sayfa yapısı değişmiş veya bağlantı geçici olarak kullanılamıyor olabilir."
            )

        # En yeni kayıtlar her zaman listenin başında olsun.
        records.sort(key=lambda item: (item.release_date, item.build_number), reverse=True)

        last_update = self._extract_last_update(soup)
        self._save_cache(records, last_update)
        return records, last_update

    @staticmethod
    def _save_cache(records: list[BuildTrackerRecord], last_update: str) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "last_update": last_update,
            "records": [asdict(record) for record in records],
        }
        CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def load_cache() -> tuple[list[BuildTrackerRecord], str, str]:
        if not CACHE_PATH.exists():
            return [], "", ""
        try:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            records = [BuildTrackerRecord(**item) for item in payload.get("records", [])]
            return records, payload.get("last_update", ""), payload.get("fetched_at", "")
        except Exception:
            return [], "", ""
