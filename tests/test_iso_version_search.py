import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from services import iso_version_service as ivs
from services.build_tracker_service import BuildTrackerRecord, BuildTrackerService
from services.unified_search_service import UnifiedSearchService


def rec(build, version="26H2", channel="Retail", kb="KB1", date="2026-10-13"):
    return BuildTrackerRecord(build_number=build, kb_number=kb, windows_version=version, channel=channel, release_date=date)


@pytest.mark.parametrize("text,expected", [
    ("26H2", "26H2"), ("25h2", "25H2"), ("Windows 11 25H2", "25H2"), ("26h1 iso", "26H1"),
    ("version 24H2", "24H2"), ("sürüm 25H2 iso indir", "25H2"),
])
def test_version_queries(text, expected):
    assert ivs.parse_version_query(text) == expected


@pytest.mark.parametrize("text", ["26300.9711", "KB5127648", "Windows 11 Pro 26H2 26300.9711", "", "iso", "2H62"])
def test_non_version_queries(text):
    assert ivs.parse_version_query(text) is None


def test_latest_build_prefers_retail_then_highest_build():
    records = [
        rec("26300.9278", channel="Release Preview"),
        rec("26300.9711", channel="Retail"),
        rec("26300.9500", channel="Retail"),
        rec("26300.10000", channel="Beta"),
        rec("26300.9900", version="25H2", channel="Retail"),
    ]
    assert ivs.latest_build_for_version(records, "26H2").build_number == "26300.9711"
    assert ivs.latest_build_for_version(records, "25h2").build_number == "26300.9900"


def test_latest_build_compares_numbers_not_strings():
    records = [rec("26300.999"), rec("26300.10001")]
    assert ivs.latest_build_for_version(records, "26H2").build_number == "26300.10001"


def test_latest_build_falls_back_when_no_retail():
    records = [rec("26300.1", channel="Dev"), rec("26300.2", channel="Release Preview")]
    assert ivs.latest_build_for_version(records, "26H2").build_number == "26300.2"
    assert ivs.latest_build_for_version([rec("1.1", channel="Dev")], "25H2") is None


def test_search_returns_single_iso_row_per_architecture_without_network(monkeypatch):
    import services.unified_search_service as us
    monkeypatch.setattr(BuildTrackerService, "load_cache", staticmethod(lambda: ([rec("26300.9711")], "x", "y")))

    def no_network(*a, **k):
        raise AssertionError("Arama sırasında Microsoft ISO servisine gidilmemeli")
    monkeypatch.setattr(us.requests if hasattr(us, "requests") else __import__("requests"), "get", no_network)
    results = UnifiedSearchService().search("26h2", ("x64", "ARM64"))
    assert [(r.source, r.architecture) for r in results] == [("Microsoft ISO", "x64"), ("Microsoft ISO", "ARM64")]
    assert "26300.9711" in results[0].title and results[0].version == "26H2"  # UUP yedeği için build başlıkta
    assert all("KB" not in r.title for r in results)  # KB görünürse arayüz MSU paketi aramaya kalkar


def test_search_still_offers_microsoft_when_tracker_is_empty(monkeypatch):
    monkeypatch.setattr(BuildTrackerService, "load_cache", staticmethod(lambda: ([], "", "")))

    def boom(self):
        raise RuntimeError("offline")
    monkeypatch.setattr(BuildTrackerService, "fetch", boom)
    results = UnifiedSearchService().search("26H2", ("x64",))
    assert [r.source for r in results] == ["Microsoft ISO"]


def test_build_and_kb_queries_do_not_use_version_path(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("sürüm yolu çağrılmamalı")
    monkeypatch.setattr(BuildTrackerService, "load_cache", staticmethod(boom))
    svc = UnifiedSearchService()
    monkeypatch.setattr(svc.cache, "search", lambda q: ["cached"])
    assert svc.search("26300.9711") == ["cached"]
    assert svc.search("KB5127648") == ["cached"]


# ---- arayüz ----
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()
    app.processEvents()


def _make_host_and_page(qapp):
    from PySide6.QtWidgets import QWidget
    from ui.pages.home_page import HomePage

    class FakeIso:
        def __init__(self):
            self.calls = []

        def set_download_context(self, source, version="", build="", architecture="x64", language=None):
            self.calls.append((source, version, build, architecture, language))

    class Host(QWidget):
        def __init__(self):
            super().__init__()
            self.iso = FakeIso()
            self.shown = []

        def page_by_name(self, name):
            return self.iso if name == "ISO Merkezi" else None

        def show_page_by_name(self, name):
            self.shown.append(name)
            return True

    host = Host()
    return host, HomePage(host)


def _destroy(qapp, host):
    host.close()
    host.deleteLater()
    qapp.sendPostedEvents(None, 0)
    qapp.processEvents()


def _select_first(qapp, page, rows, index=0):
    page._last_results = rows
    page._fill_table(rows)
    page.results_table.selectRow(index)
    qapp.processEvents()


@pytest.mark.parametrize("row_index,expected", [
    (0, ("auto", "26H2", "26300.9711", "ARM64", "English (United States)")),
])
def test_microsoft_download_button_opens_iso_center_with_selection(qapp, monkeypatch, row_index, expected):
    host, page = _make_host_and_page(qapp)
    try:
        monkeypatch.setattr(BuildTrackerService, "load_cache", staticmethod(lambda: ([rec("26300.9711")], "x", "y")))
        rows = UnifiedSearchService().search("26H2", ("ARM64",))
        page.language_filter.setCurrentIndex(page.language_filter.findText("Dil: English (United States)"))
        _select_first(qapp, page, rows, row_index)

        assert page.open_package_button.isEnabled()
        assert page.find_packages_button.text() == "ISO Seçenekleri"
        page.open_package_button.click()
        assert host.iso.calls == [expected]
        assert host.shown == ["ISO Merkezi"]

        host.shown.clear()
        page.find_packages_button.click()
        assert host.shown == ["ISO Merkezi"]
    finally:
        _destroy(qapp, host)


def test_card_text_differs_per_source(qapp, monkeypatch):
    host, page = _make_host_and_page(qapp)
    try:
        monkeypatch.setattr(BuildTrackerService, "load_cache", staticmethod(lambda: ([rec("26300.9711")], "x", "y")))
        rows = UnifiedSearchService().search("26H2", ("x64",))
        _select_first(qapp, page, rows, 0)
        assert "Microsoft" in page.package_card_title.text() and "UUP" in page.package_card_title.text()
        assert "UUP" in page.package_card_desc.text()
    finally:
        _destroy(qapp, host)


def test_regular_update_rows_keep_old_behavior(qapp):
    from services.search_result import SearchResult
    host, page = _make_host_and_page(qapp)
    try:
        msu = SearchResult(update_id="1", title="2026-x64 Windows 11, version 26H2 (KB5127648) (26300.9711)", source="Microsoft Update Catalog")
        _select_first(qapp, page, [msu])
        assert not page.open_package_button.isEnabled()  # paket aranmadan indirilemez
        assert page.find_packages_button.text() == "Paketleri Bul"
        assert "değildir" in page.package_card_desc.text()
    finally:
        _destroy(qapp, host)
