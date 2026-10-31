"""Uygulamanın ortak stil sayfası (QSS).

Ana pencere ve tüm sayfalar tarafından paylaşılan görünüm kuralları burada, bölümlere ayrılmış
olarak durur. Renk ve ölçü değerleri ``TOKENS`` içindedir; QSS metninde ``@ADI@`` yazılır ve
``qss()`` ile gerçek değere çevrilir. Sayfalar yalnızca kendine özgü kuralları kendi dosyasında
tutar; ortak bileşenler (düğmeler, tablo başlığı, kaydırma çubuğu, sayfa başlığı…) buradan gelir.

Koyu tema ``ui.theme`` tarafından çalışma anında bu metinden türetilir; burada yalnızca açık tema
renkleri yazılır.
"""
from __future__ import annotations

import re

# Açık tema renk ve ölçü değerleri (tek kaynak)
TOKENS: dict[str, str] = {
    "BLUE": "#2167D5",  # birincil mavi (düğme dolgusu, vurgulu metin, seçili öğe)
}

_TOKEN = re.compile(r"@([A-Z0-9_]+)@")


def qss(text: str) -> str:
    """``@ADI@`` yer tutucularını ``TOKENS`` değerleriyle değiştirir."""
    return _TOKEN.sub(lambda m: TOKENS.get(m.group(1), m.group(0)), text)


SECTIONS: dict[str, str] = {}

# ---- Temel: pencere, genel yazı tipi, etiket
SECTIONS["base"] = '''
QMainWindow#mainWindow {
    background: #F5F8FC;
}
QWidget {
    color: #14213D;
    font-family: "Segoe UI";
    font-size: 14px;
    background: transparent;
}
QWidget#centralRoot, QStackedWidget#pageStack {
    background: #F5F8FC;
}
QLabel {
    background: transparent;
    border: none;
}
'''

# ---- Yan menü ve marka kartı
SECTIONS["sidebar"] = '''
QFrame#sidebar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0A1A31, stop:1 #0C2244);
    border: none;
    border-right: 1px solid #14304F;
}
QFrame#brandCard {
    background: #0F2749;
    border: 1px solid #1F3F66;
    border-radius: 14px;
}
QLabel#brandLogo {
    background: transparent;
    border: none;
}
QLabel#brandTitle {
    color: #FFFFFF;
    font-size: 16px;
    font-weight: 700;
    background: transparent;
}
QLabel#brandSubtitle {
    color: #9DB2CC;
    font-size: 11px;
    background: transparent;
}
QLabel#navGroupLabel {
    color: #8FA9C9;
    font-size: 11px;
    font-weight: 700;
    padding: 6px 4px 4px 4px;
    letter-spacing: 1.5px;
}
QFrame#navDivider {
    background: #1A3555;
    border: none;
}
QFrame#sidebarFooter {
    background: #0F2749;
    border: 1px solid #1F3F66;
    border-radius: 14px;
}
QLabel#statusDot {
    background: #2FD27F;
    border: 3px solid #1C6B4A;
    border-radius: 6px;
}
QLabel#versionLabel {
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 700;
}
QLabel#lastCheckLabel {
    color: #93A9C4;
    font-size: 11px;
}
'''

# ---- Sayfa başlığı ve alt başlığı
SECTIONS["page_header"] = '''
QLabel#pageTitle {
    font-size: 28px;
    font-weight: 700;
    color: #0B1736;
    background: transparent;
}
QLabel#pageSubtitle {
    color: #65728A;
    font-size: 14px;
    background: transparent;
}
'''

# ---- Arama / istatistik kartları
SECTIONS["cards"] = '''
QFrame#searchCard, QFrame#statCard {
    background: #FFFFFF;
    border: 1px solid #DCE5F0;
    border-radius: 12px;
}
QFrame#statCard {
    min-height: 86px;
}
QLabel#statTitle {
    color: #65728A;
    font-size: 12px;
    background: transparent;
}
QLabel#statValue {
    color: #0B1736;
    font-size: 24px;
    font-weight: 700;
    background: transparent;
}
QLabel#statNote {
    color: #8A96A8;
    font-size: 11px;
    background: transparent;
}
'''

