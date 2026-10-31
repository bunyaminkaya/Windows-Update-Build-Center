import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace as NS

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from services import iso_batch_view as V
from services.settings_service import SettingsService, auto_create_iso_enabled


def job(status, jid="1", **meta):
    base = {"build": "29695.1001", "architecture": "x64", "language": "tr-tr"}
    base.update(meta)
    return NS(id=jid, status=status, batch_meta=base)


# ---------------- görünüm mantığı ----------------
def test_downloading_button_disabled_and_progress():
    jobs = [job("Tamamlandı", "1"), job("İndiriliyor", "2"), job("Kuyrukta", "3")]
    v = V.compute_view("b", jobs, None, True)
    assert v.phase == V.DOWNLOADING and not v.primary_enabled and (v.done, v.total) == (1, 3)
    assert "1/3" in v.text and "kendiliğinden" in v.text
    assert "etkinleşecek" in V.compute_view("b", jobs, None, False).text


def test_failed_downloads_offer_retry_instead_of_silence():
    jobs = [job("Tamamlandı", "1"), job("Hata", "2"), job("İptal edildi", "3")]
    v = V.compute_view("b", jobs, None, True)
    assert v.phase == V.DOWNLOAD_PROBLEM and v.primary_action == "retry_downloads" and v.primary_enabled
    assert v.failed_ids == ["2", "3"] and "2 dosya" in v.text


def test_all_downloaded_auto_vs_manual():
    jobs = [job("Tamamlandı", "1"), job("Tamamlandı", "2")]
    auto = V.compute_view("b", jobs, None, True)
    assert auto.phase == V.STARTING and not auto.primary_enabled
    manual = V.compute_view("b", jobs, {"status": V.READY_STATUS}, False)
    assert manual.phase == V.READY and manual.primary_action == "start" and manual.primary_enabled
    assert manual.primary_label == "ISO'yu Şimdi Oluştur" and "butona basın" in manual.text
    # ayar kapalıyken durum kaydı olmasa da düğme etkin olmalı
    assert V.compute_view("b", jobs, None, False).phase == V.READY


@pytest.mark.parametrize("status,phase", [
    ("Hazırlanıyor", V.BUILDING_PHASE), ("Dönüştürülüyor", V.BUILDING_PHASE), ("Doğrulanıyor", V.BUILDING_PHASE),
    ("Hata", V.BUILD_FAILED), ("İptal", V.BUILD_CANCELLED), ("Hazır", V.BUILT),
])
def test_iso_states(status, phase):
    v = V.compute_view("b", [job("Tamamlandı")], {"status": status, "iso_path": r"C:\x\Win.iso"}, True)
    assert v.phase == phase
    if phase == V.BUILDING_PHASE:
        assert not v.primary_enabled and "cancel" in v.actions
    if phase == V.BUILT:
        assert v.primary_action == "open_folder" and "Win.iso" in v.text
    if phase in (V.BUILD_FAILED, V.BUILD_CANCELLED):
        assert v.primary_action == "retry_build" and v.primary_enabled


# ---------------- ayar ----------------
def test_auto_create_defaults_to_on(monkeypatch):
    monkeypatch.setattr(SettingsService, "load", staticmethod(lambda: {"uup_iso": {}}))
    assert auto_create_iso_enabled() is True
    monkeypatch.setattr(SettingsService, "load", staticmethod(lambda: {"uup_iso": {"auto_create_iso": False}}))
    assert auto_create_iso_enabled() is False
    from services.settings_service import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["uup_iso"]["auto_create_iso"] is True


# ---------------- panel ----------------
class FakeDM(QObject):
    job_added = Signal(str); job_updated = Signal(str)
    def __init__(self, jobs): super().__init__(); self.jobs = jobs; self.retried = []
    def all_jobs(self): return self.jobs
    def retry_many(self, ids): self.retried += list(ids)


class FakeISO(QObject):
    queue_changed = Signal(); status_changed = Signal(str, str); build_started = Signal(str)
    build_finished = Signal(str, str, str); build_failed = Signal(str, str); build_cancelled = Signal(str, str)
    def __init__(self): super().__init__(); self.states = {}; self.started = []; self.retried = []; self.cancelled = []
    def all_states(self): return self.states
    def state(self, b): return dict(self.states.get(b, {}))
    def start_build(self, b, meta): self.started.append((b, meta))
    def retry_build(self, b): self.retried.append(b)
    def cancel_build(self, b): self.cancelled.append(b)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _jobs(*statuses):
    out = []
    for i, st in enumerate(statuses):
        j = job(st, str(i), uup_dir="U", project_dir="P")
        j.batch_id, j.batch_kind = "B1", "uup_iso"
        out.append(j)
    return out


def _panel(qapp, jobs, monkeypatch, auto=True):
    import ui.widgets.iso_build_panel as mod
    monkeypatch.setattr(mod, "auto_create_iso_enabled", lambda: auto)
    dm, iso = FakeDM(jobs), FakeISO()
    return mod.IsoBuildPanel(manager=dm, iso_manager=iso), dm, iso


def _close(qapp, panel):
    panel.close(); panel.deleteLater(); qapp.sendPostedEvents(None, 0); qapp.processEvents()


def test_panel_hidden_without_uup_jobs(qapp, monkeypatch):
    panel, _dm, _iso = _panel(qapp, [], monkeypatch)
    try:
        assert panel.isHidden()
    finally:
        _close(qapp, panel)


