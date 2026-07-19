from __future__ import annotations

from urllib.parse import urlencode
import time

import requests

from services.uup_result import UupSearchResult
from services.uup_download_package import UupDownloadPackage

API_BASE = "https://api.uupdump.net"
SITE_BASE = "https://uupdump.net"

ARCH_MAP = {
    "x64": "amd64",
    "ARM64": "arm64",
    "x86": "x86",
}

LANGUAGE_MAP = {
    "Türkçe": "tr-tr",
    "English (United States)": "en-us",
    "English (United Kingdom)": "en-gb",
    "Deutsch": "de-de",
    "Français": "fr-fr",
    "Español": "es-es",
    "Italiano": "it-it",
    "Português (Brasil)": "pt-br",
    "Português (Portugal)": "pt-pt",
    "Nederlands": "nl-nl",
    "Polski": "pl-pl",
    "Русский": "ru-ru",
    "Українська": "uk-ua",
    "العربية": "ar-sa",
    "日本語": "ja-jp",
    "한국어": "ko-kr",
    "中文 (简体)": "zh-cn",
    "中文 (繁體)": "zh-tw",
}

EDITION_HINTS = {
    "Windows 11": ["CORE", "COREN", "HOMEBASIC", "HOMEPREMIUM"],
    "Windows 11 Pro": ["PROFESSIONAL", "PROFESSIONALN"],
}


