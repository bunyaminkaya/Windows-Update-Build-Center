from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QProgressBar, QPushButton, QStyle, QStyledItemDelegate, QTabBar, QVBoxLayout,
    QWidget,
)

from ui import icons, styles
from ui.pages.system_update_page import SystemUpdatePage

_OK = {"Uygun", "Eşleşiyor", "Aynı veya daha yeni", "Hazır", "Bulundu"}
_WARN = {"Kontrol gerekli", "Yetersiz", "Yetersiz / kritik", "Destek dışı", "Bulunamadı"}
# Mockup'taki gösterim: Bilgi (mavi), Uygun (yeşil), Kontrol gerekli (turuncu)
_BASE_OK = {"Uygun", "Eşleşiyor", "Aynı veya daha yeni", "Hazır"}  # mevcut özet metniyle aynı sayım


def _kind(result: str) -> str:
    if result in _OK:
        return "ok"
    if result in _WARN:
        return "warn"
    return "info"


_PILL = {
    "ok": ("#E3F6EA", "#15803D", "Uygun", "check-circle"),
    "warn": ("#FFEFD6", "#C2680C", "Kontrol gerekli", "warning"),
    "info": ("#E6F0FF", "#1768E0", "Bilgi", "info-fill"),
}
_ROW_ICONS = {
    "Windows sürümü": ("windows-color", "#1768E0"),
    "Mevcut build": ("boxes", "#1768E0"),
    "Mimari": ("globe", "#1768E0"),
    "TPM 2.0": ("cpu", "#E08A12"),
    "Secure Boot": ("shield", "#E08A12"),
    "Disk alanı": ("save", "#1768E0"),
    "İşlemci": ("cpu", "#1768E0"),
    "RAM": ("list", "#1768E0"),
    "Güncelleme kanalı": ("cloud-outline", "#1768E0"),
    "Dil": ("globe", "#1768E0"),
    "Edition": ("windows-color", "#1768E0"),
}


