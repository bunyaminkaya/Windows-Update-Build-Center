"""Microsoft'un resmi Windows 11 ISO indirme sayfasından ISO bağlantısı almaya çalışır.

Microsoft yalnızca o an indirmeye açık sürümün ISO'sunu sunar (ör. ``Win11_25H2_Turkish_x64.iso``).
Bağlantı, resmi sayfanın kendi kullandığı yardımcı servislerle (sürüm -> dil -> geçici bağlantı) alınır
ve yaklaşık 24 saat geçerlidir.

ÖNEMLİ: Microsoft bu servisi otomatik isteklere karşı koruyor (Sentinel / bot denetimi). Çok sık deneme,
VPN/proxy ya da yeni denetimler yüzünden istek reddedilebilir; bu durumda ``MicrosoftIsoRejected``
fırlatılır ve çağıran taraf kullanıcıya UUP kaynağını önermelidir. Reddedilince engeli uzatmamak için
10 dakika yeniden denenmez.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from services.settings_service import SettingsService

PAGE_URLS = {
    "x64": "https://www.microsoft.com/en-us/software-download/windows11",
    "ARM64": "https://www.microsoft.com/en-us/software-download/windows11arm64",
}
API_BASE = "https://www.microsoft.com/software-download-connector/api"
PROFILE = "606624d44113"
SESSION_TAG_URL = "https://vlscppe.microsoft.com/tags?org_id=y6jn8c31&session_id={sid}"
TIMEOUT = 25
COOLDOWN_SECONDS = 600
REJECT_MEMORY_SECONDS = 24 * 3600  # Microsoft'un geçici engeli yaklaşık bu kadar sürer
ALLOWED_HOST_SUFFIXES = (".microsoft.com", ".azureedge.net", ".windowsupdate.com")

# Uygulamadaki dil adı -> Microsoft'un sunduğu dil adı adayları (küçük harfle)
LANGUAGE_NAMES = {
    "Türkçe": ("turkish", "türkçe"),
    "English (United States)": ("english",),
    "English (United Kingdom)": ("english international",),
    "Deutsch": ("german", "deutsch"),
    "Français": ("french", "français"),
    "Español": ("spanish", "español"),
    "Italiano": ("italian", "italiano"),
    "Português (Brasil)": ("brazilian portuguese", "português (brasil)"),
    "Português (Portugal)": ("portuguese", "português (portugal)"),
    "Nederlands": ("dutch", "nederlands"),
    "Polski": ("polish", "polski"),
    "Русский": ("russian", "русский"),
    "Українська": ("ukrainian", "українська"),
    "العربية": ("arabic", "العربية"),
    "日本語": ("japanese", "日本語"),
    "한국어": ("korean", "한국어"),
    "中文 (简体)": ("chinese simplified", "中文(简体)", "中文 (简体)"),
    "中文 (繁體)": ("chinese traditional", "中文(繁體)", "中文 (繁體)"),
}
DEFAULT_LANGUAGE = "Türkçe"
_VERSION_IN_NAME = re.compile(r"(\d{2}H[12])", re.I)


class MicrosoftIsoError(RuntimeError):
    """Microsoft'tan ISO bağlantısı alınamadı (ağ, dil yok, sayfa yapısı vb.)."""


class MicrosoftIsoRejected(MicrosoftIsoError):
    """Microsoft otomatik isteği reddetti (Sentinel / bot denetimi / IP engeli)."""


@dataclass(slots=True)
class IsoOffer:
    version: str
    architecture: str
    language: str
    filename: str
    url: str
    page_url: str


