import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

import ui.pages.iso_center_page as mod
from services import ms_iso_service as ms
from services.build_tracker_service import BuildTrackerRecord, BuildTrackerService
from services.settings_service import SettingsService

X64_URL = "https://software.download.prss.microsoft.com/dbazure/Win11_25H2_Turkish_x64.iso?t=abc"
PAGE = '<select id="product-edition"><option value="">-</option><option value="3321">Win11</option></select>'


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()
    app.processEvents()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    store = {"iso_center": {"scan_folders": []}, "downloads": {"default_folder": str(tmp_path)}}
    monkeypatch.setattr(SettingsService, "load", staticmethod(lambda: store))
    monkeypatch.setattr(SettingsService, "update_value", staticmethod(lambda sec, key, val: None))
    monkeypatch.setattr(mod.IsoCenterPage, "refresh_scan", lambda self: None)  # disk taraması yok
    ms.MicrosoftIsoService._blocked_until = 0.0
    monkeypatch.setattr(ms.MicrosoftIsoService, "remember_rejection", staticmethod(lambda: None))
    yield
    ms.MicrosoftIsoService._blocked_until = 0.0


class FakeUup(QObject):
    auto_finished = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.requests = []

    def request_auto_download(self, *args):
        self.requests.append(args)


class Host(QWidget):
    def __init__(self, page_factory):
        super().__init__()
        self.uup = FakeUup()
        self.shown = []
        self.page = page_factory(self)

    def page_by_name(self, name):
        return self.uup if name == "UUP ISO Oluşturucu" else None

    def show_page_by_name(self, name):
        self.shown.append(name)
        return True


def _make(qapp):
    host = Host(lambda h: mod.IsoCenterPage(h))
    return host, host.page


def _destroy(qapp, host):
    host.page.shutdown()
    host.close(); host.deleteLater()
    qapp.sendPostedEvents(None, 0); qapp.processEvents()


def _wait(cond, ms_=5000):
    import time
    end = time.time() + ms_ / 1000
    while time.time() < end and not cond():
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return cond()


def test_context_fills_panel_and_source_switch_swaps_value(qapp):
    host, page = _make(qapp)
    try:
        page.set_download_context("microsoft", version="26H2", build="26300.9818", architecture="ARM64", language="English (United States)")
        assert page.dl_source.currentIndex() == page.SOURCE_MS
        assert page.dl_target.text() == "26H2" and page.dl_arch.currentText() == "ARM64"
        assert page.dl_lang.currentText() == "English (United States)"
        assert not page.dl_edition.isEnabled()
        page.dl_source.setCurrentIndex(page.SOURCE_UUP)
        assert page.dl_target.text() == "26300.9818" and page.dl_edition.isEnabled()
        page.dl_target.setText("26300.1")  # elle yazılan korunur
        page.dl_source.setCurrentIndex(page.SOURCE_MS)
        assert page.dl_target.text() == "26300.1"
    finally:
        _destroy(qapp, host)


def test_uup_start_sends_request_with_selected_options(qapp):
    host, page = _make(qapp)
    try:
        page.set_download_context("uup", version="26H2", build="26300.9818", architecture="x64", language="Türkçe")
        page.dl_edition.setCurrentIndex(page.dl_edition.findText("Windows 11 Pro"))
        page.dl_button.click()
        assert len(host.uup.requests) == 1
        build, title, channel, source, arch, lang, edition = host.uup.requests[0]
        assert (build, arch, lang, edition) == ("26300.9818", "x64", "Türkçe", "Windows 11 Pro")
        assert not page.dl_button.isEnabled()
        host.uup.auto_finished.emit(True, "6 UUP dosyası indirme kuyruğuna eklendi.")
        assert page.dl_button.isEnabled() and "kuyruğuna" in page.dl_status.text()
        assert host.shown == ["İndirme Yöneticisi"]
        host.uup.auto_finished.emit(False, "başka")  # beklenmeyen sinyal yok sayılır
    finally:
        _destroy(qapp, host)


