from __future__ import annotations

import html
import json
import re
from urllib.parse import unquote, urlparse

import requests

from services.catalog_service import CatalogService
from services.package_result import PackageResult

CATALOG_BASES = [
    "https://www.catalog.update.microsoft.com",
    "https://catalog.update.microsoft.com",
]

ALLOWED_MICROSOFT_HOST_SUFFIXES = (
    ".microsoft.com",
    ".windowsupdate.com",
    ".delivery.mp.microsoft.com",
    ".dl.delivery.mp.microsoft.com",
    ".download.windowsupdate.com",
)


class PackageService:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        self.catalog = CatalogService()

    @staticmethod
    def _architecture_from_text(text: str) -> str:
        value = text.lower()
        if "arm64" in value:
            return "ARM64"
        if (
            "x64" in value
            or "64-bit" in value
            or "x64-based" in value
        ):
            return "x64"
        if (
            "x86" in value
            or "32-bit" in value
            or "x86-based" in value
        ):
            return "x86"
        return "Belirsiz"

    @staticmethod
    def _filename_from_url(url: str) -> str:
        path = urlparse(url).path
        return (
            unquote(path.rsplit("/", 1)[-1])
            or "Microsoft_Update_Package"
        )

    @staticmethod
    def _file_type(filename: str) -> str:
        if "." not in filename:
            return "DOSYA"
        return filename.rsplit(".", 1)[-1].upper()

    @staticmethod
    def _is_official_microsoft_url(url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower()
            return any(
                host == suffix.lstrip(".")
                or host.endswith(suffix)
                for suffix in ALLOWED_MICROSOFT_HOST_SUFFIXES
            )
        except Exception:
            return False

    def _get_download_dialog(
        self,
        update_id: str,
    ) -> str:
        # This is the exact payload structure used by the working
        # Microsoft Update Catalog DownloadDialog flow.
        payload = [{
            "size": 0,
            "UpdateID": update_id,
            "UpdateIDInfo": update_id,
        }]

        errors: list[str] = []

        for base in CATALOG_BASES:
            try:
                response = self.session.post(
                    base + "/DownloadDialog.aspx",
                    data={
                        "UpdateIDs": json.dumps(
                            payload,
                            separators=(",", ":"),
                        )
                    },
                    headers={
                        "Referer": base + "/",
                        "Origin": base,
                    },
                    timeout=20,
                    allow_redirects=True,
                )
                response.raise_for_status()

                if response.text:
                    return response.text

            except Exception as exc:
                errors.append(
                    f"{base}: {exc.__class__.__name__}"
                )

        raise RuntimeError(
            "Microsoft Update Catalog DownloadDialog yanıtı alınamadı. "
            + " | ".join(errors)
        )

    @staticmethod
    def _extract_download_urls(
        response_text: str,
    ) -> list[str]:
        text = (
            html.unescape(response_text)
            .replace("\\/", "/")
            .replace("\\u0026", "&")
        )

        # Primary parser: exact JavaScript structure used by Catalog.
        matches = re.findall(
            r"downloadInformation\[\d+\]\.files\[\d+\]\.url"
            r"\s*=\s*['\"]([^'\"]+)['\"]",
            text,
            flags=re.I,
        )

        # Secondary fallback for markup variations.
        if not matches:
            matches = re.findall(
                r"https://[^\"'<>\\s]+?"
                r"\.(?:msu|cab|exe|psf)"
                r"(?:\?[^\"'<>\\s]*)?",
                text,
                flags=re.I,
            )

        clean: list[str] = []

        for url in matches:
            value = (
                html.unescape(url)
                .replace("\\/", "/")
                .replace("\\u0026", "&")
            )

            if value not in clean:
                clean.append(value)

        return clean

    def find_packages_for_kb(
        self,
        kb: str,
    ) -> list[PackageResult]:
        kb = kb.strip().upper()

        if not kb.startswith("KB"):
            kb = "KB" + re.sub(r"\D", "", kb)

        updates = self.catalog.search(kb)

        packages: list[PackageResult] = []
        seen_urls: set[str] = set()
        dialog_success_count = 0

        for update in updates:
            try:
                page = self._get_download_dialog(
                    update.update_id
                )
                dialog_success_count += 1
            except Exception:
                continue

            urls = self._extract_download_urls(page)

            for url in urls:
                if url in seen_urls:
                    continue

                if not self._is_official_microsoft_url(url):
                    continue

                seen_urls.add(url)

                filename = self._filename_from_url(url)

                architecture = self._architecture_from_text(
                    f"{update.title} {filename}"
                )

                packages.append(
                    PackageResult(
                        update_id=update.update_id,
                        update_title=update.title,
                        filename=filename,
                        architecture=architecture,
                        file_type=self._file_type(filename),
                        size=update.size or "—",
                        direct_url=url,
                        source="Microsoft Update Catalog",
                        product=update.product or "",
                        classification=update.classification or "",
                        version=update.version or "",
                        last_updated=update.last_updated or "",
                    )
                )

        if updates and dialog_success_count == 0:
            raise RuntimeError(
                "Catalog kayıtları bulundu ancak Microsoft "
                "DownloadDialog yanıtı alınamadı."
            )

        architecture_order = {
            "x64": 0,
            "ARM64": 1,
            "x86": 2,
            "Belirsiz": 3,
        }

        packages.sort(
            key=lambda item: (
                architecture_order.get(
                    item.architecture,
                    9,
                ),
                item.filename.lower(),
            )
        )

        return packages