class UupService:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def _get(self, endpoint: str, params: dict) -> dict:
        url = f"{API_BASE}/{endpoint}"
        max_attempts = 5
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=25,
                )

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "").strip()
                    try:
                        wait_seconds = max(1, min(60, int(retry_after)))
                    except Exception:
                        wait_seconds = min(30, 2 ** attempt)

                    last_error = RuntimeError(
                        "UUP hizmeti geçici olarak çok fazla istek aldı. "
                        f"{wait_seconds} saniye sonra yeniden deneniyor."
                    )
                    if attempt < max_attempts:
                        time.sleep(wait_seconds)
                        continue
                    raise last_error

                if response.status_code in {500, 502, 503, 504}:
                    wait_seconds = min(20, 2 ** attempt)
                    last_error = RuntimeError(
                        f"UUP hizmeti geçici olarak kullanılamıyor (HTTP {response.status_code})."
                    )
                    if attempt < max_attempts:
                        time.sleep(wait_seconds)
                        continue
                    raise last_error

                response.raise_for_status()
                payload = response.json()

                api_response = payload.get("response", {})
                if isinstance(api_response, dict) and api_response.get("error"):
                    raise RuntimeError(str(api_response["error"]))

                return api_response

            except requests.RequestException as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                time.sleep(min(15, 2 ** attempt))

        if isinstance(last_error, RuntimeError):
            raise last_error
        raise RuntimeError(
            "Microsoft UUP bağlantıları alınamadı. Ağ bağlantısını kontrol edip yeniden deneyin."
        ) from last_error

    @staticmethod
    def _normalize_arch(value: str) -> str:
        value = (value or "").lower()
        if value == "amd64":
            return "x64"
        if value == "arm64":
            return "ARM64"
        if value == "x86":
            return "x86"
        return value or "Belirsiz"

    @staticmethod
    def _pick_edition(
        edition_list: list[str],
        fancy_names: dict,
        requested_name: str,
    ) -> tuple[str, str]:
        wanted = EDITION_HINTS.get(requested_name, [])

        for code in wanted:
            if code in edition_list:
                return code, fancy_names.get(code, code)

        requested_lower = requested_name.lower()
        for code in edition_list:
            fancy = str(fancy_names.get(code, code))
            if requested_lower in fancy.lower():
                return code, fancy

        if edition_list:
            code = edition_list[0]
            return code, fancy_names.get(code, code)

        return "", ""

    def search(
        self,
        build: str,
        architecture: str,
        language_name: str,
        edition_name: str,
    ) -> list[UupSearchResult]:
        build = build.strip()
        api_arch = ARCH_MAP.get(architecture, architecture.lower())
        language_code = LANGUAGE_MAP.get(language_name, "en-us")

        response = self._get(
            "listid.php",
            {
                "search": build,
                "sortByDate": 1,
            },
        )

        raw_builds = response.get("builds", [])
        if isinstance(raw_builds, dict):
            raw_builds = list(raw_builds.values())

        matches: list[UupSearchResult] = []

        for item in raw_builds or []:
            item_build = str(item.get("build", "")).strip()
            item_arch = str(item.get("arch", "")).strip().lower()

            if item_build != build:
                continue
            if item_arch != api_arch.lower():
                continue

            uuid = str(item.get("uuid", "")).strip()
            if not uuid:
                continue

            result = UupSearchResult(
                uuid=uuid,
                title=str(item.get("title", "")).strip(),
                build=item_build,
                architecture=self._normalize_arch(item_arch),
                created=int(item.get("created", 0) or 0),
                language_code=language_code,
                source_url=(
                    f"{SITE_BASE}/selectlang.php?"
                    + urlencode({"id": uuid})
                ),
            )

            # Check available languages.
            try:
                language_response = self._get(
                    "listlangs.php",
                    {"id": uuid},
                )
                language_list = [
                    str(value).lower()
                    for value in language_response.get("langList", [])
                ]
                result.language_available = (
                    language_code.lower() in language_list
                )
            except Exception as exc:
                result.notes.append(
                    f"Dil listesi alınamadı: {exc}"
                )

            # Check available editions for selected language.
            if result.language_available:
                try:
                    edition_response = self._get(
                        "listeditions.php",
                        {
                            "id": uuid,
                            "lang": language_code,
                        },
                    )
                    edition_list = [
                        str(value)
                        for value in edition_response.get(
                            "editionList",
                            [],
                        )
                    ]
                    fancy_names = edition_response.get(
                        "editionFancyNames",
                        {},
                    )
                    code, fancy = self._pick_edition(
                        edition_list,
                        fancy_names,
                        edition_name,
                    )
                    result.edition_code = code
                    result.edition_name = fancy
                    result.edition_available = bool(code)
                except Exception as exc:
                    result.notes.append(
                        f"Edition listesi alınamadı: {exc}"
                    )

            # Validate UUP set without fetching temporary file URLs.
            if (
                result.language_available
                and result.edition_available
            ):
                try:
                    set_response = self._get(
                        "get.php",
                        {
                            "id": uuid,
                            "lang": language_code,
                            "edition": result.edition_code,
                            "noLinks": 1,
                        },
                    )
                    files = set_response.get("files", {})
                    if isinstance(files, dict):
                        result.file_count = len(files)
                        for info in files.values():
                            try:
                                result.total_size += int(
                                    info.get("size", 0) or 0
                                )
                            except Exception:
                                pass
                except Exception as exc:
                    result.notes.append(
                        f"UUP seti doğrulanamadı: {exc}"
                    )

            matches.append(result)

        return matches


    @staticmethod
    def _size_label(size_bytes: int) -> str:
        if size_bytes <= 0:
            return "—"
        if size_bytes >= 1024 ** 3:
            return f"{size_bytes / 1024 ** 3:.2f} GB"
        if size_bytes >= 1024 ** 2:
            return f"{size_bytes / 1024 ** 2:.1f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes} B"

    @staticmethod
    def _extract_url(info) -> str:
        if isinstance(info, str):
            return info
        if not isinstance(info, dict):
            return ""

        for key in ("url", "downloadUrl", "download_url"):
            value = info.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value

        urls = info.get("urls")
        if isinstance(urls, list):
            for value in urls:
                if isinstance(value, str) and value.startswith("http"):
                    return value
                if isinstance(value, dict):
                    nested = UupService._extract_url(value)
                    if nested:
                        return nested
        return ""

    def get_download_packages(
        self,
        uuid: str,
        language_code: str,
        edition_code: str,
        architecture: str,
    ) -> list[UupDownloadPackage]:
        response = self._get(
            "get.php",
            {
                "id": uuid,
                "lang": language_code,
                "edition": edition_code,
            },
        )

        files = response.get("files", {})
        if not isinstance(files, dict):
            raise RuntimeError("UUP dosya listesi beklenen biçimde alınamadı.")

        packages: list[UupDownloadPackage] = []
        missing_links = 0

        for filename, info in files.items():
            url = self._extract_url(info)
            if not url:
                missing_links += 1
                continue

            size_bytes = 0
            sha1 = ""
            if isinstance(info, dict):
                try:
                    size_bytes = int(info.get("size", 0) or 0)
                except Exception:
                    size_bytes = 0
                sha1 = str(info.get("sha1", "") or "")

            packages.append(
                UupDownloadPackage(
                    filename=str(filename),
                    direct_url=url,
                    architecture=architecture,
                    size=self._size_label(size_bytes),
                    size_bytes=size_bytes,
                    sha1=sha1,
                )
            )

        if not packages:
            raise RuntimeError(
                "UUP seti bulundu ancak Microsoft indirme bağlantıları alınamadı. "
                "Bağlantılar geçici olabilir; birkaç dakika sonra yeniden deneyin."
            )

        packages.sort(key=lambda item: item.filename.lower())
        return packages