def test_uup_failure_is_reported_without_navigation(qapp):
    host, page = _make(qapp)
    try:
        page.set_download_context("uup", build="26300.9818")
        page.dl_button.click()
        host.uup.auto_finished.emit(False, "Bu build için seçtiğiniz dil UUP'de bulunamadı.")
        assert "dil" in page.dl_status.text() and host.shown == []
        assert page.dl_button.isEnabled()
    finally:
        _destroy(qapp, host)


def test_uup_resolves_version_name_to_latest_build(qapp, monkeypatch):
    host, page = _make(qapp)
    try:
        rec = BuildTrackerRecord(build_number="26300.9818", windows_version="26H2", channel="Retail")
        monkeypatch.setattr(BuildTrackerService, "load_cache", staticmethod(lambda: ([rec], "", "")))
        page.set_download_context("uup", version="26H2")
        page.dl_button.click()
        assert host.uup.requests[0][0] == "26300.9818"
    finally:
        _destroy(qapp, host)


def test_uup_without_resolvable_build_warns(qapp, monkeypatch):
    host, page = _make(qapp)
    warned = []
    monkeypatch.setattr(mod, "show_warning", lambda *a, **k: warned.append(a))
    try:
        monkeypatch.setattr(BuildTrackerService, "load_cache", staticmethod(lambda: ([], "", "")))
        monkeypatch.setattr(BuildTrackerService, "fetch", lambda self: (_ for _ in ()).throw(RuntimeError("offline")))
        page.set_download_context("uup", version="26H2")
        page.dl_button.click()
        assert warned and host.uup.requests == []
        assert page.dl_button.isEnabled()
    finally:
        _destroy(qapp, host)


def _patch_microsoft(monkeypatch, offer=None, error=None):
    class FakeWorker(mod.MsIsoLinkWorker):
        def run(self):
            if error:
                self.failed.emit(error[0], error[1])
            else:
                self.finished.emit(offer)
    monkeypatch.setattr(mod, "MsIsoLinkWorker", FakeWorker)


def _offer(version="25H2"):
    return ms.IsoOffer(version=version, architecture="x64", language="Türkçe",
                       filename=f"Win11_{version}_Turkish_x64.iso", url=X64_URL, page_url=ms.PAGE_URLS["x64"])


def test_microsoft_matching_version_goes_to_download_manager(qapp, monkeypatch, tmp_path):
    host, page = _make(qapp)
    added = []
    try:
        _patch_microsoft(monkeypatch, offer=_offer("25H2"))
        monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / "Win11.iso"), "")))
        monkeypatch.setattr(mod.DownloadManager, "instance", staticmethod(lambda: type("M", (), {"add_download": lambda s, p, t: added.append((p, t))})()))
        page.set_download_context("microsoft", version="25H2", language="Türkçe")
        page.dl_button.click()
        assert _wait(lambda: bool(added))
        package, target = added[0]
        assert package.direct_url == X64_URL and package.file_type == "ISO" and package.source == "Microsoft ISO"
        assert target.endswith("Win11.iso")
        assert page.dl_button.isEnabled() and "kuyruğuna" in page.dl_status.text()
    finally:
        _destroy(qapp, host)


def test_microsoft_other_version_asks_before_downloading(qapp, monkeypatch, tmp_path):
    host, page = _make(qapp)
    added, asked = [], []
    try:
        _patch_microsoft(monkeypatch, offer=_offer("25H2"))
        monkeypatch.setattr(mod, "ask_confirmation", lambda *a, **k: asked.append(a[2]) or False)
        monkeypatch.setattr(mod.DownloadManager, "instance", staticmethod(lambda: type("M", (), {"add_download": lambda s, p, t: added.append(p)})()))
        page.set_download_context("microsoft", version="26H2", language="Türkçe")
        page.dl_button.click()
        assert _wait(lambda: bool(asked))
        assert "25H2" in asked[0] and "26H2" in asked[0]
        assert added == [] and page.dl_button.isEnabled()
        assert "UUP" in page.dl_status.text()
    finally:
        _destroy(qapp, host)