# ---- Metin kutuları ve açılır listeler
SECTIONS["inputs"] = '''
QLineEdit, QComboBox {
    background: #FFFFFF;
    border: 1px solid #C9D5E4;
    border-radius: 8px;
    padding: 9px 12px;
    min-height: 24px;
    selection-background-color: @BLUE@;
    color: #14213D;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid @BLUE@;
}
QComboBox {
    padding: 9px 34px 9px 12px;
}
QComboBox::drop-down {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 30px;
    border: 0px;
    background: transparent;
    margin: 0px;
    padding: 0px;
}
QComboBox::down-arrow {
    width: 9px;
    height: 9px;
    margin-right: 10px;
}
QComboBox:on {
    border: 1px solid @BLUE@;
    border-radius: 8px;
    background: #FFFFFF;
}
QComboBox[popupOpen="true"] {
    border: 1px solid @BLUE@;
    border-radius: 8px;
    background: #FFFFFF;
}
QWidget#modernComboPopup {
    background: transparent;
    border: none;
}
QListWidget#modernComboPopupList {
    background: transparent;
    border: none;
    outline: none;
    padding: 4px;
    color: #14213D;
}
QListWidget#modernComboPopupList::item {
    min-height: 28px;
    padding: 6px 10px;
    margin: 1px 2px;
    border: none;
    border-radius: 7px;
    color: #14213D;
    background: transparent;
}
QListWidget#modernComboPopupList::item:hover {
    background: #EEF4FF;
    color: #0B1736;
}
QListWidget#modernComboPopupList::item:selected {
    background: @BLUE@;
    color: #FFFFFF;
}
QListWidget#modernComboPopupList QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 7px 3px 7px 0;
}
QListWidget#modernComboPopupList QScrollBar::handle:vertical {
    background: #C3D2E7;
    min-height: 26px;
    border-radius: 4px;
}
QListWidget#modernComboPopupList QScrollBar::add-line:vertical,
QListWidget#modernComboPopupList QScrollBar::sub-line:vertical,
QListWidget#modernComboPopupList QScrollBar::add-page:vertical,
QListWidget#modernComboPopupList QScrollBar::sub-page:vertical {
    background: transparent;
    border: none;
}
'''

# ---- Düğmeler
SECTIONS["buttons"] = '''
QPushButton {
    background: @BLUE@;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 600;
    min-height: 22px;
}
QPushButton:hover {
    background: #185ABE;
}
QPushButton:disabled {
    background: #D9DEE6;
    color: #8F99A8;
}
QPushButton#dangerButton {
    background: #FFFFFF;
    color: #E53935;
    border: 1px solid #EF5350;
}
QPushButton#dangerButton:hover {
    background: #FFF4F4;
}
'''

# ---- Bilgi kutuları
SECTIONS["info_boxes"] = '''
QLabel#infoBox {
    background: #EAF2FF;
    border: 1px solid #C8DFFF;
    border-radius: 8px;
    padding: 12px;
    color: #31537B;
}
QLabel#subtleInfoBox {
    background: #F7FAFF;
    border: 1px solid #D9E6F7;
    border-radius: 8px;
    padding: 10px 12px;
    color: #5B6E88;
}
'''

# ---- Tablolar ve başlıkları
SECTIONS["tables"] = '''
QTableWidget, QTableView, QListWidget {
    outline: none;
}
QTableWidget {
    background: white;
    border: 1px solid #DDE5F0;
    border-radius: 10px;
    gridline-color: #E7EEF7;
    alternate-background-color: #F8FBFF;
    selection-background-color: #DDEBFF;
    selection-color: #0B1736;
    show-decoration-selected: 1;
}
QHeaderView::section {
    background: #EDF4FD;
    color: #16345F;
    border: none;
    border-right: 1px solid #D8E4F2;
    border-bottom: 1px solid #D8E4F2;
    padding: 8px;
    font-weight: 600;
}

QTableWidget::item {
    padding: 7px 8px;
    border: none;
}
QTableWidget::item:hover {
    background: #F4F8FF;
}
QTableWidget::item:selected {
    background: #DDEBFF;
    color: #16345F;
    border: none;
}
QTableWidget::item:selected:active {
    background: #DDEBFF;
    color: #16345F;
    border: none;
}
QTableWidget::item:selected:!active {
    background: #DDEBFF;
    color: #16345F;
    border: none;
}
QTableWidget::item:focus,
QTableView::item:focus,
QListWidget::item:focus {
    outline: none;
    border: none;
}
QTableCornerButton::section {
    background: #EDF4FD;
    border: none;
    border-right: 1px solid #D8E4F2;
    border-bottom: 1px solid #D8E4F2;
}
'''

# ---- İlerleme çubuğu
SECTIONS["progress"] = '''
QProgressBar#downloadProgress {
    background: #ECF2FA;
    border: 1px solid #D5E1EF;
    border-radius: 7px;
    text-align: center;
    color: white;
    font-weight: 700;
}
QProgressBar#downloadProgress::chunk {
    background-color: @BLUE@;
    border-radius: 6px;
}
'''

# ---- Menüler
SECTIONS["menus"] = '''
QMenu {
    background-color: #FFFFFF;
    color: #14213D;
    border: 1px solid #C9D5E5;
    border-radius: 6px;
    padding: 5px;
}
QMenu::item {
    background-color: transparent;
    color: #14213D;
    padding: 7px 28px 7px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: @BLUE@;
    color: #FFFFFF;
}
QMenu::item:disabled {
    color: #98A4B5;
}
QMenu::separator {
    height: 1px;
    background: #E2E9F2;
    margin: 5px 8px;
}
'''

