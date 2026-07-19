from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from services.search_result import SearchResult

FLIGHT_HUB_URLS = [
    "https://learn.microsoft.com/en-us/windows-insider/flight-hub/",
    "https://learn.microsoft.com/en-us/windows-insider/flight-hub",
]

RELEASE_CHANNELS = [
    ("experimental-future-platforms", "Experimental (Future Platforms)"),
    ("experimental-26-h1", "Experimental (26H1)"),
    ("experimental", "Experimental"),
    ("beta", "Beta"),
    ("beta-26-h1", "Beta (26H1)"),
    ("canary", "Canary"),
    ("dev", "Dev"),
    ("release-preview", "Release Preview"),
]


class InsiderService:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
            "Cache-Control": "no-cache",
        })

    @staticmethod
    def is_build_query(query: str) -> bool:
        return re.fullmatch(r"\d{4,5}\.\d{1,5}", query.strip()) is not None

    def _fetch_requests(self, url: str) -> str:
        response = self.session.get(url, timeout=10, allow_redirects=True)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _fetch_powershell(url: str) -> str:
        if not sys.platform.startswith("win"):
            return ""

        temp_path = Path(tempfile.gettempdir()) / (
            f"mdlb_learn_{os.getpid()}_{abs(hash(url))}.html"
        )
        escaped_url = url.replace("'", "''")
        escaped_path = str(temp_path).replace("'", "''")
        command = (
            "$ErrorActionPreference='Stop';"
            "[Net.ServicePointManager]::SecurityProtocol="
            "[Net.SecurityProtocolType]::Tls12;"
            f"$r=Invoke-WebRequest -UseBasicParsing -Uri '{escaped_url}';"
            f"[IO.File]::WriteAllText('{escaped_path}',"
            "$r.Content,[Text.Encoding]::UTF8)"
        )
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy", "Bypass",
                    "-Command", command,
                ],
                capture_output=True,
                text=True,
                timeout=25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0 or not temp_path.exists():
                return ""
            return temp_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return ""
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _fetch(self, url: str) -> str:
        try:
            return self._fetch_requests(url)
        except Exception:
            return self._fetch_powershell(url)

    @staticmethod
    def _release_date_from_html(page_html: str) -> str:
        soup = BeautifulSoup(page_html, "html.parser")
        text = " ".join(soup.stripped_strings)
        match = re.search(
            r"Release date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            text,
            re.I,
        )
        return match.group(1) if match else ""

    def _search_direct_release_note(
        self,
        build: str,
    ) -> list[SearchResult]:
        slug = build.replace(".", "-")

        # Use likely channel first based on build family.
        candidates = list(RELEASE_CHANNELS)
        if build.startswith("29"):
            candidates.sort(
                key=lambda item: 0
                if item[0] == "experimental-future-platforms"
                else 1
            )
        elif build.startswith("281"):
            candidates.sort(
                key=lambda item: 0
                if item[0] == "experimental-26-h1"
                else 1
            )
        elif build.startswith("263"):
            candidates.sort(
                key=lambda item: 0
                if item[0] == "experimental"
                else 1
            )
        elif build.startswith("2622"):
            candidates.sort(
                key=lambda item: 0
                if item[0] == "beta"
                else 1
            )

        for channel_slug, channel_name in candidates:
            url = (
                "https://learn.microsoft.com/en-us/windows-insider/"
                f"release-notes/{channel_slug}/preview-build-{slug}"
            )
            page = self._fetch(url)
            if not page:
                continue

            soup = BeautifulSoup(page, "html.parser")
            page_text = " ".join(soup.stripped_strings)

            # Avoid treating generic 404 shell pages as valid.
            if build not in page_text:
                continue

            title_node = soup.find("h1")
            title = (
                " ".join(title_node.stripped_strings)
                if title_node
                else f"Windows 11 Insider Preview Build {build}"
            )

            return [
                SearchResult(
                    update_id=f"insider:{build}",
                    title=title,
                    product="Windows 11 Insider Preview",
                    classification=channel_name,
                    last_updated=self._release_date_from_html(page),
                    version=build,
                    size="—",
                    source="Microsoft Learn",
                    source_url=url,
                    channel=channel_name,
                )
            ]

        return []

    def _search_flight_hub(self, build: str) -> list[SearchResult]:
        for url in FLIGHT_HUB_URLS:
            page = self._fetch(url)
            if not page:
                continue

            soup = BeautifulSoup(page, "html.parser")

            # Strong parser: inspect every table row as a whole.
            for row in soup.find_all("tr"):
                row_text = " ".join(row.stripped_strings)
                if build not in row_text:
                    continue

                cells = [
                    " ".join(cell.stripped_strings).strip()
                    for cell in row.find_all(["th", "td"])
                ]
                release_date = cells[-1] if len(cells) > 1 else ""
                heading = row.find_previous(["h2", "h3", "h4"])
                channel = (
                    " ".join(heading.stripped_strings).strip()
                    if heading
                    else "Windows Insider"
                )

                return [
                    SearchResult(
                        update_id=f"flight-hub:{build}",
                        title=f"Windows 11 Insider Preview Build {build}",
                        product="Windows 11 Insider Preview",
                        classification=channel,
                        last_updated=release_date,
                        version=build,
                        size="—",
                        source="Microsoft Flight Hub",
                        source_url=url,
                        channel=channel,
                    )
                ]

            # Last fallback: raw page contains build but table markup changed.
            if build in " ".join(soup.stripped_strings):
                return [
                    SearchResult(
                        update_id=f"flight-hub:{build}",
                        title=f"Windows 11 Insider Preview Build {build}",
                        product="Windows 11 Insider Preview",
                        classification="Windows Insider",
                        last_updated="",
                        version=build,
                        size="—",
                        source="Microsoft Flight Hub",
                        source_url=url,
                        channel="Windows Insider",
                    )
                ]

        return []

    def search_build(self, build: str) -> list[SearchResult]:
        if not self.is_build_query(build):
            return []

        # Direct release notes are more precise than the Flight Hub.
        results = self._search_direct_release_note(build)
        if results:
            return results

        return self._search_flight_hub(build)
