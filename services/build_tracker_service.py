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
TRACKER_REST_URL = "https://bunyaminkaya.com/wp-json/wp/v2/pages/58984"
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


@dataclass
class BuildChangeDetails:
    added_features: list[str]
    fixed_issues: list[str]
    known_issues: list[str]
    source_url: str = ""


@dataclass
class KnownIssue:
    description: str
    affected_versions: str
    status: str
    workaround: str
    source_url: str


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

    def _download_html(self) -> str:
        # WordPress/CDN sayfa önbelleği nedeniyle eski tracker HTML'i dönmemesi için
        # her canlı kontrolde benzersiz sorgu parametresi kullanılır.
        cache_buster = str(int(time() * 1000))
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
        page_error: Exception | None = None
        try:
            response = self.session.get(
                TRACKER_URL,
                params={"mdl_refresh": cache_buster},
                headers=headers,
                timeout=(10, 35),
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            if "bk-wbt-card" in response.text:
                return response.text
            page_error = RuntimeError("Ana sayfa Build Tracker kartlarını içermiyor.")
        except Exception as exc:
            page_error = exc

        # Cloudflare veya bir güvenlik eklentisi normal sayfa isteğini engellerse
        # aynı sayfanın WordPress REST içeriğini ikinci, bağımsız kaynak olarak kullan.
        try:
            response = self.session.get(
                TRACKER_REST_URL,
                params={"context": "view", "_": cache_buster},
                headers={**headers, "Accept": "application/json"},
                timeout=(10, 35),
            )
            response.raise_for_status()
            payload = response.json()
            html = str((payload.get("content") or {}).get("rendered") or "")
            if "bk-wbt-card" not in html:
                raise RuntimeError("WordPress REST yanıtında Build Tracker kartı yok.")
            return html
        except Exception as rest_error:
            raise RuntimeError(
                "Build Tracker verisi hem sayfadan hem WordPress veri uç noktasından alınamadı. "
                f"Sayfa: {page_error}; REST: {rest_error}"
            ) from rest_error

    def fetch(self) -> tuple[list[BuildTrackerRecord], str]:
        soup = BeautifulSoup(self._download_html(), "html.parser")

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
    def _change_section_kind(heading: str) -> str:
        value = heading.casefold()
        if any(word in value for word in ("bilinen sorun", "known issue")):
            return "known_issues"
        if any(word in value for word in ("düzelt", "iyileştirme", "fix", "resolved issue")):
            return "fixed_issues"
        if any(word in value for word in ("yenilik", "yeni özellik", "öne çıkan", "what's new", "new feature")):
            return "added_features"
        return ""

    @staticmethod
    def _clean_change_item(value: str) -> str:
        value = " ".join((value or "").split())
        return value[:500].strip()

    def fetch_change_details(self, record: BuildTrackerRecord) -> BuildChangeDetails:
        """İlgili makale/resmî kaynaktaki yapılandırılmış değişiklik başlıklarını okur."""
        buckets: dict[str, list[str]] = {
            "added_features": [], "fixed_issues": [], "known_issues": [],
        }
        used_source = ""
        urls = [url for url in (record.article_url, record.microsoft_url) if url]
        for url in urls:
            try:
                response = self.session.get(url, timeout=(8, 22))
                response.raise_for_status()
                response.encoding = response.apparent_encoding or "utf-8"
                soup = BeautifulSoup(response.text, "html.parser")
                root = soup.select_one(".entry-content .content-inner, .entry-content, article, main") or soup
                found_here = False
                for heading in root.select("h2, h3, h4"):
                    kind = self._change_section_kind(self._text(heading))
                    if not kind:
                        continue
                    for node in heading.find_all_next():
                        if node is not heading and node.name in ("h2", "h3", "h4"):
                            break
                        if node.name == "li":
                            text = self._clean_change_item(self._text(node))
                            if text and text not in buckets[kind]:
                                buckets[kind].append(text)
                                found_here = True
                        elif node.name == "p" and not node.find_parent("li"):
                            text = self._clean_change_item(self._text(node))
                            if len(text) >= 25 and text not in buckets[kind]:
                                buckets[kind].append(text)
                                found_here = True
                        if len(buckets[kind]) >= 12:
                            break
                if found_here:
                    used_source = url
                    break
            except Exception:
                continue

        # Tracker özeti kaybolmasın; yapılandırılmış yenilik başlığı bulunamadığında
        # bunu yalnızca genel değişiklik özeti olarak ilk bölümde göster.
        if not buckets["added_features"] and record.description:
            buckets["added_features"].append(record.description)
        return BuildChangeDetails(source_url=used_source, **buckets)

    @staticmethod
    def _issue_status(text: str) -> str:
        value = (text or "").casefold()
        if any(word in value for word in ("resolved", "çözüldü", "fixed", "düzeltildi")):
            return "Çözüldü"
        if any(word in value for word in ("mitigated", "hafifletildi")):
            return "Etkisi azaltıldı"
        if any(word in value for word in ("investigating", "araştırılıyor", "working on a resolution")):
            return "Araştırılıyor"
        return "Devam ediyor"

    def fetch_known_issues(self, record: BuildTrackerRecord) -> list[KnownIssue]:
        """Seçili build için Microsoft'un yayımladığı bilinen sorunları okur."""
        source_url = (record.microsoft_url or "").strip()
        if not source_url:
            return []
        response = self.session.get(source_url, timeout=(8, 25))
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        root = soup.select_one("main, article, .content") or soup
        issues: list[KnownIssue] = []
        affected = f"Windows 11 {record.windows_version}".strip()

        for heading in root.select("h2, h3, h4"):
            if not self._change_section_kind(self._text(heading)) == "known_issues":
                continue
            section_nodes = []
            for node in heading.find_all_next():
                if node is not heading and node.name in ("h2", "h3", "h4"):
                    break
                section_nodes.append(node)

            tables = [node for node in section_nodes if node.name == "table"]
            for table in tables:
                headers = [self._text(cell).casefold() for cell in table.select("thead th")]
                for row in table.select("tbody tr"):
                    cells = [self._clean_change_item(self._text(cell)) for cell in row.select("th, td")]
                    if not cells:
                        continue
                    mapped = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
                    description = next((v for k, v in mapped.items() if any(x in k for x in ("symptom", "issue", "sorun", "belirti"))), cells[0])
                    workaround = next((v for k, v in mapped.items() if any(x in k for x in ("workaround", "resolution", "geçici", "çözüm"))), cells[1] if len(cells) > 1 else "Microsoft tarafından geçici çözüm yayımlanmadı.")
                    status_text = " ".join(cells)
                    issues.append(KnownIssue(description, affected or "—", self._issue_status(status_text), workaround, source_url))

            if not issues:
                texts = []
                for node in section_nodes:
                    if node.name in ("p", "li") and not node.find_parent("table"):
                        text = self._clean_change_item(self._text(node))
                        if len(text) >= 25 and text not in texts:
                            texts.append(text)
                for text in texts[:10]:
                    normalized = text.casefold()
                    if any(phrase in normalized for phrase in (
                        "not currently aware of any issues",
                        "not aware of any issues",
                        "herhangi bir sorun bilinmemektedir",
                        "bir soruna dair bilgi almamıştır",
                        "bilinen bir sorun yoktur",
                    )):
                        continue
                    issues.append(KnownIssue(
                        text, affected or "—", self._issue_status(text),
                        "Microsoft tarafından ayrı bir geçici çözüm yayımlanmadı.", source_url,
                    ))
            break
        return issues

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
