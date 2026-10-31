from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests

from app.version import APP_VERSION, UPDATE_INFO_URL, UPDATE_PAGE_URL

logger = logging.getLogger(__name__)


@dataclass
class AppUpdateInfo:
    available: bool
    latest: str = ""
    url: str = UPDATE_PAGE_URL
    notes: str = ""
    error: str = ""


def _version_tuple(value: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", value or "")
    return tuple(int(n) for n in nums) or (0,)


class AppUpdateService:
    """Programın yeni sürümü var mı diye küçük bir JSON dosyasına bakar. Hata sessizce yutulur."""

    @staticmethod
    def is_newer(latest: str, current: str = APP_VERSION) -> bool:
        a, b = _version_tuple(latest), _version_tuple(current)
        width = max(len(a), len(b))
        return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))

    @classmethod
    def check(cls, timeout: float = 8.0, url: str = UPDATE_INFO_URL) -> AppUpdateInfo:
        try:
            response = requests.get(url, timeout=timeout, headers={"User-Agent": "WindowsUpdateBuildCenter"})
            response.raise_for_status()
            data = response.json()
            latest = str(data.get("version", "")).strip()
            if not latest:
                return AppUpdateInfo(False, error="Sürüm bilgisi bulunamadı.")
            page = str(data.get("url") or UPDATE_PAGE_URL)
            if not page.lower().startswith(("https://", "http://")):
                page = UPDATE_PAGE_URL
            return AppUpdateInfo(cls.is_newer(latest), latest, page, str(data.get("notes", ""))[:400])
        except Exception as exc:
            logger.info("Program güncelleme denetimi yapılamadı: %s", exc)
            return AppUpdateInfo(False, error=str(exc))
