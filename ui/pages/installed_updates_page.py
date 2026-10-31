from __future__ import annotations

import ctypes
import re
from PySide6.QtCore import QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QTransform
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QFrame, QTextEdit, QDialog, QDialogButtonBox, QStyle, QStyledItemDelegate
)

from ui import icons

from services.windows_update_service import WindowsUpdateService
from services.build_tracker_service import BuildTrackerService


class _Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class InstalledRowDelegate(QStyledItemDelegate):
    """Yüklü KB tablosu çizimi: Windows ikonlu KB, Kaldırılabilir ve Durum rozetleri (yalnızca görünüm)."""

    def paint(self, painter, option, index):
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
            painter.drawPixmap(rect.left() + 12, rect.center().y() - 11, icons.pixmap("windows-color", "#1768E0", 22))
            painter.setPen(QColor("#1B3D73"))
            painter.drawText(rect.adjusted(46, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter, text)
        elif col in (4, 5):
            positive = text.lower() in ("evet", "yüklü")
            bg, fg = ("#E3F6EA", "#15803D") if positive else ("#EEF2F7", "#6C7C93")
            font = option.font
            font.setBold(True)
            font.setPointSizeF(max(8.0, font.pointSizeF() - 0.5))
            painter.setFont(font)
            width = QFontMetrics(font).horizontalAdvance(text) + 28
            pill = QRectF(rect.left() + 8, rect.center().y() - 13, width, 26)
            path = QPainterPath()
            path.addRoundedRect(pill, 13, 13)
            painter.fillPath(path, QColor(bg))
            painter.setPen(QColor(fg))
            painter.drawText(pill, Qt.AlignCenter, text)
        else:
            painter.setPen(QColor("#2A3A5C"))
            elided = option.fontMetrics.elidedText(text, Qt.ElideRight, max(1, rect.width() - 16))
            painter.drawText(rect.adjusted(8, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()


class InstalledUpdatesPage(QWidget):
    """Tüm yüklü KB güncellemelerini gösteren ve güvenli kaldırma sağlayan sayfa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._worker = None
        self.setObjectName("installedPage")
        self._build_ui()
        self._apply_styles()
        self.refresh_installed()

    @staticmethod
    def _ico(name, color, size=36, stroke=2.0):
        return QIcon(icons.pixmap(name, color, size, stroke=stroke))

    @staticmethod
    def _stat_card(icon_name, tile_bg, icon_color, title):
        card = QFrame()
        card.setObjectName("iuStat")
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(16)
        tile = QLabel()
        tile.setFixedSize(56, 56)
        tile.setAlignment(Qt.AlignCenter)
        tile.setStyleSheet(f"background: {tile_bg}; border-radius: 16px;")
        tile.setPixmap(icons.pixmap(icon_name, icon_color, 28, stroke=2.0))
        row.addWidget(tile)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(title)
        t.setObjectName("iuStatTitle")
        v = QLabel("0")
        v.setObjectName("iuStatValue")
        n = QLabel("")
        n.setObjectName("iuStatNote")
        col.addWidget(t)
        col.addWidget(v)
        col.addWidget(n)
        row.addLayout(col, 1)
        return card, v, n

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        tile = QLabel()
        tile.setFixedSize(56, 56)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap("windows-color", "#1768E0", 44))
        header.addWidget(tile, 0, Qt.AlignTop)
        tb = QVBoxLayout()
        tb.setSpacing(2)
        title = QLabel("Yüklü Güncellemeler")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Bilgisayarınızda kurulu güncellemeleri KB numaralarıyla listeleyin ve inceleyin.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        tb.addWidget(title)
        tb.addWidget(subtitle)
        header.addLayout(tb, 1)
        self.header_refresh_btn = QPushButton("  Yenile")
        self.header_refresh_btn.setObjectName("iuPrimary")
        self.header_refresh_btn.setIcon(self._ico("refresh", "#FFFFFF"))
        self.header_refresh_btn.setIconSize(QSize(18, 18))
        self.header_refresh_btn.setCursor(Qt.PointingHandCursor)
        from ui.widgets.table_export import make_export_button, export_table_csv
        self.export_button = make_export_button()
        self.export_button.clicked.connect(
            lambda: export_table_csv(self, self.table, "yuklu_guncellemeler")
        )
        header.addWidget(self.export_button, 0, Qt.AlignTop)
        header.addWidget(self.header_refresh_btn, 0, Qt.AlignTop)
        root.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        c1, self.stat_total, self.stat_total_note = self._stat_card("doc", "#DCEAFD", "#1768E0", "Toplam Yüklü KB")
        c2, self.stat_removable, self.stat_removable_note = self._stat_card("trash", "#D8F2E4", "#15803D", "Kaldırılabilir")
        c3, self.stat_check, self.stat_check_note = self._stat_card("warning", "#FDE9C8", "#E08A12", "Kontrol Gerekiyor")
        for c in (c1, c2, c3):
            stats.addWidget(c, 1)
        root.addLayout(stats)

        body = QHBoxLayout()
        body.setSpacing(14)

        left = QFrame()
        left.setObjectName("iuCard")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 14)
        lv.setSpacing(12)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.refresh_btn = QPushButton("  Yenile")
        self.refresh_btn.setObjectName("iuPrimary")
        self.refresh_btn.setIcon(self._ico("refresh", "#FFFFFF"))
        self.refresh_btn.clicked.connect(self.refresh_installed)
        self.header_refresh_btn.clicked.connect(self.refresh_btn.click)
        self.failed_btn = QPushButton("  Başarısız Güncellemeleri Tara")
        self.failed_btn.setObjectName("iuPrimary")
        self.failed_btn.setIcon(self._ico("shield", "#FFFFFF"))
        self.failed_btn.clicked.connect(self.scan_failed)
        self.compare_btn = QPushButton("  Eksik KB'leri Kontrol Et")
        self.compare_btn.setObjectName("iuSecondary")
        self.compare_btn.setIcon(self._ico("gear-outline", "#1768E0"))
        self.compare_btn.setToolTip("Build Tracker ile Eksik KB Kontrolü")
        self.compare_btn.clicked.connect(self.compare_tracker)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("iuSearch")
        self.filter_edit.setPlaceholderText("KB numarası, açıklama veya tarih ara...")
        self.filter_edit.addAction(self._ico("search", "#4B5E7C"), QLineEdit.LeadingPosition)
        self.filter_edit.textChanged.connect(self._filter)
        for b in (self.refresh_btn, self.failed_btn, self.compare_btn):
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.PointingHandCursor)
        controls.addWidget(self.filter_edit, 1)
        controls.addWidget(self.refresh_btn)
        controls.addWidget(self.failed_btn)
        controls.addWidget(self.compare_btn)
        lv.addLayout(controls)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("iuTable")
        self.table.setHorizontalHeaderLabels(["KB", "Açıklama", "Kurulum Tarihi", "Kaynak", "Kaldırılabilir", "Durum"])
        self._table_style(self.table)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        from ui.widgets.empty_state import attach_empty_state
        self._empty = attach_empty_state(self.table, "list", self._empty_text)
        self._empty.clicked.connect(self.refresh_installed)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.cellDoubleClicked.connect(lambda row, col: self.remove_selected())
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 125)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 125)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setItemDelegate(InstalledRowDelegate(self.table))
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.horizontalHeader().sectionClicked.connect(self._header_sort)
        self._sort_col, self._sort_order = -1, Qt.AscendingOrder
        lv.addWidget(self.table, 1)
        body.addWidget(left, 1)

        self.detail = QFrame()
        self.detail.setObjectName("iuCard")
        self.detail.setFixedWidth(330)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        detail_layout.setSpacing(10)

        dh = QHBoxLayout()
        dh.setSpacing(10)
        dic = QLabel()
        dic.setPixmap(icons.pixmap("windows-color", "#1768E0", 26))
        dh.addWidget(dic)
        dht = QLabel("Güncelleme Ayrıntıları")
        dht.setObjectName("iuCardTitle")
        dh.addWidget(dht, 1)
        detail_layout.addLayout(dh)

        head = QHBoxLayout()
        self.detail_title = QLabel("Güncelleme seçin")
        self.detail_title.setObjectName("iuDetailTitle")
        head.addWidget(self.detail_title, 1)
        self.detail_badge = QLabel("Yüklü")
        self.detail_badge.setObjectName("iuBadge")
        self.detail_badge.setVisible(False)
        head.addWidget(self.detail_badge, 0, Qt.AlignVCenter)
        detail_layout.addLayout(head)

        # Eski metin etiketi mantık için korunur; görsel tasarımda anahtar/değer satırları gösterilir.
        self.detail_text = QLabel("Yüklü KB listesinden bir güncelleme seçtiğinizde ayrıntıları burada görebilirsiniz.")
        self.detail_text.setWordWrap(True)
        self.detail_text.setObjectName("iuDetailHint")
        detail_layout.addWidget(self.detail_text)

        self.detail_rows = {}
        self.detail_grid_widget = QWidget()
        gl = QVBoxLayout(self.detail_grid_widget)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(7)
        for key, cap in (("desc", "Açıklama"), ("date", "Kurulum Tarihi"), ("source", "Kaynak"), ("channel", "Kanal"), ("group", "Yayın Grubu"), ("kb", "KB Numarası")):
            r = QHBoxLayout()
            k = QLabel(cap)
            k.setObjectName("iuKey")
            v = QLabel("—")
            v.setObjectName("iuVal")
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            v.setWordWrap(True)
            r.addWidget(k)
            r.addStretch()
            r.addWidget(v)
            gl.addLayout(r)
            self.detail_rows[key] = v
        self.detail_grid_widget.setVisible(False)
        detail_layout.addWidget(self.detail_grid_widget)

        self.sec_remove_title = QLabel("Kaldırılabilirlik")
        self.sec_remove_title.setObjectName("iuSection")
        detail_layout.addWidget(self.sec_remove_title)
        self.remove_state_box, self.remove_state_icon, self.remove_state_title, self.remove_state_text = self._state_box()
        detail_layout.addWidget(self.remove_state_box)
        self.sec_status_title = QLabel("Durum")
        self.sec_status_title.setObjectName("iuSection")
        detail_layout.addWidget(self.sec_status_title)
        self.status_state_box, self.status_state_icon, self.status_state_title, self.status_state_text = self._state_box()
        detail_layout.addWidget(self.status_state_box)
        for w in (self.sec_remove_title, self.remove_state_box, self.sec_status_title, self.status_state_box):
            w.setVisible(False)

        warn_box = QFrame()
        warn_box.setObjectName("iuWarn")
        wl = QHBoxLayout(warn_box)
        wl.setContentsMargins(12, 10, 12, 10)
        wl.setSpacing(10)
        wi = QLabel()
        wi.setPixmap(icons.pixmap("warning", "#E08A12", 22, stroke=2.2))
        wl.addWidget(wi, 0, Qt.AlignTop)
        warning = QLabel("Kaldırma işleminden önce sistem geri yükleme noktası oluşturulur. İşlem tamamlandıktan sonra sistemi yeniden başlatmanız gerekebilir.")
        warning.setObjectName("iuWarnText")
        warning.setWordWrap(True)
        wl.addWidget(warning, 1)
        detail_layout.addWidget(warn_box)
        detail_layout.addStretch(1)

        self.remove_btn = QPushButton("  Güncellemeyi Kaldır")
        self.remove_btn.setObjectName("iuRemove")
        self.remove_btn.setIcon(self._ico("trash", "#FFFFFF"))
        self.remove_btn.setIconSize(QSize(18, 18))
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.remove_btn.setEnabled(False)
        detail_layout.addWidget(self.remove_btn)
        body.addWidget(self.detail)
        root.addLayout(body, 1)

        strip = QFrame()
        strip.setObjectName("iuInfo")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(14, 10, 14, 10)
        sl.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("info-fill", "#1768E0", 20))
        sl.addWidget(ic)
        self.info = QLabel("Yüklü KB listesi hazırlanıyor…")
        self.info.setObjectName("iuInfoText")
        self.info.setWordWrap(True)
        sl.addWidget(self.info, 1)
        root.addWidget(strip)

    @staticmethod
    def _state_box():
        box = QFrame()
        box.setObjectName("iuState")
        row = QHBoxLayout(box)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)
        ic = QLabel()
        ic.setFixedSize(30, 30)
        ic.setAlignment(Qt.AlignCenter)
        row.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel("")
        t.setObjectName("iuStateTitle")
        d = QLabel("")
        d.setObjectName("iuStateText")
        d.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(d)
        row.addLayout(col, 1)
        return box, ic, t, d

    @staticmethod
    def _table_style(table):
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(48)
        table.setShowGrid(False)
        table.setMouseTracking(True)
        table.setFrameShape(QFrame.NoFrame)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignVCenter | Qt.AlignLeft)

    def _apply_styles(self):
        up, down = self._arrow_urls()
        self.setStyleSheet("""
        QWidget#installedPage { background: #F3F7FC; }
        QLabel { background: transparent; }
        QPushButton#iuPrimary {
            background: #1768E0; color: #FFFFFF; border: none; border-radius: 10px;
            padding: 0 14px; font-size: 13px; font-weight: 700; min-height: 44px; max-height: 44px;
        }
        QPushButton#iuPrimary:hover { background: #135BC4; }
        QPushButton#iuPrimary:disabled { background: #A9C4EE; }
        QPushButton#iuSecondary {
            background: #FFFFFF; color: #1768E0; border: 1px solid #CBD9EC; border-radius: 10px;
            padding: 0 14px; font-size: 13px; font-weight: 700; min-height: 44px; max-height: 44px;
        }
        QPushButton#iuSecondary:hover { background: #F1F6FD; border-color: #9DB9E6; }
        QPushButton#iuSecondary:disabled { color: #8A98B0; background: #F6F9FE; border: 1px solid #E1E8F2; }
        QFrame#iuStat, QFrame#iuCard { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px; }
        QLabel#iuStatTitle { color: #14213D; font-size: 14px; font-weight: 700; }
        QLabel#iuStatValue { color: #0A1F44; font-size: 28px; font-weight: 800; }
        QLabel#iuStatNote { color: #5F7090; font-size: 12px; }
        QLabel#iuCardTitle { color: #14213D; font-size: 16px; font-weight: 700; }
        QLineEdit#iuSearch {
            background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 10px;
            padding: 0 14px 0 6px; font-size: 13px; color: #14213D; min-height: 44px; max-height: 44px;
            selection-background-color: #1768E0;
        }
        QLineEdit#iuSearch:focus { border: 1px solid #1768E0; }
        QTableWidget#iuTable { background: #FFFFFF; border: none; outline: none; gridline-color: transparent; }
        QTableWidget#iuTable QHeaderView::section {
            background: #F4F8FD; color: #3A4D70; border: none; padding: 12px 8px;
            font-size: 12px; font-weight: 700;
        }
        QTableWidget#iuTable QHeaderView::section:first { padding-left: 46px; }
        QTableWidget#iuTable QHeaderView::up-arrow { image: url(%UP%); width: 10px; height: 10px; }
        QTableWidget#iuTable QHeaderView::down-arrow { image: url(%DOWN%); width: 10px; height: 10px; }
        QLabel#iuDetailTitle { color: #14213D; font-size: 20px; font-weight: 700; }
        QLabel#iuDetailHint { color: #5F7090; font-size: 12px; }
        QLabel#iuBadge { background: #E3F6EA; color: #15803D; border-radius: 12px; padding: 4px 14px; font-size: 12px; font-weight: 700; }
        QLabel#iuKey { color: #7C8BA5; font-size: 12px; }
        QLabel#iuVal { color: #14213D; font-size: 12px; font-weight: 500; }
        QLabel#iuSection { color: #14213D; font-size: 14px; font-weight: 700; margin-top: 4px; }
        QFrame#iuState { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 10px; }
        QLabel#iuStateTitle { color: #14213D; font-size: 13px; font-weight: 600; }
        QLabel#iuStateText { color: #7C8BA5; font-size: 11px; }
        QFrame#iuWarn { background: #FFF6E5; border: 1px solid #F8DDA8; border-radius: 10px; }
        QLabel#iuWarnText { color: #8A5A0B; font-size: 11px; }
        QPushButton#iuRemove {
            background: #D93C3C; color: #FFFFFF; border: none; border-radius: 10px;
            font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
        }
        QPushButton#iuRemove:hover { background: #C22F2F; }
        QPushButton#iuRemove:disabled { background: #E9EEF5; color: #A3AFC2; }
        QFrame#iuInfo { background: #EEF4FE; border: 1px solid #D5E3F8; border-radius: 10px; }
        QLabel#iuInfoText { color: #3A5478; font-size: 12px; }
        """.replace("%UP%", up).replace("%DOWN%", down))

    @staticmethod
    def _arrow_urls():
        import os, tempfile
        out = []
        for name, flip in (("up", True), ("down", False)):
            try:
                pm = icons.pixmap("chevron-down", "#4B5E7C", 12, stroke=2.4)
                if flip:
                    pm = pm.transformed(QTransform().scale(1, -1))
                path = os.path.join(tempfile.gettempdir(), f"wubc_inst_{name}.png")
                pm.save(path, "PNG")
                out.append(path.replace("\\", "/"))
            except Exception:
                out.append("")
        return out[0], out[1]

    # ── Yalnızca görünüm yardımcıları ──
    def _header_sort(self, column: int) -> None:
        if column == self._sort_col:
            self._sort_order = Qt.DescendingOrder if self._sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self._sort_col, self._sort_order = column, Qt.AscendingOrder
        self.table.sortItems(column, self._sort_order)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSortIndicator(column, self._sort_order)
        self._filter(self.filter_edit.text())

    def _tracker_info(self, kb: str):
        try:
            from services.build_tracker_service import BuildTrackerService as _B
            records, _u, _f = _B.load_cache()
        except Exception:
            return "—", "—"
        number = re.sub(r"\D", "", kb or "").lstrip("0")
        for rec in records or []:
            if number and re.sub(r"\D", "", rec.kb_number or "").lstrip("0") == number:
                return rec.channel or "—", rec.release_group or "—"
        return "—", "—"

    def _update_stats(self, items):
        total = len(items)
        removable = sum(1 for i in items if getattr(i, "removable", False))
        invalid = sum(1 for i in items if not re.fullmatch(r"KB\d+", (getattr(i, "kb", "") or ""), re.I))
        self.stat_total.setText(str(total))
        self.stat_total_note.setText("Bilgisayarınızda yüklü güncelleştirme.")
        self.stat_removable.setText(str(removable))
        self.stat_removable_note.setText("Kaldırılabilir güncelleştirme bulunamadı." if not removable else "Güvenle kaldırılabilir güncelleştirme.")
        self.stat_check.setText(str(invalid))
        self.stat_check_note.setText("Özel bir işlem gerekmiyor." if not invalid else "Geçerli KB numarası içermeyen kayıtlar var.")

    def _update_detail_view(self, row: int) -> None:
        has = row >= 0
        for w in (self.detail_grid_widget, self.sec_remove_title, self.remove_state_box, self.sec_status_title, self.status_state_box):
            w.setVisible(has)
        self.detail_badge.setVisible(has)
        self.detail_text.setVisible(not has)
        if not has:
            return
        kb = self._cell(row, 0)
        channel, group = self._tracker_info(kb)
        values = {"desc": self._cell(row, 1), "date": self._cell(row, 2), "source": self._cell(row, 3), "channel": channel, "group": group, "kb": kb}
        for key, val in values.items():
            self.detail_rows[key].setText(val or "—")
        removable = self._cell(row, 4).lower() == "evet"
        if removable:
            self.remove_state_icon.setPixmap(icons.pixmap("check-circle", "#15803D", 26, stroke=2.2))
            self.remove_state_title.setText("Kaldırılabilir")
            self.remove_state_text.setText("Bu güncelleme kaldırılabilir.")
        else:
            self.remove_state_icon.setPixmap(icons.pixmap("x", "#6C7C93", 22, stroke=2.2))
            self.remove_state_title.setText("Kaldırılamaz")
            self.remove_state_text.setText("Bu güncelleme kaldırma için uygun değil.")
        self.status_state_icon.setPixmap(icons.pixmap("check-circle", "#15803D", 26, stroke=2.2))
        self.status_state_title.setText(self._cell(row, 5) or "Yüklü")
        self.status_state_text.setText("Güncelleme başarıyla yüklendi.")

    def _run(self, fn, done, button=None):
        if self._worker and self._worker.isRunning():
            return
        if button:
            button.setEnabled(False)
        self._worker = _Worker(fn, self)
        self._worker.done.connect(done)
        self._worker.failed.connect(lambda e: self._worker_error(e, button))
        self._worker.finished.connect(lambda: button.setEnabled(True) if button else None)
        self._worker.start()

    def _worker_error(self, message, button=None):
        if button:
            button.setEnabled(True)
        QMessageBox.warning(self, "İşlem başarısız", message)

    def _empty_text(self):
        if getattr(self, "_items", None):
            return ("Bu aramada sonuç yok", "Arama ya da süzgeçleri değiştirmeyi deneyin.", None)
        return ("Yüklü güncelleme listesi boş", "Bu bilgisayardaki güncellemeleri listelemek için yenileyin.", "Yenile")

    def refresh_installed(self):
        self._run(WindowsUpdateService.installed_updates, self._loaded, self.refresh_btn)

    def _loaded(self, items):
        self._items = items
        self._update_stats(items)
        self._render(items)
        self.info.setText(f"{len(items)} yüklü KB bulundu. Bir güncellemeyi seçin; ayrıntıları sağ panelde görün ve kaldırmak için 'Kaldır' düğmesini kullanın. Çift tıklama da kaldırma işlemini başlatır.")

    def _render(self, items):
        self.table.setRowCount(0)
        for item in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [item.kb, item.description, item.installed_on, "Windows Update", "Evet" if item.removable else "Hayır", "Yüklü"]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.table.clearSelection()
        self._clear_detail()
        self._filter(self.filter_edit.text())

    def _filter(self, text):
        q = text.strip().lower()
        for row in range(self.table.rowCount()):
            visible = not q or any(q in ((self.table.item(row, col).text() if self.table.item(row, col) else "").lower()) for col in range(self.table.columnCount()))
            self.table.setRowHidden(row, not visible)

    def _show_selected(self):
        row = self.table.currentRow()
        if row < 0:
            self._clear_detail()
            return
        kb = self._cell(row, 0)
        desc = self._cell(row, 1)
        date = self._cell(row, 2)
        source = self._cell(row, 3)
        removable = self._cell(row, 4)
        status = self._cell(row, 5)
        self.detail_title.setText(kb or "Güncelleme")
        self.detail_text.setText(
            f"Açıklama: {desc or '—'}\n\n"
            f"Kurulum tarihi: {date or '—'}\n\n"
            f"Kaynak: {source or '—'}\n\n"
            f"Kaldırılabilir: {removable or '—'}\n\n"
            f"Durum: {status or '—'}"
        )
        self.remove_btn.setEnabled(removable.lower() == "evet")
        self._update_detail_view(row)

    def _clear_detail(self):
        self.detail_title.setText("Güncelleme seçin")
        self.detail_text.setText("Yüklü KB listesinden bir güncelleme seçtiğinizde ayrıntıları burada görebilirsiniz.")
        self.remove_btn.setEnabled(False)
        self._update_detail_view(-1)

    def _cell(self, row, col):
        item = self.table.item(row, col)
        return item.text().strip() if item else ""

    @staticmethod
    def _is_admin():
        if not hasattr(ctypes, "windll"):
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def remove_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Güncelleme seçin", "Önce kaldırmak istediğiniz KB güncellemesini seçin.")
            return
        kb = self._cell(row, 0)
        removable = self._cell(row, 4).lower() == "evet"
        if not kb or not re.fullmatch(r"KB\d+", kb, re.I):
            QMessageBox.warning(self, "Geçersiz KB", "Seçili satır geçerli bir KB numarası içermiyor.")
            return
        if not removable:
            QMessageBox.warning(self, "Kaldırılamaz", f"{kb} Windows tarafından kaldırılabilir olarak işaretlenmemiş.")
            return
        if not self._is_admin():
            QMessageBox.warning(self, "Yönetici yetkisi gerekli", "KB kaldırmak için programı Yönetici olarak çalıştırmanız gerekir.")
            return

        answer = QMessageBox.warning(
            self, "Güncellemeyi kaldır",
            f"{kb} güncellemesini kaldırmak istediğinizden emin misiniz?\n\n"
            "Kaldırma işleminden önce sistem geri yükleme noktası oluşturulacaktır. "
            "Geri yükleme noktası oluşturulamazsa kaldırma işlemi yapılmayacaktır.\n\n"
            "Devam etmek istiyor musunuz?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        self.remove_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.info.setText(f"{kb} için sistem geri yükleme noktası oluşturuluyor…")
        self._run(
            WindowsUpdateService.create_restore_point,
            lambda result, kb=kb: self._restore_done(result, kb),
        )

    def _restore_done(self, result, kb):
        ok, message = result
        if not ok:
            self.info.setText("Geri yükleme noktası oluşturulamadı; kaldırma işlemi engellendi.")
            QMessageBox.critical(self, "Kaldırma engellendi", "Geri yükleme noktası oluşturulamadığı için güncelleme kaldırılmadı.\n\n" + message)
            self.refresh_btn.setEnabled(True)
            self._show_selected()
            return
        self.info.setText(f"Geri yükleme noktası oluşturuldu. {kb} kaldırılıyor…")
        self._run(
            lambda: WindowsUpdateService.uninstall_update(kb),
            lambda result, kb=kb: self._remove_done(result, kb),
        )

    def _remove_done(self, result, kb):
        ok, message = result
        if ok:
            QMessageBox.information(self, "Kaldırma tamamlandı", f"{kb} kaldırma işlemi tamamlandı.\n\n{message}\n\nGerekirse Windows'u yeniden başlatın.")
            self.info.setText(f"{kb} kaldırıldı. Liste yenileniyor…")
            self.refresh_installed()
        else:
            QMessageBox.critical(self, "Kaldırma başarısız", f"{kb} kaldırılamadı.\n\n{message}")
            self.info.setText("Kaldırma başarısız oldu. Güncelleme sistemde bırakıldı.")
            self.refresh_btn.setEnabled(True)
            self._show_selected()

    def scan_failed(self):
        self._run(WindowsUpdateService.failed_updates, self._failed_loaded, self.failed_btn)

    def _failed_loaded(self, events):
        if not events:
            QMessageBox.information(self, "Başarısız güncellemeler", "Son 30 günde Windows Update Client kayıtlarında hata veya uyarı bulunamadı.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Başarısız Windows Update olayları")
        dlg.resize(900, 600)
        layout = QVBoxLayout(dlg)
        output = QTextEdit()
        output.setReadOnly(True)
        output.setPlainText("\n\n".join(events[:50]))
        layout.addWidget(output)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()

    def compare_tracker(self):
        self._run(lambda: BuildTrackerService().fetch()[0], self._tracker_loaded, self.compare_btn)

    def _tracker_loaded(self, records):
        installed = {re.sub(r"\D", "", x.kb).lstrip("0") for x in self._items}
        missing = []
        for rec in records[:100]:
            n = re.sub(r"\D", "", rec.kb_number or "").lstrip("0")
            if n and n not in installed:
                missing.append(rec)
        self.info.setText(f"Build Tracker: {len(records[:100])} kayıt incelendi • {len(missing)} KB bilgisayarda yüklü görünmüyor. Bunlar kesin eksik değildir; hedef Windows sürümü, build ve yerine geçme durumu ayrıca kontrol edilmelidir.")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
        super().closeEvent(event)
