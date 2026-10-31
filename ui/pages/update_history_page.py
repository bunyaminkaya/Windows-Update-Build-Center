from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QScrollArea, QStackedWidget, QStyle, QStyledItemDelegate,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ui import icons
from ui.widgets.release_chart import ReleaseChart
from ui.widgets.empty_state import attach_empty_state
from ui.widgets.modern_combo_box import ModernComboBox

from services.build_history_service import BuildHistoryService
from services.build_tracker_service import BuildTrackerRecord, BuildTrackerService


_PILL = {
    "release preview": ("#FFEFD6", "#C2680C"),
    "beta": ("#E3F6EA", "#15803D"),
    "experimental": ("#F3E8FF", "#7C3AED"),
    "canary": ("#FEECEC", "#DC2626"),
    "default": ("#E6F0FF", "#1D4ED8"),
}


def _pill_colors(channel: str):
    value = (channel or "").casefold()
    for key in ("release preview", "beta", "experimental", "canary"):
        if key in value:
            return _PILL[key]
    return _PILL["default"]


class ReleaseRowDelegate(QStyledItemDelegate):
    """Yayınlanan güncellemeler tablosu çizimi (yalnızca görünüm)."""

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#EAF2FE"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor("#F6F9FE"))
        else:
            painter.fillRect(rect, QColor("#FFFFFF"))
        painter.setPen(QColor("#EDF1F6"))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        text = str(index.data(Qt.DisplayRole) or "")
        col = index.column()
        painter.setFont(option.font)
        if col == 0:
            painter.drawPixmap(rect.left() + 10, rect.center().y() - 11, icons.pixmap("windows-color", "#1768E0", 22))
            painter.setPen(QColor("#2A3A5C"))
            painter.drawText(rect.adjusted(44, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter, text)
        elif col == 4:
            bg, fg = _pill_colors(text)
            font = option.font
            font.setBold(True)
            font.setPointSizeF(max(8.0, font.pointSizeF() - 0.5))
            painter.setFont(font)
            width = QFontMetrics(font).horizontalAdvance(text) + 24
            pill = QRectF(rect.left() + 6, rect.center().y() - 12, width, 24)
            path = QPainterPath()
            path.addRoundedRect(pill, 12, 12)
            painter.fillPath(path, QColor(bg))
            painter.setPen(QColor(fg))
            painter.drawText(pill, Qt.AlignCenter, text)
        elif col == 6:
            painter.setPen(QColor("#1768E0"))
            painter.drawText(rect.adjusted(0, 0, -34, 0), Qt.AlignRight | Qt.AlignVCenter, text)
            painter.drawPixmap(rect.right() - 28, rect.center().y() - 8, icons.pixmap("chevron-right", "#4B5E7C", 16, stroke=2.2))
        else:
            painter.setPen(QColor("#4A5B7A") if col == 5 else QColor("#2A3A5C"))
            elided = option.fontMetrics.elidedText(text, Qt.ElideRight, max(1, rect.width() - 16))
            painter.drawText(rect.adjusted(8, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()


class UpdateHistoryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[BuildTrackerRecord] = []
        self._visible_rows: list[BuildTrackerRecord] = []
        self._build_ui()
        self.reload()

    @staticmethod
    def _ico(name: str, color: str, size: int = 36, stroke: float = 2.0) -> QIcon:
        return QIcon(icons.pixmap(name, color, size, stroke=stroke))

    @staticmethod
    def _field(caption: str, combo) -> QFrame:
        box = QFrame()
        box.setObjectName("fldBox")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 6, 8, 4)
        lay.setSpacing(0)
        cap = QLabel(caption)
        cap.setObjectName("fldCaption")
        lay.addWidget(cap)
        lay.addWidget(combo)
        box.setFixedHeight(52)
        box.setMinimumWidth(170)
        return box

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 22)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        tile = QLabel()
        tile.setObjectName("histTile")
        tile.setFixedSize(52, 52)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap("history", "#1768E0", 30, stroke=2.0))
        header.addWidget(tile, 0, Qt.AlignTop)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Güncelleme Geçmişi")
        title.setObjectName("histTitle")
        subtitle = QLabel("Daha önce yayımlanan Windows güncellemelerinin kaydını tarih ve sürüme göre inceleyin.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        refresh = QPushButton("  Geçmişi Yenile")
        refresh.setObjectName("primaryButton")
        refresh.setIcon(self._ico("refresh", "#FFFFFF"))
        refresh.setIconSize(QSize(18, 18))
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.reload)
        from ui.widgets.table_export import make_export_button, export_table_csv
        self.export_button = make_export_button()
        self.export_button.clicked.connect(
            lambda: export_table_csv(self, self.release_table, "guncelleme_gecmisi", skip_columns=(6,))
        )
        header.addWidget(self.export_button, 0, Qt.AlignTop)
        header.addWidget(refresh, 0, Qt.AlignTop)
        root.addLayout(header)

        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(14)
        self.summary_cards: dict[str, tuple[QLabel, QLabel]] = {}
        for key, title_text in (("today", "Bugün"), ("week", "Bu hafta"), ("month", "Bu ay")):
            card = QFrame()
            card.setObjectName("historyStatCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(18, 14, 18, 14)
            row.setSpacing(14)
            ic = QLabel()
            ic.setObjectName("histStatTile")
            ic.setFixedSize(48, 48)
            ic.setAlignment(Qt.AlignCenter)
            ic.setPixmap(icons.pixmap("calendar", "#1768E0", 26, stroke=2.0))
            row.addWidget(ic)
            layout = QVBoxLayout()
            layout.setSpacing(0)
            caption = QLabel(title_text)
            caption.setObjectName("historyStatTitle")
            value = QLabel("0 kayıt")
            value.setObjectName("historyStatValue")
            value.setTextFormat(Qt.RichText)
            note = QLabel("Build Tracker yayın tarihine göre")
            note.setObjectName("historyStatNote")
            note.setVisible(False)
            layout.addWidget(caption)
            layout.addWidget(value)
            layout.addWidget(note)
            row.addLayout(layout, 1)
            summary_layout.addWidget(card, 1)
            self.summary_cards[key] = (value, note)
        root.addLayout(summary_layout)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("historyTabs")
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setCursor(Qt.PointingHandCursor)
        self.tabs.addTab(self._build_releases_tab(), "Yayınlanan Güncellemeler")
        self.tabs.addTab(self._build_checks_tab(), "Kontrol Geçmişi")
        self.tabs.addTab(self._build_chart_tab(), "Grafik")
        root.addWidget(self.tabs, 1)

        info_box = QFrame()
        info_box.setObjectName("historyInfo")
        ib = QHBoxLayout(info_box)
        ib.setContentsMargins(14, 10, 14, 10)
        ib.setSpacing(10)
        iic = QLabel()
        iic.setPixmap(icons.pixmap("info-fill", "#1768E0", 18))
        iic.setStyleSheet("background: transparent; border: none;")
        ib.addWidget(iic)
        info = QLabel("Üst kısımdaki kartlar, seçili dönem için yayınlanan güncellemelerin özetini göstermektedir. Kontrol Geçmişi sekmesi, programın gerçekleştirdiği canlı kontrol işlemlerinin kayıtlarını içerir.")
        info.setObjectName("historyInfoText")
        info.setWordWrap(True)
        ib.addWidget(info, 1)
        root.addWidget(info_box)

        up, down = self._arrow_urls()
        self.setStyleSheet("""
            QLabel { background: transparent; }
            QLabel#histTile { background: #E3EEFC; border-radius: 26px; }
            QLabel#histTitle { color: #0A1F44; font-size: 30px; font-weight: 700; }
            QPushButton#primaryButton {
                background: #1768E0; color: #FFFFFF; border: none; border-radius: 12px;
                padding: 0 20px; font-size: 13px; font-weight: 700; min-height: 44px; max-height: 44px;
            }
            QPushButton#primaryButton:hover { background: #135BC4; }
            QFrame#historyStatCard, QFrame#historyTablePanel {
                background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px;
            }
            QLabel#histStatTile { background: #E8F0FD; border-radius: 12px; }
            QLabel#historyStatTitle { color: #3A4D70; font-size: 12px; font-weight: 700; }
            QLabel#historyStatValue { color: #14213D; font-size: 26px; font-weight: 700; }
            QLabel#historyStatNote, QLabel#historyResultInfo { color: #7C8BA5; font-size: 12px; }
            QLabel#historySectionTitle { color: #14213D; font-size: 15px; font-weight: 700; }
            QFrame#historyInfo { background: #F2F7FF; border: 1px solid #D7E5F7; border-radius: 10px; }
            QLabel#historyInfoText { color: #55708E; font-size: 11px; }
            QTabWidget#historyTabs::pane { border: none; background: transparent; top: 10px; }
            QTabBar { background: transparent; }
            QTabBar::tab {
                background: #E9F0FA; color: #1768E0; padding: 11px 24px; margin-right: 10px;
                border-radius: 10px; font-weight: 700; font-size: 13px; border: none;
            }
            QTabBar::tab:selected { background: #1768E0; color: #FFFFFF; }
            QTabBar::tab:hover:!selected { background: #DCE8F8; }
            QLineEdit#histSearch {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 10px;
                padding: 0 12px 0 4px; font-size: 13px; color: #14213D; min-height: 50px; max-height: 50px;
                selection-background-color: #1768E0;
            }
            QLineEdit#histSearch:focus { border: 1px solid #1768E0; }
            QFrame#fldBox { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 10px; }
            QFrame#fldBox:hover { border-color: #9DB9E6; }
            QLabel#fldCaption { color: #6C7C93; font-size: 10px; font-weight: 600; }
            QFrame#fldBox QComboBox#modernComboBox {
                background: transparent; border: none; padding: 0 22px 0 0;
                font-size: 13px; font-weight: 600; color: #14213D; min-height: 22px; max-height: 22px;
            }
            QPushButton#histViewButton {
                background: #FFFFFF; color: #3A4D70; border: 1px solid #D5E0EE; border-radius: 10px;
                padding: 0 14px; font-size: 13px; font-weight: 600; min-height: 42px; max-height: 42px;
            }
            QPushButton#histViewButton:checked { background: #1768E0; color: #FFFFFF; border: 1px solid #1768E0; }
            QPushButton#histViewButton:hover:!checked { background: #F1F6FD; }
            QFrame#histDivider { background: #DCE5F1; border: none; }
            QTableWidget#historyTable { background: #FFFFFF; border: none; outline: none; gridline-color: transparent; }
            QTableWidget#historyTable QHeaderView::section {
                background: #F4F8FD; color: #3A4D70; border: none; padding: 11px 8px;
                font-size: 12px; font-weight: 700;
            }
            QTableWidget#historyTable QHeaderView::section:first { padding-left: 44px; }
            QTableWidget#historyTable QHeaderView::up-arrow { image: url(%UP%); width: 10px; height: 10px; }
            QTableWidget#historyTable QHeaderView::down-arrow { image: url(%DOWN%); width: 10px; height: 10px; }
            QScrollArea#histCardScroll, QWidget#histCardHost { background: #FFFFFF; border: none; }
            QFrame#newUpdateCard { background: #FFFFFF; border: 1px solid #DCE5F0; border-radius: 10px; }
            QFrame#newUpdateCard:hover { border-color: #77A7EE; background: #F8FBFF; }
            QFrame#newUpdateCard[channelStyle="release-preview"] { background: #FFFBF2; border-color: #FDE7B2; }
            QFrame#newUpdateCard[channelStyle="beta"] { background: #F5FCF7; border-color: #D6F1DE; }
            QFrame#newUpdateCard[channelStyle="experimental"] { background: #FAF7FF; border-color: #EADCFF; }
            QFrame#newUpdateCard[channelStyle="retail"], QFrame#newUpdateCard[channelStyle="dev"] { background: #F7FAFF; border-color: #DBEAFE; }
            QFrame#newUpdateCard[channelStyle="canary"] { background: #FFF8F8; border-color: #FEE2E2; }
            QLabel#windowsTileIcon { background: #EAF3FF; color: #2167D5; border-radius: 8px; font-size: 22px; font-weight: 700; }
            QLabel#newUpdateTitle { color: #10213D; font-weight: 700; font-size: 14px; }
            QLabel#newUpdateMeta { color: #53657D; font-size: 11px; }
            QLabel#newUpdateDate { color: #7E8EA3; font-size: 10px; }
            QLabel#updateKindBadge { padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 700; background: #E6F0FF; color: #1D4ED8; }
            QLabel#updateKindBadge[channelStyle="release-preview"] { background: #FFEFD6; color: #C2680C; }
            QLabel#updateKindBadge[channelStyle="beta"] { background: #E3F6EA; color: #15803D; }
            QLabel#updateKindBadge[channelStyle="experimental"] { background: #F3E8FF; color: #7C3AED; }
            QLabel#updateKindBadge[channelStyle="canary"] { background: #FEECEC; color: #DC2626; }
        """.replace("%UP%", up).replace("%DOWN%", down))

    @staticmethod
    def _arrow_urls() -> tuple[str, str]:
        import os, tempfile
        out = []
        for name, flip in (("up", True), ("down", False)):
            try:
                pm = icons.pixmap("chevron-down", "#4B5E7C", 12, stroke=2.4)
                if flip:
                    pm = pm.transformed(QTransform().scale(1, -1))
                path = os.path.join(tempfile.gettempdir(), f"wubc_hist_{name}.png")
                pm.save(path, "PNG")
                out.append(path.replace("\\", "/"))
            except Exception:
                out.append("")
        return out[0], out[1]

    def _panel(self) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("historyTablePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return panel, layout

    def _configure_table(self, table: QTableWidget, stretch_column: int) -> None:
        table.setObjectName("historyTable")
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setMouseTracking(True)
        table.setFrameShape(QFrame.NoFrame)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        for column in range(table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Stretch if column == stretch_column else QHeaderView.ResizeToContents)

    def _build_releases_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        panel, layout = self._panel()

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(16, 14, 16, 12)
        toolbar.setSpacing(12)
        self.release_search = QLineEdit()
        self.release_search.setObjectName("histSearch")
        self.release_search.setPlaceholderText("Build veya KB ara...")
        self.release_search.setClearButtonEnabled(True)
        self.release_search.addAction(self._ico("search", "#4B5E7C"), QLineEdit.LeadingPosition)
        self.release_search.textChanged.connect(self._render_releases)
        toolbar.addWidget(self.release_search, 1)

        self.period_combo = ModernComboBox()
        self.period_combo.addItems(["Bu Ay", "Bu Hafta", "Bugün", "Tümü"])
        self.period_combo.currentTextChanged.connect(self._render_releases)
        toolbar.addWidget(self._field("Tarih Aralığı", self.period_combo), 1)

        self.version_combo = ModernComboBox()
        self.version_combo.addItems(["Tümü"])
        self.version_combo.currentTextChanged.connect(self._render_releases)
        toolbar.addWidget(self._field("Windows Sürümü", self.version_combo), 1)

        self.sort_combo = ModernComboBox()
        self.sort_combo.addItems(["Yayın tarihi: En yeni", "Yayın tarihi: En eski", "Build: Yüksek", "Build: Düşük"])
        self.sort_combo.currentTextChanged.connect(self._render_releases)
        toolbar.addWidget(self._field("Sıralama", self.sort_combo), 1)

        divider = QFrame()
        divider.setObjectName("histDivider")
        divider.setFixedSize(1, 36)
        toolbar.addWidget(divider)

        self.list_view_button = QPushButton("  Liste")
        self.card_view_button = QPushButton("  Kart")
        group = QButtonGroup(self)
        group.setExclusive(True)
        for b in (self.list_view_button, self.card_view_button):
            b.setObjectName("histViewButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(18, 18))
            b.setMinimumWidth(84)
            group.addButton(b)
            toolbar.addWidget(b)
        self.list_view_button.setChecked(True)
        self._card_mode = False
        self.list_view_button.clicked.connect(lambda: self._set_view_mode(False))
        self.card_view_button.clicked.connect(lambda: self._set_view_mode(True))
        self._set_view_icons(False)

        self.release_result_info = QLabel("")
        self.release_result_info.setObjectName("historyResultInfo")
        toolbar.addWidget(self.release_result_info)
        layout.addLayout(toolbar)

        self.release_table = QTableWidget(0, 7)
        self.release_table.setHorizontalHeaderLabels(["Yayın Tarihi", "Build", "KB", "Windows Sürümü", "Kanal", "Açıklama", ""])
        self._configure_table(self.release_table, 5)
        self.release_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        self.release_table.setColumnWidth(6, 90)
        self.release_table.horizontalHeader().setSectionsClickable(True)
        self.release_table.horizontalHeader().setSortIndicatorShown(True)
        self.release_table.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.release_table.setItemDelegate(ReleaseRowDelegate(self.release_table))
        self.release_table.cellClicked.connect(self._release_cell_clicked)
        self._release_empty = attach_empty_state(self.release_table, "history", self._release_empty_text)
        self._release_empty.clicked.connect(self.reload)

        self.card_scroll = QScrollArea()
        self.card_scroll.setObjectName("histCardScroll")
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.NoFrame)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("histCardHost")
        self.card_grid = QGridLayout(host)
        self.card_grid.setContentsMargins(16, 6, 16, 16)
        self.card_grid.setSpacing(12)
        self.card_scroll.setWidget(host)

        self.release_stack = QStackedWidget()
        self.release_stack.addWidget(self.release_table)
        self.release_stack.addWidget(self.card_scroll)
        layout.addWidget(self.release_stack, 1)
        outer.addWidget(panel)
        self._sync_sort_indicator()
        return tab

    def _release_empty_text(self):
        if not getattr(self, "records", None):
            return ("Henüz yayın kaydı yok", "Build Tracker kayıtları henüz alınmadı. Yenileyerek kayıtları yükleyebilirsiniz.", "Geçmişi Yenile")
        return ("Bu filtrede kayıt yok", "Tarih aralığını \"Tümü\" yapmayı veya aramayı değiştirmeyi deneyin.", None)

    def _check_empty_text(self):
        return ("Henüz kontrol kaydı yok", "Windows Sürüm Takibi kayıtları denetledikçe her kontrolün sonucu burada listelenir.", None)

    def _build_chart_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        panel, layout = self._panel()
        head = QVBoxLayout()
        head.setContentsMargins(20, 16, 20, 4)
        title = QLabel("Aylık Yayın Sayısı")
        title.setObjectName("historySectionTitle")
        note = QLabel("Son 12 ayda Build Tracker'a göre yayımlanan build sayısı, kanallara ayrılmış olarak.")
        note.setObjectName("historyResultInfo")
        head.addWidget(title)
        head.addWidget(note)
        layout.addLayout(head)
        self.release_chart = ReleaseChart()
        wrap = QVBoxLayout()
        wrap.setContentsMargins(20, 6, 20, 16)
        wrap.addWidget(self.release_chart)
        layout.addLayout(wrap, 1)
        outer.addWidget(panel)
        return tab

    def _build_checks_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        panel, layout = self._panel()
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(18, 14, 18, 10)
        title = QLabel("Program Kontrol Kayıtları")
        title.setObjectName("historySectionTitle")
        toolbar.addWidget(title)
        toolbar.addStretch()
        self.check_result_info = QLabel("")
        self.check_result_info.setObjectName("historyResultInfo")
        toolbar.addWidget(self.check_result_info)
        layout.addLayout(toolbar)
        self.check_table = QTableWidget(0, 6)
        self.check_table.setHorizontalHeaderLabels(["Kontrol Tarihi", "Durum", "Yeni Bulunan", "Toplam Kayıt", "Kaynak Kontrolü", "Bulunan Kayıtlar / Açıklama"])
        self._configure_table(self.check_table, 5)
        self.check_table.setStyleSheet("QHeaderView::section:first { padding-left: 18px; } QTableWidget::item { padding-left: 10px; border-bottom: 1px solid #EDF1F6; } QTableWidget::item:selected { background: #EAF2FE; color: #14213D; }")
        layout.addWidget(self.check_table, 1)
        attach_empty_state(self.check_table, "list", self._check_empty_text)
        outer.addWidget(panel)
        return tab

    # ── Yalnızca görünüm yardımcıları ──
    def _set_view_icons(self, card_mode: bool) -> None:
        self.list_view_button.setIcon(self._ico("list", "#3A4D70" if card_mode else "#FFFFFF"))
        self.card_view_button.setIcon(self._ico("boxes", "#FFFFFF" if card_mode else "#3A4D70"))

    def _set_view_mode(self, card_mode: bool) -> None:
        self._card_mode = bool(card_mode)
        self._set_view_icons(self._card_mode)
        self.release_stack.setCurrentIndex(1 if self._card_mode else 0)
        if self._card_mode:
            self._render_cards(self._visible_rows)

    def _render_cards(self, rows) -> None:
        from ui.pages.kb_updates_page import NewUpdateCard
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for idx, record in enumerate(rows):
            card = NewUpdateCard(record)
            card.clicked.connect(self._open_in_tracker)
            self.card_grid.addWidget(card, idx // 2, idx % 2)
        self.card_grid.setRowStretch((len(rows) + 1) // 2, 1)
        self.card_grid.setColumnStretch(0, 1)
        self.card_grid.setColumnStretch(1, 1)

    _SORT_CLICK = {0: (0, 1), 1: (2, 3)}

    def _header_clicked(self, column: int) -> None:
        pair = self._SORT_CLICK.get(column)
        if not pair:
            return
        current = self.sort_combo.currentIndex()
        self.sort_combo.setCurrentIndex(pair[1] if current == pair[0] else pair[0])

    def _sync_sort_indicator(self, *_args) -> None:
        index = self.sort_combo.currentIndex()
        column = 0 if index in (0, 1) else 1
        order = Qt.DescendingOrder if index in (0, 2) else Qt.AscendingOrder
        self.release_table.horizontalHeader().setSortIndicator(column, order)

    def _release_cell_clicked(self, row: int, column: int) -> None:
        if column == 6 and 0 <= row < len(self._visible_rows):
            self._open_in_tracker(self._visible_rows[row])

    def _open_in_tracker(self, record) -> None:
        window = self.window()
        if not hasattr(window, "page_by_name"):
            return
        page = window.page_by_name("Windows Sürüm Takibi")
        if page is None:
            return
        window.show_page_by_name("Windows Sürüm Takibi")
        page.select_record(record)

    def _refresh_version_filter(self) -> None:
        versions = sorted({r.windows_version for r in self.records if r.windows_version}, reverse=True)
        if tuple(versions) == getattr(self, "_version_key", None):
            return
        self._version_key = tuple(versions)
        current = self.version_combo.currentText()
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        self.version_combo.addItems(["Tümü"] + versions)
        self.version_combo.setCurrentIndex(max(0, self.version_combo.findText(current)))
        self.version_combo.blockSignals(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()

    def _release_groups(self) -> dict[str, list[BuildTrackerRecord]]:
        return BuildHistoryService.release_groups(self.records)

    def _render_releases(self, *_args) -> None:
        groups = self._release_groups()
        self._refresh_version_filter()
        period = self.period_combo.currentText()
        rows = {"Bugün": groups["today"], "Bu Hafta": groups["week"], "Bu Ay": groups["month"], "Tümü": self.records}.get(period, groups["month"])
        needle = self.release_search.text().strip().lower()
        version = self.version_combo.currentText()
        if needle:
            rows = [r for r in rows if needle in r.search_text]
        if version and version != "Tümü":
            rows = [r for r in rows if (r.windows_version or "") == version]
        sort_index = self.sort_combo.currentIndex()
        if sort_index == 1:
            rows = sorted(rows, key=lambda r: (r.release_date, r.build_number))
        elif sort_index in (2, 3):
            def build_key(r):
                try:
                    return tuple(int(x) for x in (r.build_number or "").split("."))
                except Exception:
                    return (0,)
            rows = sorted(rows, key=build_key, reverse=(sort_index == 2))
        self._sync_sort_indicator()
        self._visible_rows = list(rows)
        self.release_table.setRowCount(0)
        for record in rows:
            row = self.release_table.rowCount()
            self.release_table.insertRow(row)
            values = [self._display_release_date(record.release_date), record.build_number or "—", record.kb_number or "—", f"Windows 11 {record.windows_version or '—'}", record.channel or "—", record.description or "Açıklama bulunmuyor.", "Detay"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setForeground(QBrush(self._channel_color(record.channel)))
                self.release_table.setItem(row, column, item)
            self.release_table.setRowHeight(row, 46)
        self.release_result_info.setText(f"{len(rows)} kayıt")
        if getattr(self, "_card_mode", False):
            self._render_cards(self._visible_rows)

    @staticmethod
    def _channel_color(channel: str) -> QColor:
        value = (channel or "").casefold()
        if "release preview" in value: return QColor("#B45309")
        if "beta" in value: return QColor("#15803D")
        if "experimental" in value: return QColor("#7C3AED")
        if "canary" in value: return QColor("#DC2626")
        return QColor("#1D4ED8")

    @staticmethod
    def _display_release_date(value: str) -> str:
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            return value or "—"

    @staticmethod
    def _display_stamp(value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            return value or "—"

    @staticmethod
    def _details_text(entry: dict) -> str:
        if entry.get("status") == "failed":
            return str(entry.get("message") or "Kontrol başarısız oldu.")
        records = entry.get("new_records", []) or []
        if not records:
            return "Yeni kayıt bulunmadı."
        return "  •  ".join(" / ".join(filter(None, [f"Build {record.get('build', '')}" if record.get("build") else "", str(record.get("kb") or ""), str(record.get("version") or ""), str(record.get("channel") or "")])) for record in records)

    def _render_checks(self) -> None:
        entries = BuildHistoryService.load()
        self.check_table.setRowCount(0)
        for entry in entries:
            row = self.check_table.rowCount()
            self.check_table.insertRow(row)
            success = entry.get("status") == "success"
            values = [self._display_stamp(str(entry.get("checked_at", ""))), "Başarılı" if success else "Başarısız", str(entry.get("new_count", 0)), str(entry.get("total_count", 0)) if success else "—", str(entry.get("source_last_update") or "—"), self._details_text(entry)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setForeground(QBrush(QColor("#218A50" if success else "#C0392B")))
                if column == 2 and int(entry.get("new_count", 0) or 0) > 0:
                    item.setForeground(QBrush(QColor("#2167D5")))
                self.check_table.setItem(row, column, item)
            self.check_table.setRowHeight(row, 44)
        self.check_result_info.setText(f"{len(entries)} kontrol kaydı")

    def reload(self) -> None:
        records, _last_update, _fetched_at = BuildTrackerService.load_cache()
        self.records = sorted(records, key=lambda record: (record.release_date, record.build_number), reverse=True)
        groups = self._release_groups()
        for key, (value, note) in self.summary_cards.items():
            value.setText(f"<span style='color:#1768E0;font-size:28px;font-weight:700'>{len(groups[key])}</span> <span style='color:#3A4D70;font-size:15px;font-weight:500'>kayıt</span>")
            note.setText("Build Tracker yayın tarihine göre")
        self._render_releases()
        self._render_checks()
        self.release_chart.set_records(self.records)