def test_panel_manual_start_button(qapp, monkeypatch):
    panel, dm, iso = _panel(qapp, _jobs("Tamamlandı", "Tamamlandı"), monkeypatch, auto=False)
    try:
        iso.states["B1"] = {"status": V.READY_STATUS}
        panel.refresh()
        card = panel._cards["B1"]
        assert card.primary.isEnabled() and card.primary.text() == "ISO'yu Şimdi Oluştur"
        card.primary.click()
        assert iso.started and iso.started[0][0] == "B1" and iso.started[0][1]["uup_dir"] == "U"
    finally:
        _close(qapp, panel)


def test_panel_retry_failed_downloads_and_retry_build(qapp, monkeypatch):
    panel, dm, iso = _panel(qapp, _jobs("Tamamlandı", "Hata", "İptal edildi"), monkeypatch)
    try:
        card = panel._cards["B1"]
        assert card.primary.text() == "Başarısızları Yeniden Dene"
        card.primary.click()
        assert dm.retried == ["1", "2"]
        dm.jobs = _jobs("Tamamlandı", "Tamamlandı")
        iso.states["B1"] = {"status": "Hata"}
        panel.refresh()
        card.primary.click()
        assert iso.retried == ["B1"]
    finally:
        _close(qapp, panel)


def test_panel_building_disables_button_and_allows_cancel(qapp, monkeypatch):
    panel, dm, iso = _panel(qapp, _jobs("Tamamlandı"), monkeypatch)
    try:
        iso.states["B1"] = {"status": "Dönüştürülüyor"}
        panel.refresh()
        card = panel._cards["B1"]
        assert not card.primary.isEnabled()
        card.extra["cancel"].click()
        assert iso.cancelled == ["B1"]
    finally:
        _close(qapp, panel)


def test_batch_completion_respects_setting(monkeypatch):
    import ui.main_window as mw
    calls = []

    class FakeMgr:
        def start_build(self, b, m): calls.append(("start", b))
        def mark_ready(self, b, m): calls.append(("ready", b))
        def state(self, b): return {}

    monkeypatch.setattr(mw.IsoBuildManager, "instance", staticmethod(lambda: FakeMgr()))
    meta = {"batch_kind": "uup_iso", "project_dir": "P", "uup_dir": "U"}
    monkeypatch.setattr(mw, "auto_create_iso_enabled", lambda: True)
    mw.MainWindow._on_download_batch_completed(None, "b1", meta)
    monkeypatch.setattr(mw, "auto_create_iso_enabled", lambda: False)
    mw.MainWindow._on_download_batch_completed(None, "b2", meta)
    mw.MainWindow._on_download_batch_completed(None, "b3", {"batch_kind": "other"})
    assert calls == [("start", "b1"), ("ready", "b2")]


def test_mark_ready_keeps_finished_iso_and_sets_state(tmp_path, monkeypatch):
    from services.iso_build_manager import IsoBuildManager
    mgr = IsoBuildManager.__new__(IsoBuildManager)
    QObject.__init__(mgr)
    import threading
    mgr._threads, mgr._queue, mgr._states, mgr._lock = {}, [], {}, threading.RLock()
    mgr._state_file = tmp_path / "iso.json"
    mgr.mark_ready("b", {"uup_dir": "U"})
    assert mgr.state("b")["status"] == IsoBuildManager.READY_STATUS and mgr.state("b")["metadata"]["uup_dir"] == "U"
    mgr._states["done"] = {"status": "Hazır", "iso_path": "x"}
    mgr.mark_ready("done", {})
    assert mgr.state("done")["status"] == "Hazır"
    from services.iso_build_manager import IsoBuildWorker
    assert IsoBuildWorker.required_space_for_size(0) == 24 * 1024 ** 3
    assert IsoBuildWorker.required_space_for_size(10 * 1024 ** 3) > 24 * 1024 ** 3 + 8 * 1024 ** 3 - 1


def test_settings_page_saves_auto_create_iso(qapp, monkeypatch):
    from ui.pages import settings_page as sp
    saved = {}
    monkeypatch.setattr(SettingsService, "save", staticmethod(lambda data: saved.update(data) or data), raising=False)
    monkeypatch.setattr(sp, "show_information", lambda *a, **k: None)   # modal kutu testi bloklamasın
    monkeypatch.setattr(sp.DownloadManager, "instance", staticmethod(lambda: type("M", (), {"apply_settings": lambda s, d: None})()))
    page = sp.SettingsPage()
    try:
        assert page.auto_create_iso.isChecked()          # varsayılan açık
        page.auto_create_iso.setChecked(False)
        page.save_settings()
        assert saved.get("uup_iso", {}).get("auto_create_iso") is False
    finally:
        page.close(); page.deleteLater(); qapp.processEvents()


def test_iso_panel_sits_below_download_operations(qapp):
    from ui.pages.download_manager_page import DownloadManagerPage
    page = DownloadManagerPage()
    try:
        lay = page.layout()
        order = [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]
        names = [w.objectName() for w in order]
        assert order.index(page.iso_panel) == len(order) - 1            # en altta
        assert names.index("dmCard") < order.index(page.iso_panel)       # indirme kartları üstte
    finally:
        page.close(); page.deleteLater(); qapp.processEvents()