class CompatRowDelegate(QStyledItemDelegate):
    """Uyumluluk tablosu çizimi: ikonlu kontrol adı, sonuç rozeti, satır kaydırmalı metinler."""

    ICON_W = 52

    def _flags(self):
        return Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        painter.fillRect(rect, QColor("#F6F9FE") if option.state & QStyle.State_MouseOver else QColor("#FFFFFF"))
        painter.setPen(QColor("#EDF1F6"))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        text = str(index.data(Qt.DisplayRole) or "")
        col = index.column()
        painter.setFont(option.font)
        if col == 0:
            name, color = _ROW_ICONS.get(text, ("info-outline", "#1768E0"))
            try:
                pix = icons.pixmap(name, color, 24, stroke=1.9)
                painter.drawPixmap(rect.left() + 14, rect.center().y() - 12, pix)
            except Exception:
                pass
            font = option.font
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#14213D"))
            painter.drawText(rect.adjusted(self.ICON_W, 4, -6, -4), self._flags(), text)
        elif col == 2:
            kind = _kind(text)
            bg, fg, _label, icon_name = _PILL[kind]
            font = option.font
            font.setBold(True)
            font.setPointSizeF(max(8.0, font.pointSizeF() - 0.7))
            painter.setFont(font)
            fm = QFontMetrics(font)
            width = fm.horizontalAdvance(text) + 46
            pill = QRectF(rect.left() + 8, rect.center().y() - 14, width, 28)
            path = QPainterPath()
            path.addRoundedRect(pill, 14, 14)
            painter.fillPath(path, QColor(bg))
            painter.drawPixmap(int(pill.left() + 10), int(pill.center().y() - 8), icons.pixmap(icon_name, fg, 16))
            painter.setPen(QColor(fg))
            painter.drawText(pill.adjusted(30, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, text)
        else:
            painter.setPen(QColor("#2A3A5C") if col == 1 else QColor("#4A5B7A"))
            painter.drawText(rect.adjusted(8, 4, -8, -4), self._flags(), text)
        painter.restore()

    def sizeHint(self, option, index):
        view = option.widget
        width = view.columnWidth(index.column()) if view is not None else 200
        col = index.column()
        if col == 2:
            return QSize(width, 40)
        left = self.ICON_W if col == 0 else 8
        fm = QFontMetrics(option.font)
        rect = fm.boundingRect(0, 0, max(40, width - left - 8), 2000, Qt.TextWordWrap, str(index.data(Qt.DisplayRole) or ""))
        return QSize(width, max(40, rect.height() + 14))


class _SummaryCard(QFrame):
    def __init__(self, kind: str, title: str, subtitle: str, icon_name: str, accent: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("compatCard")
        self.setProperty("kind", kind)
        self.setProperty("active", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(92)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(14)
        tile = QLabel()
        tile.setObjectName("compatCardTile")
        tile.setProperty("kind", kind)
        tile.setFixedSize(52, 52)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap(icon_name, "#FFFFFF", 28, stroke=2.2))
        row.addWidget(tile)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel(title)
        self.title.setObjectName("compatCardTitle")
        self.title.setProperty("kind", kind)
        self.value = QLabel("0")
        self.value.setObjectName("compatCardValue")
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("compatCardSub")
        col.addWidget(self.title)
        col.addWidget(self.value)
        col.addWidget(self.sub)
        row.addLayout(col, 1)
        chev = QLabel()
        chev.setPixmap(icons.pixmap("chevron-right", "#7C8BA5", 18, stroke=2.2))
        row.addWidget(chev)
        self.on_click = None

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton and self.on_click:
            self.on_click(self.kind)


class CompatibilityPage(SystemUpdatePage):
    """Bilgisayar uyumluluğu ve donanım özellikleri için bağımsız sayfa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        for i in range(self.tabs.count() - 1, 0, -1):
            self.tabs.removeTab(i)
        # Bağımsız menü olduğu için ayrıca mavi sekme düğmesi gösterme.
        self.tabs.tabBar().setVisible(False)
        self.setObjectName("compatibilityPage")
        self._set_page_text()
        self._kind_filter = None
        self._rows_cache = []
        self._build_compat_view()

    def _set_page_text(self):
        from PySide6.QtWidgets import QLabel
        title = self.findChild(QLabel, "pageTitle")
        subtitle = self.findChild(QLabel, "pageSubtitle")
        if title:
            title.setText("Windows 11 Uyumluluğu")
        if subtitle:
            subtitle.setText("Bilgisayarınızın Windows 11 gereksinimlerini karşılayıp karşılamadığını kontrol edin.")
            subtitle.setWordWrap(True)

    # ── Yeni arayüz (yalnızca görünüm; mevcut widget'lar ve mantık aynen kullanılır) ──
    @staticmethod
    def _ico(name, color, size=36, stroke=2.0):
        return QIcon(icons.pixmap(name, color, size, stroke=stroke))

    def _build_compat_view(self):
        root = self.layout()
        self.tabs.setVisible(False)
        title = self.findChild(QLabel, "pageTitle")
        subtitle = self.findChild(QLabel, "pageSubtitle")
        # Eski başlık etiketlerini yeni üst bölüme taşı
        for w in (title, subtitle):
            root.removeWidget(w)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        tile = QLabel()
        tile.setObjectName("cpTile")
        tile.setFixedSize(56, 56)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap("monitor", "#1768E0", 40, stroke=1.8))
        header.addWidget(tile, 0, Qt.AlignTop)
        tb = QVBoxLayout()
        tb.setSpacing(2)
        tb.addWidget(title)
        tb.addWidget(subtitle)
        header.addLayout(tb, 1)
        root.insertLayout(0, header)

        # Hedef güncelleme kartı (mevcut giriş ve düğmeler yeniden kullanılır)
        target_card = QFrame()
        target_card.setObjectName("cpCard")
        tl = QVBoxLayout(target_card)
        tl.setContentsMargins(18, 14, 18, 16)
        tl.setSpacing(10)
        tt = QLabel("Hedef Güncelleme")
        tt.setObjectName("cpCardTitle")
        tl.addWidget(tt)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.compat_target.setObjectName("cpTarget")
        self.compat_target.addAction(self._ico("search", "#4B5E7C"), self.compat_target.ActionPosition.LeadingPosition)
        self.compat_check.setObjectName("cpPrimary")
        self.compat_check.setText("  Sistemi ve Hedefi Kontrol Et")
        self.compat_check.setIcon(self._ico("shield", "#FFFFFF"))
        self.compat_latest.setObjectName("cpSecondary")
        self.compat_latest.setText("  Build Tracker Hedefini Al")
        self.compat_latest.setIcon(self._ico("gear-outline", "#1768E0"))
        for b in (self.compat_check, self.compat_latest):
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.compat_target, 1)
        row.addWidget(self.compat_check)
        row.addWidget(self.compat_latest)
        tl.addLayout(row)
        root.insertWidget(1, target_card)

        # Özet kartları
        cards = QHBoxLayout()
        cards.setSpacing(14)
        self.card_ok = _SummaryCard("ok", "Uyumlu", "kontrol uygun durumda", "check", "#15803D")
        self.card_warn = _SummaryCard("warn", "Kontrol Gerekli", "kontrol için inceleme gerekiyor", "warning", "#E08A12")
        self.card_info = _SummaryCard("info", "Bilgi", "bilgi amaçlı kayıt", "info-fill", "#1768E0")
        for c in (self.card_ok, self.card_warn, self.card_info):
            c.on_click = self._toggle_kind_filter
            cards.addWidget(c, 1)
        root.insertLayout(2, cards)

        # Gövde: liste + özet paneli
        body = QHBoxLayout()
        body.setSpacing(14)
        list_card = QFrame()
        list_card.setObjectName("cpCard")
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.setSpacing(0)
        lh = QHBoxLayout()
        lh.setContentsMargins(18, 14, 18, 10)
        lh.setSpacing(16)
        lt = QLabel("Uyumluluk Kontrol Listesi")
        lt.setObjectName("cpCardTitle")
        lh.addWidget(lt)
        lh.addStretch()
        for text, color in (("Uyumlu", "#22A06B"), ("Kontrol Gerekli", "#F2A33A"), ("Bilgi", "#1768E0")):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 12px; background: transparent;")
            lab = QLabel(text)
            lab.setObjectName("cpLegend")
            lh.addWidget(dot)
            lh.addWidget(lab)
        sep = QFrame()
        sep.setObjectName("cpDivider")
        sep.setFixedSize(1, 24)
        lh.addWidget(sep)
        self.check_count = QLabel("0 kontrol")
        self.check_count.setObjectName("cpLegend")
        lh.addWidget(self.check_count)
        lc.addLayout(lh)

        t = self.compat_table
        t.setObjectName("compatTable")
        t.setAlternatingRowColors(False)
        t.setShowGrid(False)
        t.setMouseTracking(True)
        t.setFrameShape(QFrame.NoFrame)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setWordWrap(True)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        h = t.horizontalHeader()
        h.setStretchLastSection(True)
        h.setDefaultAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        for col, width in ((0, 195), (1, 225), (2, 150)):
            h.setSectionResizeMode(col, QHeaderView.Fixed)
            h.resizeSection(col, width)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        t.setItemDelegate(CompatRowDelegate(t))
        tw = QHBoxLayout()
        tw.setContentsMargins(14, 0, 14, 14)
        tw.addWidget(t)
        lc.addLayout(tw, 1)
        body.addWidget(list_card, 1)

        # Sağ: Uyumluluk Özeti
        side = QFrame()
        side.setObjectName("cpCard")
        side.setFixedWidth(310)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 16, 16, 16)
        sv.setSpacing(12)
        st = QLabel("Uyumluluk Özeti")
        st.setObjectName("cpCardTitle")
        sv.addWidget(st)

        self.status_box = QFrame()
        self.status_box.setObjectName("cpStatus")
        self.status_box.setProperty("kind", "warn")
        sb = QHBoxLayout(self.status_box)
        sb.setContentsMargins(14, 12, 14, 12)
        sb.setSpacing(12)
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(46, 46)
        self.status_icon.setAlignment(Qt.AlignCenter)
        sb.addWidget(self.status_icon, 0, Qt.AlignTop)
        sc = QVBoxLayout()
        sc.setSpacing(3)
        self.status_title = QLabel("")
        self.status_title.setObjectName("cpStatusTitle")
        self.status_title.setProperty("kind", "warn")
        self.status_text = QLabel("")
        self.status_text.setObjectName("cpStatusText")
        self.status_text.setWordWrap(True)
        sc.addWidget(self.status_title)
        sc.addWidget(self.status_text)
        sb.addLayout(sc, 1)
        sv.addWidget(self.status_box)

        prog = QFrame()
        prog.setObjectName("cpInner")
        pl = QVBoxLayout(prog)
        pl.setContentsMargins(14, 12, 14, 14)
        pl.setSpacing(8)
        self.progress_label = QLabel("0 / 0 uygun veya bilgilendirici")
        self.progress_label.setObjectName("cpProgressText")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        pl.addWidget(self.progress_label)
        pl.addWidget(self.progress)
        sv.addWidget(prog)

        steps = QFrame()
        steps.setObjectName("cpInner")
        stl = QVBoxLayout(steps)
        stl.setContentsMargins(14, 12, 14, 12)
        stl.setSpacing(8)
        stt = QLabel("Önerilen adımlar")
        stt.setObjectName("cpStepsTitle")
        stl.addWidget(stt)
        self.steps_layout = QVBoxLayout()
        self.steps_layout.setSpacing(10)
        stl.addLayout(self.steps_layout)
        sv.addWidget(steps)

        self.export_compat_btn = QPushButton("  Raporu Dışa Aktar")
        self.export_compat_btn.setObjectName("cpSecondary")
        self.export_compat_btn.setIcon(self._ico("download", "#1768E0"))
        self.export_compat_btn.setIconSize(QSize(18, 18))
        self.export_compat_btn.setCursor(Qt.PointingHandCursor)
        self.export_compat_btn.clicked.connect(self._export_compat_report)
        sv.addWidget(self.export_compat_btn)
        sv.addStretch()
        body.addWidget(side)
        root.insertLayout(3, body)

        # Alt bilgi şeridi: mevcut compat_summary etiketi
        strip = QFrame()
        strip.setObjectName("cpInfo")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(14, 10, 14, 10)
        sl.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("info-fill", "#1768E0", 20))
        sl.addWidget(ic)
        self.compat_summary.setObjectName("cpInfoText")
        self.compat_summary.setWordWrap(True)
        sl.addWidget(self.compat_summary, 1)
        root.addWidget(strip)
        root.setStretch(3, 1)

        self._apply_compat_styles()
        if self.compat_table.rowCount():
            self._update_view(self._rows_cache)

    def _apply_compat_styles(self):
        self.setStyleSheet(styles.qss("""
            QWidget#compatibilityPage { background: #F3F7FC; }
            QLabel { background: transparent; }
            QLabel#cpTile { background: transparent; }
            QFrame#cpCard { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px; }
            QLabel#cpCardTitle { color: #14213D; font-size: 17px; font-weight: 700; }
            QLabel#cpLegend { color: #3A4D70; font-size: 12px; }
            QFrame#cpDivider { background: #DCE5F1; border: none; }
            QLineEdit#cpTarget {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 10px;
                padding: 0 14px 0 6px; font-size: 13px; color: #14213D;
                min-height: 46px; max-height: 46px; selection-background-color: @BLUE@;
            }
            QLineEdit#cpTarget:focus { border: 1px solid @BLUE@; }
            QPushButton#cpPrimary {
                background: @BLUE@; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 0 20px; font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
            }
            QPushButton#cpPrimary:hover { background: #135BC4; }
            QPushButton#cpPrimary:disabled { background: #A9C4EE; }
            QPushButton#cpSecondary {
                background: #FFFFFF; color: @BLUE@; border: 1px solid #CBD9EC; border-radius: 10px;
                padding: 0 20px; font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
            }
            QPushButton#cpSecondary:hover { background: #F1F6FD; border-color: #9DB9E6; }
            QPushButton#cpSecondary:disabled { color: #8A98B0; background: #F6F9FE; border: 1px solid #E1E8F2; }
            QFrame#compatCard { border-radius: 14px; border: 1px solid #DCE5F1; background: #FFFFFF; }
            QFrame#compatCard[kind="ok"] { background: #EAF8F0; border-color: #CBEBD9; }
            QFrame#compatCard[kind="warn"] { background: #FFF5E5; border-color: #FBDFAE; }
            QFrame#compatCard[kind="info"] { background: #EAF2FE; border-color: #CFE0F8; }
            QFrame#compatCard[active="true"] { border: 2px solid @BLUE@; }
            QLabel#compatCardTile { border-radius: 26px; }
            QLabel#compatCardTile[kind="ok"] { background: #22A06B; }
            QLabel#compatCardTile[kind="warn"] { background: #F2A33A; }
            QLabel#compatCardTile[kind="info"] { background: @BLUE@; }
            QLabel#compatCardTitle { font-size: 15px; font-weight: 700; }
            QLabel#compatCardTitle[kind="ok"] { color: #15803D; }
            QLabel#compatCardTitle[kind="warn"] { color: #C2680C; }
            QLabel#compatCardTitle[kind="info"] { color: @BLUE@; }
            QLabel#compatCardValue { color: #0A1F44; font-size: 28px; font-weight: 800; }
            QLabel#compatCardSub { color: #5F7090; font-size: 12px; }
            QTableWidget#compatTable { background: #FFFFFF; border: none; outline: none; gridline-color: transparent; }
            QTableWidget#compatTable QHeaderView::section {
                background: #F4F8FD; color: #3A4D70; border: none; padding: 11px 8px;
                font-size: 12px; font-weight: 700;
            }
            QTableWidget#compatTable QHeaderView::section:first { padding-left: 52px; }
            QFrame#cpStatus { border-radius: 12px; }
            QFrame#cpStatus[kind="warn"] { background: #FFF5E5; border: 1px solid #FBDFAE; }
            QFrame#cpStatus[kind="ok"] { background: #EAF8F0; border: 1px solid #CBEBD9; }
            QLabel#cpStatusTitle { font-size: 16px; font-weight: 700; }
            QLabel#cpStatusTitle[kind="warn"] { color: #D4800B; }
            QLabel#cpStatusTitle[kind="ok"] { color: #15803D; }
            QLabel#cpStatusText { color: #5F7090; font-size: 12px; }
            QFrame#cpInner { background: #FFFFFF; border: 1px solid #E3EAF4; border-radius: 12px; }
            QLabel#cpProgressText { color: #14213D; font-size: 14px; font-weight: 600; }
            QLabel#cpStepsTitle { color: #14213D; font-size: 14px; font-weight: 700; }
            QLabel#cpStepText { color: #3A4D70; font-size: 12px; }
            QLabel#cpStepNum { background: #FDE9C8; color: #D4800B; border-radius: 12px; font-weight: 700; font-size: 12px; }
            QProgressBar { background: #E4EBF5; border: none; border-radius: 5px; }
            QProgressBar::chunk { background: @BLUE@; border-radius: 5px; }
            QFrame#cpInfo { background: #EEF4FE; border: 1px solid #D5E3F8; border-radius: 10px; }
            QLabel#cpInfoText { color: #3A5478; font-size: 12px; background: transparent; border: none; padding: 0; }
        """))

    _STEP_HINTS = {
        "TPM 2.0": "TPM 2.0 durumunu BIOS/UEFI üzerinden kontrol edin.",
        "Secure Boot": "Secure Boot desteğini doğrulayın.",
        "Disk alanı": "Disk alanını en az 20 GB boş olacak şekilde artırın.",
        "RAM": "Bellek miktarının Windows gereksinimini karşıladığını kontrol edin.",
        "Mimari": "Paket mimarisinin sisteminizle eşleştiğini doğrulayın.",
    }

    def _render_compat(self, rows):
        # Mevcut mantık: tabloyu ve özet metnini doldurur.
        super()._render_compat(rows)
        self._rows_cache = list(rows)
        if hasattr(self, "card_ok"):
            self._update_view(self._rows_cache)

    def _update_view(self, rows):
        kinds = [_kind(str(r[2])) if len(r) > 2 else "info" for r in rows]
        ok_n, warn_n, info_n = kinds.count("ok"), kinds.count("warn"), kinds.count("info")
        self.card_ok.value.setText(str(ok_n))
        self.card_warn.value.setText(str(warn_n))
        self.card_info.value.setText(str(info_n))
        self.check_count.setText(f"{len(rows)} kontrol")
        good = sum(1 for r in rows if len(r) > 2 and str(r[2]) in _BASE_OK)
        self.progress.setRange(0, max(1, len(rows)))
        self.progress.setValue(good)
        self.progress_label.setText(f"{good} / {len(rows)} uygun veya bilgilendirici")
        level = "warn" if warn_n else "ok"
        for w in (self.status_box, self.status_title):
            w.setProperty("kind", level)
            w.style().unpolish(w)
            w.style().polish(w)
        if warn_n:
            self.status_title.setText("Bazı kontroller gerekiyor")
            self.status_text.setText("Sisteminizin genel olarak uyumlu olduğu görülüyor, ancak bazı kontroller için ek inceleme gerekiyor.")
            self.status_icon.setStyleSheet("background: #FDE9C8; border-radius: 23px;")
            self.status_icon.setPixmap(icons.pixmap("warning", "#E08A12", 26, stroke=2.2))
        else:
            self.status_title.setText("Sistem uyumlu görünüyor")
            self.status_text.setText("Tüm temel kontroller uygun veya bilgilendirici durumda.")
            self.status_icon.setStyleSheet("background: #CBEBD9; border-radius: 23px;")
            self.status_icon.setPixmap(icons.pixmap("check-circle", "#15803D", 26, stroke=2.2))
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        warn_rows = [r for r, k in zip(rows, kinds) if k == "warn"]
        for i, r in enumerate(warn_rows[:4], 1):
            line = QHBoxLayout()
            line.setSpacing(10)
            num = QLabel(str(i))
            num.setObjectName("cpStepNum")
            num.setFixedSize(24, 24)
            num.setAlignment(Qt.AlignCenter)
            text = QLabel(self._STEP_HINTS.get(str(r[0]), f"{r[0]} sonucunu ayrıntılı inceleyin."))
            text.setObjectName("cpStepText")
            text.setWordWrap(True)
            line.addWidget(num, 0, Qt.AlignTop)
            line.addWidget(text, 1)
            holder = QWidget()
            holder.setLayout(line)
            self.steps_layout.addWidget(holder)
        if not warn_rows:
            text = QLabel("Ek işlem gerekmiyor.")
            text.setObjectName("cpStepText")
            self.steps_layout.addWidget(text)
        self._apply_kind_filter()

    def _toggle_kind_filter(self, kind: str):
        self._kind_filter = None if self._kind_filter == kind else kind
        for c in (self.card_ok, self.card_warn, self.card_info):
            c.setProperty("active", self._kind_filter == c.kind)
            c.style().unpolish(c)
            c.style().polish(c)
        self._apply_kind_filter()

    def _apply_kind_filter(self):
        shown = 0
        for r in range(self.compat_table.rowCount()):
            item = self.compat_table.item(r, 2)
            kind = _kind(item.text()) if item else "info"
            hide = bool(self._kind_filter and kind != self._kind_filter)
            self.compat_table.setRowHidden(r, hide)
            shown += 0 if hide else 1
        self.check_count.setText(f"{shown} kontrol")

    def _export_compat_report(self):
        t = self.compat_table
        if not t.rowCount():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Raporu kaydet", "Uyumluluk_Raporu.txt", "Metin dosyası (*.txt)")
        if not path:
            return
        lines = ["Windows Update & Build Center — Windows 11 Uyumluluğu", ""]
        for r in range(t.rowCount()):
            cells = [t.item(r, c).text() if t.item(r, c) else "" for c in range(4)]
            lines.append(f"{cells[0]}: {cells[1]} — {cells[2]} ({cells[3]})")
        lines += ["", self.compat_summary.text()]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