class MicrosoftIsoService:
    _blocked_until = 0.0  # tüm örnekler için ortak (işlem ömrü boyunca)

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        )
        self.session.headers.setdefault("Accept-Language", "en-US,en;q=0.9")

    # ---- yardımcılar ----
    def _json(self, url: str, params: dict, referer: str) -> dict:
        response = self.session.get(url, params=params, timeout=TIMEOUT, headers={"Referer": referer})
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise MicrosoftIsoError("Microsoft'un indirme servisi beklenmeyen bir yanıt verdi.") from exc
        errors = payload.get("Errors") if isinstance(payload, dict) else None
        if errors:
            first = errors[0] if isinstance(errors, list) else errors
            text = (first.get("Value") if isinstance(first, dict) else str(first)) or ""
            text = re.sub(r"<[^>]+>", " ", text).strip()
            raise MicrosoftIsoRejected(text or "Microsoft isteği reddetti.")
        return payload

    @staticmethod
    def edition_id_from_page(html_text: str) -> str:
        block = re.search(r"<select[^>]*id=[\"']product-edition[\"'][^>]*>(.*?)</select>", html_text, re.I | re.S)
        scope = block.group(1) if block else html_text
        for value in re.findall(r"<option[^>]*value=[\"'](\d+)[\"']", scope, re.I):
            return value
        raise MicrosoftIsoError("Microsoft indirme sayfasında ISO sürüm listesi bulunamadı (sayfa yapısı değişmiş olabilir).")

    @staticmethod
    def pick_sku(skus: list[dict], language_name: str) -> dict | None:
        wanted = LANGUAGE_NAMES.get(language_name) or (language_name.casefold(),)
        for sku in skus:
            names = {str(sku.get("Language", "")).casefold(), str(sku.get("LocalizedLanguage", "")).casefold()}
            if any(name in names for name in wanted):
                return sku
        return None

    @staticmethod
    def _filename_from_url(url: str) -> str:
        return urlparse(url).path.rsplit("/", 1)[-1]

    @staticmethod
    def _host_ok(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(host.endswith(s) for s in ALLOWED_HOST_SUFFIXES)

    @staticmethod
    def rejected_recently() -> bool:
        """Microsoft son 24 saatte isteği reddettiyse True (kayıt ayarlarda tutulur, program kapansa da korunur)."""
        try:
            stamp = float(SettingsService.load().get("iso_center", {}).get("ms_rejected_at", 0) or 0)
        except Exception:
            return False
        return 0 < time.time() - stamp < REJECT_MEMORY_SECONDS

    @staticmethod
    def remember_rejection() -> None:
        try:
            SettingsService.update_value("iso_center", "ms_rejected_at", time.time())
        except Exception:
            pass

    # ---- ana akış ----
    def find(self, language_name: str = DEFAULT_LANGUAGE, architecture: str = "x64") -> IsoOffer:
        """Microsoft'un o an sunduğu ISO'nun bağlantısını alır. Sürüm, dosya adından okunur."""
        if architecture not in PAGE_URLS:
            raise MicrosoftIsoError("Microsoft yalnızca x64 ve ARM64 için ISO sunar.")
        remaining = MicrosoftIsoService._blocked_until - time.monotonic()
        if remaining > 0:
            raise MicrosoftIsoRejected(
                "Microsoft az önce otomatik isteği reddetti; engeli uzatmamak için "
                f"{int(remaining // 60) + 1} dakika boyunca yeniden denenmeyecek."
            )
        try:
            return self._find(language_name, architecture)
        except MicrosoftIsoRejected:
            MicrosoftIsoService._blocked_until = time.monotonic() + COOLDOWN_SECONDS
            MicrosoftIsoService.remember_rejection()
            raise
        except requests.RequestException as exc:
            raise MicrosoftIsoError(f"Microsoft'a bağlanılamadı: {exc}") from exc

    def _find(self, language_name: str, arch: str) -> IsoOffer:
        page_url = PAGE_URLS[arch]
        page = self.session.get(page_url, timeout=TIMEOUT)
        page.raise_for_status()
        edition_id = self.edition_id_from_page(page.text)

        session_id = str(uuid.uuid4())
        try:  # Microsoft'un oturum kaydı; başarısız olsa da denemeye devam edilir
            self.session.get(SESSION_TAG_URL.format(sid=session_id), timeout=TIMEOUT)
        except requests.RequestException:
            pass

        common = {"profile": PROFILE, "Locale": "en-US", "sessionID": session_id}
        sku_info = self._json(
            f"{API_BASE}/getskuinformationbyproductedition",
            {**common, "ProductEditionId": edition_id, "SKU": "undefined", "friendlyFileName": "undefined"},
            page_url,
        )
        skus = sku_info.get("Skus") or []
        sku = self.pick_sku(skus, language_name)
        if sku is None:
            available = ", ".join(sorted({str(s.get("LocalizedLanguage") or s.get("Language")) for s in skus}))
            raise MicrosoftIsoError(f"{language_name} dili Microsoft'un {arch} ISO listesinde yok. Sunulan diller: {available or '—'}.")

        links = self._json(
            f"{API_BASE}/GetProductDownloadLinksBySku",
            {**common, "productEditionId": "undefined", "SKU": sku.get("Id"), "friendlyFileName": "undefined"},
            page_url,
        )
        candidates = []
        for option in links.get("ProductDownloadOptions") or []:
            url = str(option.get("Uri") or "")
            if url and self._host_ok(url):
                name = self._filename_from_url(url)
                low = name.lower()
                found_arch = "ARM64" if "arm64" in low else ("x64" if "x64" in low else arch)
                candidates.append((found_arch, name, url))
        chosen = next((c for c in candidates if c[0] == arch), candidates[0] if candidates else None)
        if chosen is None:
            raise MicrosoftIsoError("Microsoft bu dil için indirme bağlantısı döndürmedi.")
        found_arch, filename, url = chosen
        match = _VERSION_IN_NAME.search(filename)
        return IsoOffer(
            version=match.group(1).upper() if match else "",
            architecture=found_arch,
            language=language_name,
            filename=filename,
            url=url,
            page_url=page_url,
        )
