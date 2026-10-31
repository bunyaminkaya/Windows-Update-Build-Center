import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from services.driver_backup_service import DriverBackupService as S, DriverInfo
from ui.widgets.empty_state import EmptyState


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _drv(name, size=0):
    return DriverInfo(name, name, size_bytes=size)


def test_parse_size_map():
    assert S.parse_size_map('{"OEM1.inf": 1000, "oem2.inf": "2048", "oem3.inf": 0, "oem4.inf": null}') == {"oem1.inf": 1000, "oem2.inf": 2048}
    assert S.parse_size_map("") == {}
    assert S.parse_size_map("[1,2]") == {}


def test_estimate_total_uses_median_for_unknown():
    total, known = S.estimate_total([_drv("a", 100), _drv("b", 300), _drv("c", 200), _drv("d")])
    assert known == 3 and total == 600 + 200  # bilinmeyen: ortanca (200)
    assert S.estimate_total([_drv("a")]) == (0, 0)


def test_estimate_sizes_is_empty_off_windows():
    if os.name == "nt":
        pytest.skip("Windows'ta gerçek tarama yapar")
    assert S.estimate_sizes([_drv("oem1.inf")]) == {}


def test_empty_state_text_is_not_clipped(qapp):
    es = EmptyState("cpu")
    es.resize(900, 500)
    es.set_content("Sürücüler okunuyor…", "Bu birkaç saniye sürebilir.")
    es.show(); qapp.processEvents()
    needed = es.text.heightForWidth(es.text.width())
    assert es.text.height() >= needed > 0
    # dar alanda da metin kutusu alandan geniş olmaz ve yüksekliği satırlara yetişir
    es.resize(200, 400); qapp.processEvents()
    assert es.text.width() <= max(160, es.width())
    assert es.text.height() >= es.text.heightForWidth(es.text.width())
    es.close(); es.deleteLater(); qapp.processEvents()


def test_page_shows_estimate_and_blocks_usb_when_too_small(qapp, monkeypatch):
    import ui.pages.driver_backup_page as page_mod
    monkeypatch.setattr(S, "is_supported_platform", staticmethod(lambda: False))  # tarama başlamasın
    page = page_mod.DriverBackupPage()
    try:
        gib = 1024 ** 3
        page._drivers = [_drv("oem1.inf", gib), _drv("oem2.inf", gib // 2)]
        page._fill_table(page._drivers)
        assert "≈ 1.5 GB" in page.summary.text()
        page._usb_targets = [("E: – Test", "E:\\")]
        page.usb_combo.clear(); page.usb_combo.addItem("E: – Test", "E:\\")
        monkeypatch.setattr(S, "check_free_space", staticmethod(lambda path: (gib // 2, None)))
        page._update_summary()
        assert not page.usb_button.isEnabled()
        assert "Yer yetmiyor" in page.usb_info.text()
        monkeypatch.setattr(S, "check_free_space", staticmethod(lambda path: (8 * gib, None)))
        page._update_summary()
        assert page.usb_button.isEnabled()
        assert "8.0 GB" in page.usb_info.text() and "1.5 GB" in page.usb_info.text()
    finally:
        page.close(); page.deleteLater(); qapp.processEvents()