def test_microsoft_rejection_switches_to_uup_and_starts_it(qapp, monkeypatch):
    host, page = _make(qapp)
    try:
        _patch_microsoft(monkeypatch, error=("Sentinel marked this request as rejected.", True))
        page.set_download_context("microsoft", version="26H2", build="26300.9818", language="Türkçe")
        page.dl_button.click()
        assert _wait(lambda: bool(host.uup.requests))
        assert page.dl_source.currentIndex() == page.SOURCE_UUP
        assert host.uup.requests[0][0] == "26300.9818"
    finally:
        _destroy(qapp, host)


def test_auto_uses_microsoft_when_it_offers_the_version(qapp, monkeypatch, tmp_path):
    host, page = _make(qapp)
    added = []
    try:
        _patch_microsoft(monkeypatch, offer=_offer("25H2"))
        monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / "w.iso"), "")))
        monkeypatch.setattr(mod.DownloadManager, "instance", staticmethod(lambda: type("M", (), {"add_download": lambda s, p, t: added.append(p)})()))
        page.set_download_context("auto", version="25H2", build="26200.1", language="Türkçe")
        assert page.dl_source.currentIndex() == page.SOURCE_AUTO
        page.dl_button.click()
        assert _wait(lambda: bool(added))
        assert added[0].source == "Microsoft ISO" and host.uup.requests == []
    finally:
        _destroy(qapp, host)


def test_auto_falls_back_to_uup_when_microsoft_has_other_version(qapp, monkeypatch):
    host, page = _make(qapp)
    asked = []
    try:
        _patch_microsoft(monkeypatch, offer=_offer("25H2"))
        monkeypatch.setattr(mod, "ask_confirmation", lambda *a, **k: asked.append(a) or True)
        page.set_download_context("auto", version="26H2", build="26300.9818", language="Türkçe")
        page.dl_button.click()
        assert _wait(lambda: bool(host.uup.requests))
        assert host.uup.requests[0][0] == "26300.9818" and asked == []  # soru sorulmaz
        assert page.dl_source.currentIndex() == page.SOURCE_UUP
    finally:
        _destroy(qapp, host)


def test_auto_falls_back_to_uup_when_microsoft_rejects(qapp, monkeypatch):
    host, page = _make(qapp)
    try:
        _patch_microsoft(monkeypatch, error=("Sentinel marked this request as rejected.", True))
        page.set_download_context("auto", version="26H2", build="26300.9818", language="Türkçe")
        page.dl_button.click()
        assert _wait(lambda: bool(host.uup.requests))
        assert host.uup.requests[0][0] == "26300.9818"
    finally:
        _destroy(qapp, host)


def test_auto_skips_microsoft_after_recent_rejection(qapp, monkeypatch):
    host, page = _make(qapp)
    try:
        monkeypatch.setattr(ms.MicrosoftIsoService, "rejected_recently", staticmethod(lambda: True))
        _patch_microsoft(monkeypatch, error=("hiç çağrılmamalı", False))
        page.set_download_context("auto", version="26H2", build="26300.9818", language="Türkçe")
        page.dl_button.click()
        assert host.uup.requests and host.uup.requests[0][0] == "26300.9818"
    finally:
        _destroy(qapp, host)


def test_microsoft_needs_version_name(qapp, monkeypatch):
    host, page = _make(qapp)
    warned = []
    monkeypatch.setattr(mod, "show_warning", lambda *a, **k: warned.append(a))
    try:
        page.set_download_context("microsoft")
        page.dl_target.setText("26300.9818")
        page.dl_button.click()
        assert warned and page.dl_button.isEnabled()
    finally:
        _destroy(qapp, host)
