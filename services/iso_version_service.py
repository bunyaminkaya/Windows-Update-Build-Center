"""26H2 / 25H2 gibi sürüm adıyla yapılan aramayı, o sürümün en son yayın build'ine çevirir.

Microsoft aylık güncellemeler ve çoğu sürüm için hazır ISO yayımlamaz; ISO, UUP kaynaklarından
build numarasıyla üretilir. Bu yüzden sürüm adı, programın Windows Sürüm Takibi verisindeki
en son yayın build'ine (ör. 26H2 -> 26300.9711) çevrilir ve UUP ISO Oluşturucu'ya aktarılır.
"""
from __future__ import annotations

import re

from services.build_tracker_service import BuildTrackerRecord

_VERSION_QUERY = re.compile(
    r"^(?:windows\s*11\s*)?(?:version\s*|sürüm\s*)?(\d{2}h[12])(?:\s*(?:iso|iso\s*indir|indir))?$",
    re.I,
)


def parse_version_query(query: str) -> str | None:
    """'26H2', 'Windows 11 25h2 iso' gibi sorgudan sürüm adını (26H2) çıkarır; değilse None."""
    match = _VERSION_QUERY.match((query or "").strip())
    return match.group(1).upper() if match else None


def _build_key(build: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)\s*", build or "")
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def _channel_rank(channel: str) -> int:
    """Düşük sayı = ISO için daha uygun. Genel yayın > Release Preview > diğer önizlemeler > Insider."""
    value = (channel or "").lower()
    if "retail" in value or value.strip() == "ga":
        return 0
    if "release preview" in value:
        return 1
    if "preview" in value or "beta" in value or "experimental" in value:
        return 2
    if "dev" in value or "canary" in value:
        return 4
    return 3


def latest_build_for_version(records: list[BuildTrackerRecord], version: str) -> BuildTrackerRecord | None:
    """Verilen sürüm için ISO'ya en uygun kaydı seçer: önce genel yayın, sonra en yüksek build."""
    version = version.upper()
    candidates = [
        r for r in records
        if (r.windows_version or "").strip().upper() == version and _build_key(r.build_number) != (0, 0)
    ]
    if not candidates:
        return None
    best_rank = min(_channel_rank(r.channel) for r in candidates)
    pool = [r for r in candidates if _channel_rank(r.channel) == best_rank]
    return max(pool, key=lambda r: _build_key(r.build_number))
