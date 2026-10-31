import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from urllib.parse import urlparse
from PySide6.QtWidgets import QApplication

from ui import help_content as hc
import ui.pages.help_page as hp


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_content_is_complete_and_links_are_https_site():
    assert len(set(hc.KEYS)) == len(hc.KEYS)
    for s in hc.SECTIONS:
        for pair in (s["title"], s["what"]):
            assert all(isinstance(x, str) and x.strip() for x in pair)
        for step in s["steps"] + s["notes"]:
            assert len(step) == 2 and all(step)
        for tr, en, url in s["links"]:
            assert tr and en
            u = urlparse(url)
            assert u.scheme == "https" and u.netloc == "bunyaminkaya.com"


def test_every_nav_page_has_a_section():
    from ui.main_window import MainWindow  # noqa: F401  (sayfa adları kaynak kodda sabit)
    import re, pathlib
    src = pathlib.Path("ui/main_window.py").read_text(encoding="utf-8")
    names = re.findall(r'\("([^"]+)", \w+(?:Page)\),', src)
    assert names
    for n in names:
        assert n in hc.KEYS or n == "Yardım", n


def test_page_shows_and_searches(app):
    p = hp.HelpPage()
    p.show_section("USB Kurulum Aracı")
    assert "USB" in p.browser.toPlainText()
    assert "bunyaminkaya" in p.browser.toHtml() or "Rufus" in p.browser.toPlainText()
    p.search.setText("sürücü")
    visible = [p.list.item(i).data(0x0100) for i in range(p.list.count()) if not p.list.item(i).isHidden()]
    assert "Sürücü Yedekleme" in visible and "Ayarlar" not in visible
    p.search.setText("zzzyokböyle")
    assert all(p.list.item(i).isHidden() for i in range(p.list.count()))


def test_unknown_page_falls_back_to_start(app):
    p = hp.HelpPage()
    p.show_section("olmayan sayfa")
    assert p._current == "Başlarken"
