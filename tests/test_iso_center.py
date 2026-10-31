import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

import ui.pages.iso_center_page as mod
from services.settings_service import SettingsService


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_settings(monkeypatch):
    store = {"iso_center": {"scan_folders": []}}
    monkeypatch.setattr(SettingsService, "load", staticmethod(lambda: store))
    monkeypatch.setattr(SettingsService, "update_value",
                        staticmethod(lambda sec, key, val: store.setdefault(sec, {}).__setitem__(key, val)))
    return store


def _wait(cond, app, ms=5000):
    import time
    end = time.time() + ms / 1000
    while time.time() < end and not cond():
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return cond()


def test_scan_worker_finds_isos(app, tmp_path):
    (tmp_path / "a.iso").write_bytes(b"1")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.ISO").write_bytes(b"2")
    (tmp_path / "x.txt").write_bytes(b"3")
    got = []
    w = mod.ScanWorker([tmp_path])
    w.found.connect(got.append)
    w.start()
    assert _wait(lambda: not w.isRunning(), app)
    QCoreApplication.processEvents()
    names = sorted(p.name.lower() for p in got[0])
    assert names == ["a.iso", "b.iso"]


def test_page_scans_lazily_and_sends_to_usb(app, tmp_path, isolated_settings, monkeypatch):
    iso = tmp_path / "Win11_26100.1_x64_tr-tr.iso"
    iso.write_bytes(b"x" * 20)
    isolated_settings["iso_center"]["scan_folders"] = [str(tmp_path)]
    page = mod.IsoCenterPage()
    assert not page._scanned_once
    page.show()
    assert _wait(lambda: len(page.records) == 1, app)
    assert page.records[0].architecture == "x64"
    sent = []
    page.send_to_usb.connect(sent.append)
    page.table.selectRow(0)
    page._send_to_usb()
    assert sent == [str(iso)]
    page.shutdown()
    page.close()


def test_legacy_scan_folders_migrated(app, isolated_settings):
    isolated_settings["iso_scan_folders"] = ["C:/eski"]
    page = mod.IsoCenterPage()
    assert page._scan_folders() == ["C:/eski"]
    assert isolated_settings["iso_center"]["scan_folders"] == ["C:/eski"]
    page.shutdown()


def test_settings_save_keeps_iso_center():
    import inspect
    import ui.pages.settings_page as sp
    assert '"iso_center"' in inspect.getsource(sp)


def test_usb_set_iso_path(app, tmp_path, monkeypatch):
    import ui.pages.usb_install_page as up
    from services.usb_media_service import UsbMediaService
    monkeypatch.setattr(UsbMediaService, "is_supported_platform", staticmethod(lambda: False))
    p = up.UsbInstallPage()
    iso = tmp_path / "Win.iso"
    iso.write_bytes(b"x" * 10)
    monkeypatch.setattr(UsbMediaService, "validate_iso", staticmethod(lambda path: None))
    assert p.set_iso_path(iso) is True
    assert p.iso_path.text() == str(iso)
    monkeypatch.setattr(UsbMediaService, "validate_iso", staticmethod(lambda path: (_ for _ in ()).throw(ValueError("kötü"))))
    monkeypatch.setattr(up, "show_error", lambda *a, **k: None)
    assert p.set_iso_path(iso) is False
