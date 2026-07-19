from __future__ import annotations

import re

from services.catalog_service import CatalogService
from services.insider_service import InsiderService
from services.official_cache_service import OfficialCacheService


class UnifiedSearchService:
    def __init__(self) -> None:
        self.catalog = CatalogService()
        self.insider = InsiderService()
        self.cache = OfficialCacheService()

    def search(self, query: str):
        query = query.strip()
        if not query:
            return []

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
