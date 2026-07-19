from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

CATALOG_BASES = [
    "https://www.catalog.update.microsoft.com",
    "https://catalog.update.microsoft.com",
]
TIMEOUT = 18


from services.search_result import SearchResult as CatalogResult

class CatalogService:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })

    @staticmethod
    def _queries(query: str) -> list[str]:
        query = query.strip()
        if not query:
            return []
        kb = re.fullmatch(r"KB\s*(\d+)", query, re.I)
        if kb:
            number = kb.group(1)
            return [number, f"KB{number}"]
        return [query]

    def search(self, query: str) -> list[CatalogResult]:
        errors: list[str] = []
        had_network_error = False

        for candidate in self._queries(query):
            for base in CATALOG_BASES:
                try:
                    url = f"{base}/Search.aspx?q={quote(candidate)}"
                    response = self.session.get(url, timeout=TIMEOUT, allow_redirects=True)
                    response.raise_for_status()
                    results = self._parse_results(response.text)
                    if results:
                        for item in results:
                            item.source = "Microsoft Update Catalog"
                            item.source_url = url
                        return results
                except requests.RequestException as exc:
                    had_network_error = True
                    errors.append(f"{base}: {exc.__class__.__name__}")
                except Exception as exc:
                    errors.append(str(exc))

        # Windows PowerShell fallback: iki resmi Catalog alan adını da dene.
        if sys.platform.startswith("win"):
            for candidate in self._queries(query):
                for base in CATALOG_BASES:
                    try:
                        page = self._fetch_with_powershell(candidate, base)
                        if page:
                            results = self._parse_results(page)
                            if results:
                                for item in results:
                                    item.source = "Microsoft Update Catalog"
                                    item.source_url = f"{base}/Search.aspx?q={quote(candidate)}"
                                return results
                    except Exception as exc:
                        errors.append(f"PowerShell: {exc.__class__.__name__}")

        if had_network_error:
            raise ConnectionError(
                "Microsoft Update Catalog'a şu anda ağ veya DNS üzerinden erişilemiyor. "
                "Program diğer Microsoft kaynaklarını kontrol etmeye devam edebilir."
            )
        return []

    @staticmethod
    def _fetch_with_powershell(query: str, base: str) -> str:
        temp_path = Path(tempfile.gettempdir()) / f"mdlb_catalog_{os.getpid()}_{abs(hash(query))}.html"
        url = f"{base}/Search.aspx?q={quote(query)}".replace("'", "''")
        target = str(temp_path).replace("'", "''")
        command = (
            "$ErrorActionPreference='Stop';"
            "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
            f"$r=Invoke-WebRequest -UseBasicParsing -Uri '{url}';"
            f"[IO.File]::WriteAllText('{target}',$r.Content,[Text.Encoding]::UTF8)"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 or not temp_path.exists():
                return ""
            return temp_path.read_text(encoding="utf-8", errors="ignore")
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    @staticmethod
    def _parse_results(page_html: str) -> list[CatalogResult]:
        soup = BeautifulSoup(page_html, "html.parser")
        table = soup.find(id="ctl00_catalogBody_updateMatches")
        results: list[CatalogResult] = []
        seen: set[str] = set()
        guid_pattern = re.compile(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        )

        if table:
            for row in table.find_all("tr"):
                if row.get("id") == "headerRow":
                    continue
                cells = row.find_all("td", recursive=False)
                if len(cells) < 8:
                    continue
                input_node = cells[7].find("input")
                update_id = str(input_node.get("id", "")).strip() if input_node else ""
                if not guid_pattern.fullmatch(update_id) or update_id in seen:
                    continue

                def cell_text(index: int) -> str:
                    return html.unescape(" ".join(cells[index].stripped_strings).strip())

                size_node = cells[6].find("span")
                size = " ".join(size_node.stripped_strings).strip() if size_node else cell_text(6)
                results.append(CatalogResult(
                    update_id=update_id,
                    title=cell_text(1),
                    product=cell_text(2),
                    classification=cell_text(3),
                    last_updated=cell_text(4),
                    version=cell_text(5),
                    size=size,
                    source="Microsoft Update Catalog",
                ))
                seen.add(update_id)

        return results
