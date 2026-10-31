from __future__ import annotations

import re

from services.catalog_service import CatalogService
from services.insider_service import InsiderService
from services.official_cache_service import OfficialCacheService
from services.build_tracker_service import BuildTrackerService
from services.iso_version_service import latest_build_for_version, parse_version_query
from services.ms_iso_service import MicrosoftIsoService, PAGE_URLS
from services.search_result import SearchResult


class UnifiedSearchService:
    def __init__(self) -> None:
        self.catalog = CatalogService()
        self.insider = InsiderService()
        self.cache = OfficialCacheService()

    def _search_iso(self, version: str, architectures) -> list[SearchResult]:
        """26H2 / 25H2 gibi sürüm adı: iki kaynak birlikte listelenir, kullanıcı birini seçer.

        1) Microsoft'un resmi ISO'su: Microsoft yalnızca o an sunduğu sürümü verir; gerçek bağlantı ISO Merkezi'nde,
           dil ve mimari seçildikten sonra istenir (burada ağ isteği yapılmaz, reddedilme riski olmasın).
        2) UUP: Sürüm Takibi verisindeki en son yayın build'i; ISO UUP kaynaklarından hazırlanır.
        """
        archs = [a for a in (architectures or ("x64",)) if a in ("x64", "ARM64")] or ["x64"]

        records, _last_update, _fetched = BuildTrackerService.load_cache()
        record = latest_build_for_version(records, version)
        if record is None:
            try:
                records, _last_update = BuildTrackerService().fetch()
            except Exception:
                records = []
            record = latest_build_for_version(records, version)

        # Tek sonuç: indirme sırasında önce Microsoft denenir, sunmuyorsa/reddederse UUP devreye girer.
        results: list[SearchResult] = []
        for arch in archs:
            build_note = f" - UUP yedeği: {record.build_number}" if record is not None else ""
            results.append(SearchResult(
                update_id=f"ms-iso:{version}:{arch}",
                title=f"Windows 11, version {version} ISO {arch} - Microsoft'tan, yoksa UUP ile{build_note}",
                product="Windows 11",
                classification="ISO",
                last_updated=(record.release_date or "") if record is not None else "",
                version=version,
                size="—",
                source="Microsoft ISO",
                source_url=PAGE_URLS[arch],
                channel="Resmi ISO",
            ))
        return results

    def search(self, query: str, architectures=None):
        query = query.strip()
        if not query:
            return []

        version = parse_version_query(query)
        if version:
            return self._search_iso(version, architectures)

        is_build = re.fullmatch(
            r"\d{4,5}\.\d{1,5}",
            query,
        ) is not None
        is_kb = re.fullmatch(
            r"KB\s*\d+|\d{7,8}",
            query,
            re.I,
        ) is not None

        # Exact official cache gives an immediate result when live sources
        # are temporarily blocked by DNS/network conditions.
        cached_results = self.cache.search(query)
        if cached_results:
            return cached_results

        # For build numbers, Insider source is more relevant than Catalog.
        if is_build:
            try:
                insider_results = self.insider.search_build(query)
                if insider_results:
                    return insider_results
            except Exception:
                pass

        # Catalog remains the primary source for KB packages and most
        # retail cumulative update build searches.
        try:
            catalog_results = self.catalog.search(query)
            if catalog_results:
                return catalog_results
        except ConnectionError as exc:
            if is_build:
                raise RuntimeError(
                    "Bu build yerel resmî önbellekte bulunamadı ve "
                    "Microsoft'un canlı kaynaklarına şu anda erişilemiyor. "
                    "İnternet/DNS bağlantınızı kontrol edip tekrar deneyin."
                ) from exc
            raise RuntimeError(
                "Microsoft Update Catalog'a şu anda erişilemiyor. "
                "İnternet veya DNS bağlantınızı kontrol edip tekrar deneyin."
            ) from exc

        # One last live Insider check for generic build-like searches.
        if is_build:
            try:
                return self.insider.search_build(query)
            except Exception:
                return []

        return []