# ---- Ayrıntı paneli
SECTIONS["detail"] = '''
QFrame#detailPanel {
    background: #FFFFFF;
    border: 1px solid #D8E4F2;
    border-radius: 10px;
}
QLabel#detailTitle {
    color: #0B1736;
    font-size: 18px;
    font-weight: 700;
}
QLabel#detailName {
    color: #16345F;
    font-size: 15px;
    font-weight: 600;
    padding-bottom: 6px;
}
QLabel#detailMeta {
    color: #5C6F89;
    font-size: 13px;
    padding: 2px 0;
}
QFrame#detailMetadataGrid {
    background: transparent;
    border: none;
}
QFrame#detailMetaCard {
    background: #F7FAFF;
    border: 1px solid #DFE8F4;
    border-radius: 8px;
    min-height: 44px;
}
QLabel#detailMetaCaption {
    color: #7A899D;
    font-size: 11px;
    font-weight: 500;
    background: transparent;
}
QLabel#detailMetaValue {
    color: #17365D;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
QSplitter::handle {
    background: #E5ECF5;
    width: 4px;
}
'''

# ---- İleti kutusu
SECTIONS["dialogs"] = '''
QMessageBox {
    background-color: #FFFFFF;
    color: #14213D;
}
QMessageBox QLabel {
    background: transparent;
    color: #14213D;
    min-width: 360px;
}
QMessageBox QPushButton {
    background: @BLUE@;
    color: #FFFFFF;
    border: none;
    border-radius: 7px;
    padding: 8px 18px;
    min-width: 90px;
}
QMessageBox QPushButton:hover {
    background: #185ABE;
}
'''

# ---- Paket listesi ve paket kartları
SECTIONS["packages"] = '''
QLabel#detailSectionTitle {
    color: #0B1736;
    font-size: 15px;
    font-weight: 700;
    margin-top: 8px;
}
QListWidget#packageList {
    background: #F8FBFF;
    border: 1px solid #D8E4F2;
    border-radius: 8px;
    color: #14213D;
    outline: none;
}
QListWidget#packageList::item {
    background: #FFFFFF;
    border-bottom: 1px solid #E5ECF5;
    padding: 10px;
    color: #14213D;
    border-radius: 6px;
}
QListWidget#packageList::item:hover {
    background: #EEF4FF;
}
QListWidget#packageList::item:selected {
    background: #DDEBFF;
    color: #16345F;
    border: 1px solid #BFD6F6;
}

QFrame#packageInfoCard {
    background: #F8FBFF;
    border: 1px solid #D8E4F2;
    border-radius: 8px;
}
QLabel#packageFileLabel {
    color: #243B5A;
    font-size: 12px;
    background: transparent;
}
QLabel#packageLinkStatus {
    color: #315F9A;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}

QScrollArea#detailScroll {
    background: #FFFFFF;
    border: none;
}
QWidget#detailScrollContent {
    background: #FFFFFF;
}
QFrame#detailFooter {
    background: #FFFFFF;
    border-top: 1px solid #E0E8F2;
}
QLabel#packageInfoTitle {
    color: #0B1736;
    font-size: 12px;
    font-weight: 700;
    background: transparent;
}
QFrame#packageInfoCard {
    background: #F6FAFF;
    border: 1px solid #D9E5F3;
    border-radius: 8px;
}
QFrame#packageWorkspace {
    background: transparent;
    border: none;
}
QFrame#packageQuickCard {
    background: #FFFFFF;
    border: 1px solid #DCE7F4;
    border-radius: 6px;
}
QLabel#packageQuickCaption {
    color: #8190A5;
    font-size: 10px;
    background: transparent;
}
QLabel#packageQuickValue {
    color: #17365D;
    font-size: 11px;
    font-weight: 600;
    background: transparent;
}
'''

# ---- ISO oluşturma durumu ve günlük
SECTIONS["iso"] = '''
QLabel#isoCurrentStatus {
    color: #17365D;
    font-size: 13px;
    font-weight: 600;
    background: #F6F9FE;
    border: 1px solid #D9E6F7;
    border-radius: 7px;
    padding: 8px 10px;
}
QLabel#isoInfoLabel {
    color: #60738E;
    font-size: 11px;
}
QLabel#isoStagePending {
    color: #7C8CA1;
    background: #F4F7FB;
    border: 1px solid #E0E8F3;
    border-radius: 7px;
    padding: 5px 7px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#isoStageActive {
    color: #FFFFFF;
    background: #246BCE;
    border: 1px solid #246BCE;
    border-radius: 7px;
    padding: 5px 7px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#isoStageDone {
    color: #176B3A;
    background: #EAF7EF;
    border: 1px solid #BDE3CA;
    border-radius: 7px;
    padding: 5px 7px;
    font-size: 10px;
    font-weight: 700;
}
QTextEdit#isoLogView {
    background: #0F172A;
    color: #DCE7F7;
    border: 1px solid #26354C;
    border-radius: 8px;
    padding: 8px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 10px;
    selection-background-color: #246BCE;
}
'''

# ---- Kaydırma çubuğu (tüm sayfalarda aynı)
SECTIONS["scrollbars"] = '''
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #C5D2E4; min-height: 30px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #A8BBD6; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; border: none; }
QComboBox#modernComboBox:hover { border-color: #9DB9E6; }
'''


def main_qss() -> str:
    """Ana pencerenin tüm ortak stil sayfası."""
    return qss("\n".join(SECTIONS.values()))
