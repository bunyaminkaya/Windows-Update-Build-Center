import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import ui.pages.usb_install_page as page_mod
from services.usb_media_service import UsbDrive, UsbMediaService


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, monkeypatch, tmp_path):
    monkeypatch.setattr(UsbMediaService, "is_supported_platform", staticmethod(lambda: False))
    p = page_mod.UsbInstallPage()
    iso = tmp_path / "Win11_x64.iso"
    iso.write_bytes(b"x" * 10)
    p.iso_path.setText(str(iso))
    p._drives = [UsbDrive(3, "Test USB", 16 * 1024**3, "E")]
    p.usb_combo.clear()
    p.usb_combo.addItem("Disk 3")
    messages = []
    monkeypatch.setattr(page_mod, "show_information", lambda *a, **k: messages.append(a[2]))
    monkeypatch.setattr(page_mod, "show_error", lambda *a, **k: messages.append(a[2]))
    monkeypatch.setattr(page_mod, "ask_confirmation", lambda *a, **k: True)
    p._messages = messages
    return p


def _capture(monkeypatch):
    calls = {}

    def fake(iso, drive, scheme, fs, label, bypass, **kw):
        calls.update(bypass=bypass, **kw)
        return "E:\\"

    monkeypatch.setattr(UsbMediaService, "create_media", staticmethod(fake))
    return calls


def _wait(page):
    for _ in range(200):
        QApplication.processEvents()
        if page._thread is None:
            return
        time.sleep(0.01)


def test_options_are_passed_to_service(page, monkeypatch):
    calls = _capture(monkeypatch)
    monkeypatch.setattr(page_mod, "show_success", lambda *a, **k: None)
    page.bypass_checks.setChecked(True)
    page.use_local_account.setChecked(True)
    page.local_account_name.setText(" Ali ")
    page.use_computer_name.setChecked(True)
    page.computer_name.setText("PC-01")
    page.skip_privacy.setChecked(True)
    page.verify_sha256.setChecked(True)
    page.expected_sha256.setText("ab" * 32)
    page.start_creation()
    _wait(page)
    c = calls["customization"]
    assert (c.bypass_hardware, c.local_account, c.computer_name, c.skip_privacy) == (True, "Ali", "PC-01", True)
    assert calls["verify_sha256"] is True
    assert calls["expected_sha256"] == "AB" * 32


def test_invalid_values_block_start(page, monkeypatch):
    calls = _capture(monkeypatch)
    page.use_computer_name.setChecked(True)
    page.computer_name.setText("Çalışma")
    page.start_creation()
    assert page._thread is None and not calls
    assert page._messages and "Türkçe karakter" in page._messages[-1]

    page.use_computer_name.setChecked(False)
    page.verify_sha256.setChecked(True)
    page.expected_sha256.setText("123")
    page.start_creation()
    assert page._thread is None and not calls
    assert "64 haneli" in page._messages[-1]


def test_empty_name_with_option_on_is_rejected(page, monkeypatch):
    calls = _capture(monkeypatch)
    page.use_local_account.setChecked(True)
    page.start_creation()
    assert page._thread is None and not calls


def test_inputs_follow_checkboxes(page):
    assert not page.local_account_name.isEnabled()
    page.use_local_account.setChecked(True)
    assert page.local_account_name.isEnabled()
    page._set_options_enabled(False)
    assert not page.local_account_name.isEnabled() and not page.skip_privacy.isEnabled()
    page._set_options_enabled(True)
    assert page.local_account_name.isEnabled() and not page.computer_name.isEnabled()
