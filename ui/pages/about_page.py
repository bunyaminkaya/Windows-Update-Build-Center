from __future__ import annotations

import re
import webbrowser

from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QScrollArea,
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from app.version import APP_NAME, APP_VERSION, RELEASE_NOTES
from app.paths import ICON_DIR
from ui import icons, styles
from services.build_history_service import BuildHistoryService


class UpdateHistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Güncelleme Geçmişi")
        self.resize(1180, 760)
        self.setMinimumSize(900, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Güncelleme Geçmişi")
        title.setObjectName("historyTitle")
        subtitle = QLabel("Build Tracker kontrolleri ve her kontrolde bulunan yeni kayıtlar")
        subtitle.setObjectName("historySubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        refresh = QPushButton("Yenile")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.reload)
        header.addWidget(refresh, 0, Qt.AlignBottom)
        root.addLayout(header)

        self.summary_layout = QHBoxLayout()
        self.summary_layout.setSpacing(10)
        self.summary_cards: dict[str, tuple[QLabel, QLabel]] = {}
        for key, title_text in (("today", "Bugün"), ("week", "Bu Hafta"), ("month", "Bu Ay")):
            card = QFrame()
            card.setObjectName("historyStatCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 12, 15, 12)
            caption = QLabel(title_text)
            caption.setObjectName("historyStatTitle")
            value = QLabel("0 yeni kayıt")
            value.setObjectName("historyStatValue")
            note = QLabel("0 kontrol")
            note.setObjectName("historyStatNote")
            card_layout.addWidget(caption)
            card_layout.addWidget(value)
            card_layout.addWidget(note)
            self.summary_layout.addWidget(card, 1)
            self.summary_cards[key] = (value, note)
        root.addLayout(self.summary_layout)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("historyTable")
        self.table.setHorizontalHeaderLabels([
            "Kontrol Tarihi", "Durum", "Yeni Kayıt", "Toplam Kayıt", "Kaynak Kontrolü", "Bulunan Kayıtlar / Açıklama",
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(5, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.result_info = QLabel("")
        self.result_info.setObjectName("historyResultInfo")
        footer.addWidget(self.result_info, 1)
        close = QPushButton("Kapat")
        close.setObjectName("primaryButton")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

        self.setStyleSheet(styles.qss("""
            QDialog { background: #F5F8FC; }
            QLabel#historyTitle { color: #10213D; font-size: 23px; font-weight: 800; }
            QLabel#historySubtitle, QLabel#historyResultInfo { color: #6C7C93; font-size: 12px; }
            QFrame#historyStatCard { background: #FFFFFF; border: 1px solid #DCE5F0; border-radius: 10px; }
            QLabel#historyStatTitle { color: #6C7C93; font-size: 11px; font-weight: 700; }
            QLabel#historyStatValue { color: @BLUE@; font-size: 20px; font-weight: 800; }
            QLabel#historyStatNote { color: #7E8EA3; font-size: 10px; }
            QTableWidget#historyTable { background: #FFFFFF; border: 1px solid #DCE5F0; border-radius: 9px; outline: none; }
            QTableWidget#historyTable::item { padding: 7px; border-bottom: 1px solid #EDF1F6; }
            QTableWidget#historyTable::item:selected { background: #EAF3FF; color: #10213D; }
            QHeaderView::section { background: #F7F9FC; color: #53657D; border: none; border-bottom: 1px solid #DCE5F0; padding: 8px; font-size: 11px; font-weight: 700; }
        """))
        self.reload()

    @staticmethod
    def _display_stamp(value: str) -> str:
        try:
            from datetime import datetime
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
        return "  •  ".join(
            " / ".join(filter(None, [
                f"Build {record.get('build', '')}" if record.get("build") else "",
                str(record.get("kb") or ""),
                str(record.get("version") or ""),
                str(record.get("channel") or ""),
            ]))
            for record in records
        )

    def reload(self) -> None:
        summary = BuildHistoryService.summary()
        for key, (value, note) in self.summary_cards.items():
            stats = summary[key]
            value.setText(f"{stats['new']} yeni kayıt")
            failure_note = f" • {stats['failed']} başarısız" if stats["failed"] else ""
            note.setText(f"{stats['checks']} kontrol{failure_note}")

        entries = BuildHistoryService.load()
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            success = entry.get("status") == "success"
            values = [
                self._display_stamp(str(entry.get("checked_at", ""))),
                "Başarılı" if success else "Başarısız",
                str(entry.get("new_count", 0)),
                str(entry.get("total_count", 0)) if success else "—",
                str(entry.get("source_last_update") or "—"),
                self._details_text(entry),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setForeground(QBrush(QColor("#218A50" if success else "#C0392B")))
                if column == 2 and int(entry.get("new_count", 0) or 0) > 0:
                    item.setForeground(QBrush(QColor("#2167D5")))
                self.table.setItem(row, column, item)
            self.table.setRowHeight(row, 44)
        self.result_info.setText(f"Son {len(entries)} kontrol kaydı gösteriliyor. Geçmiş en fazla 500 kontrol saklar.")


class _ClickableFrame(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _icon_label(name, color, size, bg="#FFFFFF", stroke=1.9):
    label = QLabel()
    label.setPixmap(icons.pixmap(name, color, size, bg=bg, stroke=stroke))
    label.setFixedSize(size, size)
    return label


class AboutPage(QWidget):
    BLUE = "#1768E0"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # Arayüz (yalnızca görünüm)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("abScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("abContent")
        scroll.setWidget(content)
        outer.addWidget(scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(18)

        root.addLayout(self._build_header())
        root.addWidget(self._build_hero())

        self._columns = QBoxLayout(QBoxLayout.LeftToRight)
        self._columns.setSpacing(18)
        self._columns.addWidget(self._build_developer_card(), 5)
        self._columns.addWidget(self._build_features_card(), 6)
        root.addLayout(self._columns)
        root.addWidget(self._build_notes_card())

        root.addLayout(self._build_footer())
        root.addStretch(1)
        self._apply_styles()

    def _build_header(self):
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(_icon_label("info-fill", self.BLUE, 44, bg="#FFFFFF"), 0, Qt.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("Hakkında")
        title.setObjectName("abTitle")
        subtitle = QLabel("Program sürümü, geliştirici ve iletişim bilgileri.")
        subtitle.setObjectName("abSubtitle")
        subtitle.setWordWrap(True)
        box.addWidget(title)
        box.addWidget(subtitle)
        head.addLayout(box, 1)
        return head

    def _build_hero(self):
        card = QFrame()
        card.setObjectName("abCard")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(16)

        panel = QFrame()
        panel.setObjectName("abHeroPanel")
        pl = QHBoxLayout(panel)
        pl.setContentsMargins(26, 18, 26, 18)
        pl.setSpacing(26)
        logo = QLabel()
        logo.setFixedSize(150, 150)
        logo.setAlignment(Qt.AlignCenter)
        logo_path = ICON_DIR / "app_logo.png"
        if logo_path.exists():
            logo.setPixmap(QPixmap(str(logo_path)).scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        pl.addWidget(logo, 0, Qt.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(0)
        name1 = QLabel("Windows")
        name1.setObjectName("abHeroName")
        name2 = QLabel("Update & Build Center")
        name2.setObjectName("abHeroTagline")
        description = QLabel(
            "Windows güncellemelerini, build sürümlerini ve UUP paketlerini yönetmenize "
            "yardımcı olan kapsamlı bir masaüstü uygulamasıdır."
        )
        description.setObjectName("abHeroDesc")
        description.setWordWrap(True)
        description.setMaximumWidth(620)
        text.addStretch(1)
        text.addWidget(name1)
        text.addWidget(name2)
        text.addSpacing(10)
        text.addWidget(description)
        text.addStretch(1)
        pl.addLayout(text, 1)
        lay.addWidget(panel, 1)

        version_box = QFrame()
        version_box.setObjectName("abVersionBox")
        version_box.setFixedWidth(270)
        vb = QVBoxLayout(version_box)
        vb.setContentsMargins(20, 18, 20, 18)
        vb.setSpacing(6)
        vkey = QLabel("Sürüm")
        vkey.setObjectName("abVersionKey")
        version = QLabel(APP_VERSION)
        version.setObjectName("abVersionValue")
        status = QFrame()
        status.setObjectName("abStatusPill")
        sl = QHBoxLayout(status)
        sl.setContentsMargins(12, 7, 12, 7)
        sl.setSpacing(8)
        sl.addWidget(_icon_label("check-circle", "#1FA35C", 18, bg="#E3F6EA"))
        stable = QLabel("Kararlı")
        stable.setObjectName("abStatusText")
        sl.addWidget(stable)
        sl.addStretch(1)
        check_row = QHBoxLayout()
        check_row.setSpacing(10)
        check_row.addWidget(_icon_label("clock", "#6E7F99", 18, stroke=1.8), 0, Qt.AlignTop)
        self.last_check_label = QLabel("Son kontrol:\n—")
        self.last_check_label.setObjectName("abVersionNote")
        check_row.addWidget(self.last_check_label, 1)
        vb.addWidget(vkey)
        vb.addWidget(version)
        vb.addWidget(status)
        vb.addSpacing(4)
        vb.addLayout(check_row)
        vb.addStretch(1)
        lay.addWidget(version_box)
        return card

    def _card_header(self, icon_name, title, subtitle, color=None):
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_icon_label(icon_name, color or self.BLUE, 28, stroke=1.9), 0, Qt.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("abSectionTitle")
        s = QLabel(subtitle)
        s.setObjectName("abSectionSub")
        s.setWordWrap(True)
        box.addWidget(t)
        box.addWidget(s)
        row.addLayout(box, 1)
        return row

    def _build_developer_card(self):
        card = QFrame()
        card.setObjectName("abCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(16)
        v.addLayout(self._card_header("user", "Geliştirici", "Uygulamanın geliştirme sürecini yürüten kişi."))

        person = QHBoxLayout()
        person.setSpacing(18)
        avatar = QLabel("BK")
        avatar.setObjectName("abAvatar")
        avatar.setFixedSize(66, 66)
        avatar.setAlignment(Qt.AlignCenter)
        person.addWidget(avatar, 0, Qt.AlignVCenter)
        pb = QVBoxLayout()
        pb.setSpacing(3)
        name = QLabel("Bünyamin KAYA")
        name.setObjectName("abDevName")
        role = QLabel("Microsoft ve Windows Teknolojileri Uzmanı")
        role.setObjectName("abDevRole")
        pb.addWidget(name)
        pb.addWidget(role)
        person.addLayout(pb, 1)
        v.addLayout(person)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self._add_contact(grid, 0, "globe", "Web Sitesi", "bunyaminkaya.com", link=True)
        self._add_contact(grid, 1, "mail", "E-posta", "bunyaminkaya@gmail.com", link=True)
        self._add_contact(grid, 2, "code", "Mevcut Sürüm", APP_VERSION, link=False)
        grid.setColumnStretch(2, 1)
        v.addLayout(grid)
        rule = QFrame()
        rule.setObjectName("abRule")
        rule.setFixedHeight(1)
        v.addWidget(rule)
        support = QHBoxLayout()
        support.setSpacing(12)
        support.addWidget(_icon_label("message", self.BLUE, 26, bg="#EAF2FE", stroke=1.8), 0, Qt.AlignTop)
        support_text = QLabel(
            "<b>Destek ve geri bildirim</b><br>Hata bildirmek ya da öneride bulunmak için e-posta gönderebilirsiniz. "
            "Ayarlar > Gelişmiş bölümünden log ve sistem bilgisi içeren bir sorun bildirim paketi de oluşturabilirsiniz."
        )
        support_text.setObjectName("abFeatureDesc")
        support_text.setWordWrap(True)
        support.addWidget(support_text, 1)
        v.addLayout(support)
        v.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        web_btn = QPushButton("Web Sitesini Aç")
        web_btn.setObjectName("abPrimaryBtn")
        web_btn.setIcon(icons.icon("external", "#FFFFFF", 18, stroke=2.1))
        web_btn.setIconSize(QSize(18, 18))
        web_btn.setCursor(Qt.PointingHandCursor)
        web_btn.clicked.connect(lambda: webbrowser.open("https://bunyaminkaya.com"))
        mail_btn = QPushButton("E-posta Gönder")
        mail_btn.setObjectName("abGhostBtn")
        mail_btn.setIcon(icons.icon("mail", self.BLUE, 18, stroke=2.0))
        mail_btn.setIconSize(QSize(18, 18))
        mail_btn.setCursor(Qt.PointingHandCursor)
        mail_btn.clicked.connect(lambda: webbrowser.open("mailto:bunyaminkaya@gmail.com"))
        update_btn = QPushButton("Güncellemeleri Denetle")
        update_btn.setObjectName("abGhostBtn")
        update_btn.setIcon(icons.icon("refresh", self.BLUE, 18, stroke=2.0))
        update_btn.setIconSize(QSize(18, 18))
        update_btn.setCursor(Qt.PointingHandCursor)
        update_btn.clicked.connect(lambda: self.window().check_app_update(silent=False) if hasattr(self.window(), "check_app_update") else None)
        actions.addWidget(web_btn)
        actions.addWidget(mail_btn)
        actions.addWidget(update_btn)
        actions.addStretch(1)
        v.addLayout(actions)
        return card

    def _build_features_card(self):
        card = QFrame()
        card.setObjectName("abCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(12)
        v.addLayout(self._card_header("star-fill", "Program Özellikleri", "Bu programın öne çıkan başlıca özellikleri."))
        v.addSpacing(2)
        features = [
            ("cloud-down", "Güncelleme Merkezi", "Windows ve diğer Microsoft ürünleri için güncellemeleri kontrol eder, indirir ve yönetir.", "Güncelleme Merkezi"),
            ("monitor", "Windows Sürüm Takibi", "Windows build sürümlerini takip eder, yeni sürümler hakkında bilgi verir.", "Windows Sürüm Takibi"),
            ("cube", "UUP ISO Oluşturucu", "UUP paketleri ile Windows sürümlerini indirmenizi ve kurulum medyası oluşturmanızı sağlar.", "UUP ISO Oluşturucu"),
            ("download-tray", "İndirme Yöneticisi", "İndirmeleri yönet, duraklatma ve devam ettirme işlemlerini kolaylaştırır.", "İndirme Yöneticisi"),
            ("usb", "USB Kurulum Aracı", "ISO dosyasını önyüklenebilir USB belleğe yazar ve kurulum öncesi kontrolleri yapar.", "USB Kurulum Aracı"),
            ("cpu", "Sürücü Yedekleme", "Üçüncü taraf sürücüleri yedekler, kurulum USB'sine ekler ve yeni kurulumdan sonra geri yükler.", "Sürücü Yedekleme"),
        ]
        for icon_name, title, desc, page in features:
            v.addWidget(self._feature_row(icon_name, title, desc, page))
        v.addStretch(1)
        return card

    def _build_notes_card(self):
        card = QFrame()
        card.setObjectName("abCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        v.addLayout(self._card_header("check-circle", f"Bu Sürümde Neler Yeni ({APP_VERSION})", "Son eklenen özelliklerin kısa özeti."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(10)
        for i, note in enumerate(RELEASE_NOTES):
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(_icon_label("check", "#1FA35C", 18, bg="#E3F6EA", stroke=2.2), 0, Qt.AlignTop)
            label = QLabel(note)
            label.setObjectName("abFeatureTitle")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            grid.addLayout(row, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        return card

    def _feature_row(self, icon_name, title, description, page_name):
        row = _ClickableFrame()
        row.setObjectName("abFeature")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        tile = QLabel()
        tile.setObjectName("abFeatureIcon")
        tile.setFixedSize(54, 54)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap(icon_name, self.BLUE, 28, bg="#E4EEFC", stroke=1.8))
        box = QVBoxLayout()
        box.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("abFeatureTitle")
        d = QLabel(description)
        d.setObjectName("abFeatureDesc")
        d.setWordWrap(True)
        box.addWidget(t)
        box.addWidget(d)
        lay.addWidget(tile, 0, Qt.AlignVCenter)
        lay.addLayout(box, 1)
        lay.addWidget(_icon_label("chevron-right", "#6E7F99", 20, stroke=2.1), 0, Qt.AlignVCenter)
        row.clicked.connect(lambda name=page_name: self._open_page(name))
        return row

    def _open_page(self, page_name: str) -> None:
        window = self.window()
        if hasattr(window, "show_page_by_name"):
            window.show_page_by_name(page_name)

    def _build_footer(self):
        footer = QHBoxLayout()
        footer.setContentsMargins(6, 0, 6, 0)
        footer.setSpacing(10)
        left = QLabel("© Bünyamin KAYA")
        left.setObjectName("abFooter")
        dot = QLabel("•")
        dot.setObjectName("abFooter")
        site = QLabel("bunyaminkaya.com")
        site.setObjectName("abFooterAccent")
        footer.addWidget(left)
        footer.addWidget(dot)
        footer.addWidget(site)
        footer.addStretch(1)
        right = QLabel(f"{APP_NAME} {APP_VERSION}")
        right.setObjectName("abFooter")
        footer.addWidget(right)
        return footer

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Ana penceredeki "Son kontrol" bilgisini yalnızca gösterir.
        text = ""
        window = self.window()
        label = getattr(window, "last_check_label", None)
        if label is not None:
            text = re.sub(r"^(Son kontrol|Last check):", "", label.text(), count=1).strip()
        if text and text != "—" and " " in text:
            day, clock = text.split(" ", 1)
            text = f"{day}, {clock}"
        self.last_check_label.setText(f"Son kontrol:\n{text or '—'}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        direction = QBoxLayout.LeftToRight if self.width() >= 1000 else QBoxLayout.TopToBottom
        if self._columns.direction() != direction:
            self._columns.setDirection(direction)

    def _apply_styles(self) -> None:
        self.setStyleSheet(styles.qss("""
            QScrollArea#abScroll { background: transparent; border: none; }
            QWidget#abContent { background: #F4F7FB; }

            QLabel#abTitle { font-size: 30px; font-weight: 700; color: #0A1F44; }
            QLabel#abSubtitle { font-size: 14px; color: #5F7090; }

            QFrame#abCard { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px; }
            QFrame#abHeroPanel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E8F1FD, stop:1 #F6FAFF);
                border: 1px solid #DCE8F8; border-radius: 12px;
            }
            QLabel#abHeroName { font-size: 38px; font-weight: 800; color: #0B1F4A; }
            QLabel#abHeroTagline { font-size: 23px; font-weight: 600; color: #1A6BE0; }
            QLabel#abHeroDesc { font-size: 13px; color: #5F7090; }

            QFrame#abVersionBox { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 12px; }
            QLabel#abVersionKey { font-size: 13px; color: #6E7F99; }
            QLabel#abVersionValue { font-size: 28px; font-weight: 800; color: #0B1F4A; }
            QFrame#abStatusPill { background: #E3F6EA; border: none; border-radius: 8px; }
            QLabel#abStatusText { font-size: 13px; font-weight: 700; color: #1C7C47; }
            QLabel#abVersionNote { font-size: 12px; color: #5F7090; }

            QLabel#abSectionTitle { font-size: 17px; font-weight: 700; color: #0F2347; }
            QLabel#abSectionSub { font-size: 12px; color: #6E7F99; }

            QLabel#abAvatar { background: @BLUE@; color: #FFFFFF; font-size: 24px; font-weight: 700; border-radius: 33px; }
            QLabel#abDevName { font-size: 20px; font-weight: 700; color: #0F2347; }
            QLabel#abDevRole { font-size: 13px; color: #5F7090; }
            QLabel#abInfoKey { font-size: 13px; color: #6E7F99; }
            QLabel#abInfoValue { font-size: 13px; font-weight: 600; color: #0F2347; }
            QLabel#abInfoLink { font-size: 13px; font-weight: 600; color: @BLUE@; }

            QPushButton#abPrimaryBtn {
                background: @BLUE@; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 0 24px; font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
            }
            QPushButton#abPrimaryBtn:hover { background: #1259C4; }
            QPushButton#abGhostBtn {
                background: #FFFFFF; color: @BLUE@; border: 1px solid #A9C2EA; border-radius: 10px;
                padding: 0 24px; font-size: 13px; font-weight: 600; min-height: 44px; max-height: 44px;
            }
            QPushButton#abGhostBtn:hover { background: #F2F7FF; }

            QFrame#abFeature { background: #F7FAFE; border: 1px solid #E0E9F5; border-radius: 12px; }
            QFrame#abFeature:hover { background: #F0F6FF; border-color: #BCD2F0; }
            QLabel#abFeatureIcon { background: #E4EEFC; border-radius: 27px; }
            QFrame#abRule { background: #E6EDF6; border: none; }
            QLabel#abFeatureTitle { font-size: 13px; font-weight: 700; color: #0F2347; }
            QLabel#abFeatureDesc { font-size: 12px; color: #6E7F99; }
            QLabel#abFooter { color: #6E7F99; font-size: 11px; }
            QLabel#abFooterAccent { color: @BLUE@; font-size: 11px; font-weight: 600; }
        """))

    def _add_contact(self, grid: QGridLayout, row: int, icon_name: str, key: str, value: str, link: bool = False) -> None:
        grid.addWidget(_icon_label(icon_name, self.BLUE, 22, stroke=1.9), row, 0)
        key_label = QLabel(key)
        key_label.setObjectName("abInfoKey")
        value_label = QLabel(value)
        value_label.setObjectName("abInfoLink" if link else "abInfoValue")
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        key_label.setMinimumWidth(110)
        grid.addWidget(key_label, row, 1)
        grid.addWidget(value_label, row, 2)
