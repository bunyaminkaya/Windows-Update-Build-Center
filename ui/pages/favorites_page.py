import json
import webbrowser
from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QMessageBox, QStyledItemDelegate, QStyle, QScrollArea,
    QStackedWidget, QButtonGroup, QApplication
)

from database.connection import get_connection
from ui import icons, styles


class _TitleDelegate(QStyledItemDelegate):
    """Güncelleme sütunu: solda mavi yıldız, yanda satır sonuna kadar kaydırılan başlık.
    Yalnızca görünümdür; hücre metni (★ önekli) ve sıralama mantığı aynen korunur."""

    PAD_LEFT = 46

    @staticmethod
    def _clean(text):
        text = str(text or "")
        return text[1:].lstrip() if text.startswith("★") else text

    def _text_rect(self, rect):
        return QRect(rect.left() + self.PAD_LEFT, rect.top() + 8, max(40, rect.width() - self.PAD_LEFT - 10), rect.height() - 16)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected:
            painter.fillRect(option.rect, QColor("#EAF2FE"))
        elif hovered:
            painter.fillRect(option.rect, QColor("#F5F9FE"))
        pix = icons.pixmap("star-fill", "#1F5FC9", 20)
        painter.drawPixmap(option.rect.left() + 16, option.rect.center().y() - 10, pix)
        painter.setPen(QColor("#16264A"))
        painter.setFont(option.font)
        painter.drawText(self._text_rect(option.rect), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
                         self._clean(index.data(Qt.DisplayRole)))
        painter.restore()

    def sizeHint(self, option, index):
        view = option.widget
        width = view.columnWidth(index.column()) if view is not None else 400
        fm = QFontMetrics(option.font)
        rect = fm.boundingRect(0, 0, max(40, width - self.PAD_LEFT - 10), 2000,
                               Qt.TextWordWrap, self._clean(index.data(Qt.DisplayRole)))
        return QSize(width, max(60, rect.height() + 28))


class _RowDelegate(QStyledItemDelegate):
    """Diğer sütunlar: seçili / üzerine gelinen satır zemini + ortalı metin."""

    def paint(self, painter, option, index):
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected:
            painter.fillRect(option.rect, QColor("#EAF2FE"))
        elif hovered:
            painter.fillRect(option.rect, QColor("#F5F9FE"))
        painter.setPen(QColor("#2A3A5C"))
        painter.setFont(option.font)
        painter.drawText(option.rect.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
                         str(index.data(Qt.DisplayRole) or ""))
        painter.restore()


class FavoritesPage(QWidget):
    """Uygulama ana penceresi içinde çalışan Favoriler çalışma alanı."""

    BLUE = "#1768E0"
    FIELD_ICONS = {
        "version": "cube", "kb": "doc", "architecture": "cpu", "product": "windows-outline",
        "classification": "boxes", "channel": "user", "source": "boxes", "created_at": "clock",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Favorilerim")
        self._build_ui()

    @staticmethod
    def _extract_kb(title):
        import re
        match = re.search(r"KB\d{5,8}", str(title or ""), re.IGNORECASE)
        return match.group(0).upper() if match else ""

    @staticmethod
    def _icon_label(name, color, size=20, box=None):
        lab = QLabel()
        lab.setPixmap(icons.pixmap(name, color, size))
        lab.setAlignment(Qt.AlignCenter)
        lab.setAttribute(Qt.WA_TranslucentBackground)
        lab.setStyleSheet("background: transparent; border: none;")
        if box:
            lab.setFixedSize(box, box)
        return lab

    @staticmethod
    def _btn(text, icon_name, color, obj, height=44):
        b = QPushButton("  " + text)
        b.setObjectName(obj)
        b.setIcon(QIcon(icons.pixmap(icon_name, color, 36)))
        b.setIconSize(QSize(18, 18))
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(height)
        return b

    def _build_ui(self):
        """Favoriler: üst arama/araç çubuğu, bilgi şeridi, liste kartı ve ayrıntı paneli."""
        self.setWindowTitle("Favorilerim • Kaydedilen Güncellemeler")
        self.setMinimumSize(1050, 650)
        self.resize(1240, 760)
        self.setObjectName("favoritesPage")
        self.setStyleSheet(styles.qss("""
            QWidget#favoritesPage { background: #F3F7FC; }
            QLabel { background: transparent; }
            QLabel#favTitle { color: #0A1F44; font-size: 30px; font-weight: 700; }
            QLabel#favSubtitle { color: #5F7090; font-size: 14px; }
            QLabel#favTile {
                background: @BLUE@; border-radius: 14px; border: none;
            }
            QLineEdit#favSearch {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 12px;
                padding: 0 14px 0 6px; font-size: 14px; color: #14213D;
                min-height: 44px; max-height: 44px; selection-background-color: @BLUE@;
            }
            QLineEdit#favSearch:focus { border: 1px solid @BLUE@; }
            QPushButton#secondaryButton, QPushButton#primaryButton, QPushButton#dangerButton {
                border-radius: 12px; padding: 0 18px; font-size: 13px; font-weight: 600;
                min-height: 44px; max-height: 44px;
            }
            QPushButton#secondaryButton { background: #FFFFFF; color: @BLUE@; border: 1px solid #CBD9EC; }
            QPushButton#secondaryButton:hover { background: #F1F6FD; border-color: #9DB9E6; }
            QPushButton#primaryButton { background: @BLUE@; color: #FFFFFF; border: none; }
            QPushButton#primaryButton:hover { background: #135BC4; }
            QPushButton#dangerButton { background: #FFFFFF; color: #E53935; border: 1px solid #EF6B68; }
            QPushButton#dangerButton:hover { background: #FFF4F4; }
            QPushButton#primaryButton:disabled { background: #A9C4EE; color: #FFFFFF; border: none; }
            QPushButton:disabled { color: #9AA8BF; background: #F4F7FB; border: 1px solid #E1E8F2; }
            QFrame#favInfoStrip {
                background: #EDF4FE; border: 1px solid #D5E3F8; border-radius: 12px;
            }
            QLabel#favCount { color: #14213D; font-size: 13px; font-weight: 700; }
            QLabel#favInfoText { color: #5F7090; font-size: 12px; }
            QFrame#favInfoDivider { background: #C9D8EE; border: none; }
            QFrame#favoritesListCard, QFrame#favoritesDetailCard {
                background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px;
            }
            QLabel#favCardTitle { color: #14213D; font-size: 16px; font-weight: 700; }
            QLabel#favCardTile { background: #EAF1FD; border-radius: 10px; border: none; }
            QPushButton#favViewButton {
                background: #FFFFFF; color: #3A4D70; border: 1px solid #D5E0EE; border-radius: 9px;
                padding: 0 14px; font-size: 12px; font-weight: 600; min-height: 36px; max-height: 36px;
            }
            QPushButton#favViewButton:checked { background: @BLUE@; color: #FFFFFF; border: 1px solid @BLUE@; }
            QPushButton#favViewButton:hover:!checked { background: #F1F6FD; }
            QTableWidget#favoritesTable {
                background: #FFFFFF; border: none; gridline-color: transparent; outline: 0;
            }
            QTableWidget#favoritesTable QHeaderView::section {
                background: #F4F8FD; color: #3A4D70; border: none; padding: 12px 8px 12px 8px;
                font-size: 12px; font-weight: 700;
            }
            QTableWidget#favoritesTable QHeaderView::section:first { padding-left: 46px; text-align: left; }
            QScrollArea#favDetailScroll { background: transparent; border: none; }
            QScrollArea#favDetailScroll > QWidget > QWidget { background: transparent; }
            QLabel#detailSectionTitle { color: #14213D; font-size: 14px; font-weight: 700; }
            QLabel#favDetailTitle { color: #14213D; font-size: 16px; font-weight: 700; }
            QLabel#detailMeta { color: #65728A; }
            QFrame#favoriteInfoCard {
                background: #F8FBFF; border: 1px solid #E1EAF5; border-radius: 10px;
            }
            QLabel#packageQuickCaption { color: #738198; font-size: 12px; }
            QLabel#packageQuickValue { color: #14213D; font-size: 13px; font-weight: 600; }
            QLabel#favBadge {
                background: #E6F7EC; color: #1B8A45; border: 1px solid #BFE6CD; border-radius: 12px;
                padding: 3px 12px 3px 8px; font-size: 12px; font-weight: 600;
            }
            QFrame#favUrlBox {
                background: #F6F9FE; border: 1px solid #D9E6F7; border-radius: 10px;
            }
            QLabel#packageFileLabel { color: @BLUE@; font-size: 12px; }
            QPushButton#favMiniButton { background: transparent; border: none; border-radius: 6px; }
            QPushButton#favMiniButton:hover { background: #E3EEFC; }
            QLabel#favEmpty { color: #7C8BA5; font-size: 14px; }
        """))

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        # ── Başlık ──
        head = QHBoxLayout()
        head.setSpacing(16)
        tile = QLabel()
        tile.setObjectName("favTile")
        tile.setFixedSize(64, 64)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap("star", "#FFFFFF", 30, stroke=2.0))
        head.addWidget(tile, 0, Qt.AlignTop)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Favorilerim")
        title.setObjectName("favTitle")
        subtitle = QLabel("Kaydettiğiniz güncelleme ve build'lere tek yerden hızlıca ulaşın.")
        subtitle.setObjectName("favSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        head.addLayout(title_col, 1)
        root.addLayout(head)

        # ── Araç çubuğu ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        search = QLineEdit()
        search.setObjectName("favSearch")
        search.setPlaceholderText("KB, build, Windows sürümü veya başlık ara...")
        search.setClearButtonEnabled(True)
        search.addAction(QIcon(icons.pixmap("search", "#1768E0", 36, stroke=2.2)), QLineEdit.LeadingPosition)
        toolbar.addWidget(search, 1)

        refresh_btn = self._btn("Yenile", "refresh", "#1768E0", "secondaryButton")
        toolbar.addWidget(refresh_btn)

        top_source_btn = self._btn("Microsoft Sayfasını Aç", "external", "#1768E0", "secondaryButton")
        top_source_btn.setEnabled(False)
        toolbar.addWidget(top_source_btn)

        top_clear_btn = self._btn("Favorileri Temizle", "trash", "#E53935", "dangerButton")
        toolbar.addWidget(top_clear_btn)
        root.addLayout(toolbar)

        # ── Bilgi şeridi ──
        strip = QFrame()
        strip.setObjectName("favInfoStrip")
        strip.setFixedHeight(48)
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(12)
        sl.addWidget(self._icon_label("info-fill", "#1768E0", 22, 24))
        count_label = QLabel("0 kayıt")
        count_label.setObjectName("favCount")
        sl.addWidget(count_label)
        divider = QFrame()
        divider.setObjectName("favInfoDivider")
        divider.setFixedSize(1, 20)
        sl.addWidget(divider)
        info_text = QLabel("Seçili favorinin ayrıntıları sağ panelde gösterilir.")
        info_text.setObjectName("favInfoText")
        sl.addWidget(info_text, 1)
        root.addWidget(strip)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("favoritesSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(14)

        # ── Sol kart: liste ──
        list_card = QFrame()
        list_card.setObjectName("favoritesListCard")
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.setSpacing(0)
        lh = QHBoxLayout()
        lh.setContentsMargins(16, 14, 16, 12)
        lh.setSpacing(12)
        ltile = QLabel()
        ltile.setObjectName("favCardTile")
        ltile.setFixedSize(40, 40)
        ltile.setAlignment(Qt.AlignCenter)
        ltile.setPixmap(icons.pixmap("star-fill", "#1F5FC9", 22))
        lh.addWidget(ltile)
        ltitle = QLabel("Kaydedilen Güncellemeler")
        ltitle.setObjectName("favCardTitle")
        lh.addWidget(ltitle, 1)
        list_view_btn = QPushButton("  Liste Görünümü")
        card_view_btn = QPushButton("  Kart Görünümü")
        view_group = QButtonGroup(self)
        view_group.setExclusive(True)
        for b, ic in ((list_view_btn, "list"), (card_view_btn, "boxes")):
            b.setObjectName("favViewButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(16, 16))
            view_group.addButton(b)
            lh.addWidget(b)
        list_view_btn.setChecked(True)
        list_view_btn.setIcon(QIcon(icons.pixmap("list", "#FFFFFF", 32)))
        card_view_btn.setIcon(QIcon(icons.pixmap("boxes", "#3A4D70", 32)))
        lc.addLayout(lh)

        table = QTableWidget(0, 7)
        table.setObjectName("favoritesTable")
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setWordWrap(True)
        table.setMouseTracking(True)
        table.setFrameShape(QFrame.NoFrame)
        table.setSortingEnabled(True)
        table.setHorizontalHeaderLabels([
            "Güncelleme", "Sürüm / Build", "KB", "Mimari", "Kaynak", "Kanal", "Kaydedildi"
        ])
        header_view = table.horizontalHeader()
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setDefaultAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        for col, width in ((1, 120), (2, 110), (3, 96), (4, 140), (5, 100), (6, 118)):
            header_view.setSectionResizeMode(col, QHeaderView.Fixed)
            header_view.resizeSection(col, width)
        table.setColumnHidden(5, True)  # Kanal ayrıntı panelinde gösterilir
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setItemDelegateForColumn(0, _TitleDelegate(table))
        row_delegate = _RowDelegate(table)
        for col in range(1, 7):
            table.setItemDelegateForColumn(col, row_delegate)
        table.setMinimumWidth(650)

        empty_label = QLabel("Henüz favori eklenmedi.")
        empty_label.setObjectName("favEmpty")
        empty_label.setAlignment(Qt.AlignCenter)
        table_stack = QStackedWidget()
        table_stack.addWidget(table)
        table_stack.addWidget(empty_label)
        lc.addWidget(table_stack, 1)
        splitter.addWidget(list_card)

        # ── Sağ kart: ayrıntı ──
        detail = QFrame()
        detail.setObjectName("favoritesDetailCard")
        dc = QVBoxLayout(detail)
        dc.setContentsMargins(0, 0, 0, 0)
        dc.setSpacing(0)

        dh = QHBoxLayout()
        dh.setContentsMargins(18, 16, 18, 8)
        dh.setSpacing(10)
        dh.addWidget(self._icon_label("star-fill", "#1F5FC9", 20, 24))
        dh_title = QLabel("Favori Ayrıntıları")
        dh_title.setObjectName("favCardTitle")
        dh.addWidget(dh_title, 1)
        saved_badge = QLabel("  Kaydedildi")
        saved_badge.setObjectName("favBadge")
        saved_badge.setVisible(False)
        dh.addWidget(saved_badge)
        dc.addLayout(dh)

        scroll = QScrollArea()
        scroll.setObjectName("favDetailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("favDetailBody")
        detail_layout = QVBoxLayout(body)
        detail_layout.setContentsMargins(18, 4, 18, 8)
        detail_layout.setSpacing(12)

        detail_title = QLabel("Favori seçin")
        detail_title.setObjectName("favDetailTitle")
        detail_title.setWordWrap(True)
        detail_layout.addWidget(detail_title)

        detail_status = QLabel("Bir kayıt seçtiğinizde tüm kayıt bilgileri burada gösterilir.")
        detail_status.setObjectName("detailMeta")
        detail_status.setWordWrap(True)
        detail_status.setVisible(False)  # metin mantık tarafından yazılır; görsel tasarımda "Kaydedildi" rozeti gösterilir
        detail_layout.addWidget(detail_status)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(12)
        info_grid.setVerticalSpacing(12)

        detail_fields = {}
        field_names = [
            ("Sürüm / Build", "version"),
            ("KB", "kb"),
            ("Mimari", "architecture"),
            ("Ürün", "product"),
            ("Sınıflandırma", "classification"),
            ("Kanal", "channel"),
            ("Kaynak", "source"),
            ("Kaydedilme", "created_at"),
        ]
        for index, (caption, key) in enumerate(field_names):
            row, col = divmod(index, 2)
            card = QFrame()
            card.setObjectName("favoriteInfoCard")
            card_h = QHBoxLayout(card)
            card_h.setContentsMargins(12, 10, 12, 10)
            card_h.setSpacing(10)
            card_h.addWidget(self._icon_label(self.FIELD_ICONS[key], "#1768E0", 18, 30), 0, Qt.AlignVCenter)
            card_layout = QVBoxLayout()
            card_layout.setSpacing(2)
            cap = QLabel(caption)
            cap.setObjectName("packageQuickCaption")
            val = QLabel("—")
            val.setObjectName("packageQuickValue")
            val.setWordWrap(True)
            card_layout.addWidget(cap)
            card_layout.addWidget(val)
            card_h.addLayout(card_layout, 1)
            info_grid.addWidget(card, row, col)
            detail_fields[key] = val
        info_grid.setColumnStretch(0, 1)
        info_grid.setColumnStretch(1, 1)
        detail_layout.addLayout(info_grid)

        url_label = QLabel("Microsoft kaynak bağlantısı")
        url_label.setObjectName("detailSectionTitle")
        detail_layout.addWidget(url_label)
        url_box = QFrame()
        url_box.setObjectName("favUrlBox")
        ub = QHBoxLayout(url_box)
        ub.setContentsMargins(12, 6, 8, 6)
        ub.setSpacing(4)
        url_value = QLabel("—")
        url_value.setObjectName("packageFileLabel")
        url_value.setWordWrap(True)
        url_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ub.addWidget(url_value, 1)
        url_copy_btn = QPushButton()
        url_open_btn = QPushButton()
        for b, ic, tip in ((url_copy_btn, "copy", "Bağlantıyı kopyala"), (url_open_btn, "external", "Bağlantıyı aç")):
            b.setObjectName("favMiniButton")
            b.setIcon(QIcon(icons.pixmap(ic, "#1768E0", 36)))
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(30, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            ub.addWidget(b)
        detail_layout.addWidget(url_box)
        detail_layout.addStretch(1)
        scroll.setWidget(body)
        dc.addWidget(scroll, 1)

        # Eylem düğmeleri (kartın altında sabit)
        actions = QVBoxLayout()
        actions.setContentsMargins(18, 8, 18, 18)
        actions.setSpacing(10)
        action_row = QHBoxLayout()
        action_row.setSpacing(12)
        restore_btn = self._btn("Aramayı Aç", "search", "#FFFFFF", "primaryButton")
        delete_btn = self._btn("Favoriden Sil", "trash", "#E53935", "dangerButton")
        close_btn = self._btn("Güncelleme Merkezine Dön", "undo", "#1768E0", "secondaryButton")
        action_row.addWidget(restore_btn, 1)
        action_row.addWidget(delete_btn, 1)
        actions.addLayout(action_row)
        actions.addWidget(close_btn)
        dc.addLayout(actions)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([720, 460])
        root.addWidget(splitter, 1)

        # ── Yalnızca görünüm kancaları (kayıt sayısı, boş durum, görünüm düğmeleri) ──
        def refresh_view_state(*_args):
            try:
                n = table.rowCount()
            except RuntimeError:  # pencere kapanırken
                return
            count_label.setText(f"{n} kayıt")
            if n == 0:
                empty_label.setText("Eşleşen favori bulunamadı." if search.text().strip() else "Henüz favori eklenmedi.")
            table_stack.setCurrentIndex(0 if n else 1)

        model = table.model()
        model.rowsInserted.connect(refresh_view_state)
        model.rowsRemoved.connect(refresh_view_state)
        model.modelReset.connect(refresh_view_state)

        def set_view_mode(card_mode):
            # Liste: tüm sütunlar. Kart: başlık odaklı, ikincil sütunlar gizli.
            for col in (2, 3, 4):
                table.setColumnHidden(col, bool(card_mode))
            list_view_btn.setIcon(QIcon(icons.pixmap("list", "#3A4D70" if card_mode else "#FFFFFF", 32)))
            card_view_btn.setIcon(QIcon(icons.pixmap("boxes", "#FFFFFF" if card_mode else "#3A4D70", 32)))
            table.resizeRowsToContents()

        list_view_btn.clicked.connect(lambda: set_view_mode(False))
        card_view_btn.clicked.connect(lambda: set_view_mode(True))

        def copy_url():
            text = url_value.text().strip()
            if text.startswith("http"):
                QApplication.clipboard().setText(text)

        def open_url_label():
            text = url_value.text().strip()
            if text.startswith("http"):
                webbrowser.open(text)

        url_copy_btn.clicked.connect(copy_url)
        url_open_btn.clicked.connect(open_url_label)


        records = []
        selected_id = {"value": None}

        def parse_metadata(raw):
            try:
                return json.loads(raw or "{}")
            except Exception:
                return {}

        def load_records():
            nonlocal records
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, item_type, item_key, title, metadata_json, created_at "
                    "FROM favorites ORDER BY id DESC"
                ).fetchall()
            records = []
            for fav_id, item_type, item_key, fav_title, metadata_json, created_at in rows:
                metadata = parse_metadata(metadata_json)
                metadata["id"] = fav_id
                metadata["item_type"] = item_type
                metadata["item_key"] = item_key
                metadata["title"] = fav_title
                metadata["created_at"] = created_at or "—"
                records.append(metadata)
            populate_table()

        def filtered_records():
            needle = search.text().strip().casefold()
            if not needle:
                return records
            result = []
            for rec in records:
                haystack = " ".join(str(rec.get(k, "")) for k in (
                    "title", "version", "kb", "architecture", "product",
                    "classification", "channel", "source", "created_at"
                )).casefold()
                if needle in haystack:
                    result.append(rec)
            return result

        def populate_table():
            table.setSortingEnabled(False)
            table.clearContents()
            visible = filtered_records()
            table.setRowCount(len(visible))
            for row, rec in enumerate(visible):
                values = [
                    rec.get("title", "—"),
                    rec.get("version", "—"),
                    rec.get("kb", "—") or self._extract_kb(str(rec.get("title", ""))),
                    rec.get("architecture", "—"),
                    rec.get("source", "Microsoft"),
                    rec.get("channel", "—"),
                    rec.get("created_at", "—"),
                ]
                for col, value in enumerate(values):
                    display_value = str(value or "—")
                    if col == 0:
                        display_value = "★  " + display_value
                    cell = QTableWidgetItem(display_value)
                    if col > 0:
                        cell.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, col, cell)
                table.item(row, 0).setData(Qt.UserRole, rec.get("id"))
            table.setSortingEnabled(True)
            if visible:
                table.selectRow(0)
            else:
                selected_id["value"] = None
                clear_detail()

        def current_record():
            row = table.currentRow()
            if row < 0:
                return None
            item = table.item(row, 0)
            fav_id = item.data(Qt.UserRole) if item else None
            for rec in records:
                if rec.get("id") == fav_id:
                    return rec
            return None

        def clear_detail():
            detail_title.setText("Favori seçin")
            detail_status.setText("Bir kayıt seçtiğinizde tüm kayıt bilgileri burada gösterilir.")
            for value in detail_fields.values():
                value.setText("—")
            url_value.setText("—")
            saved_badge.setVisible(False)
            restore_btn.setEnabled(False)
            top_source_btn.setEnabled(False)
            delete_btn.setEnabled(False)

        def show_detail():
            rec = current_record()
            if not rec:
                clear_detail()
                return
            selected_id["value"] = rec.get("id")
            title_text = rec.get("title", "Microsoft güncellemesi")
            detail_title.setText(title_text)
            detail_status.setText(
                "Favori kaydı hazır. İsterseniz arama ekranına dönüp paketleri tekrar bulabilirsiniz."
            )
            kb = rec.get("kb") or self._extract_kb(str(title_text))
            values = {
                "version": rec.get("version") or "—",
                "kb": kb or "—",
                "architecture": rec.get("architecture") or "—",
                "product": rec.get("product") or "—",
                "classification": rec.get("classification") or "—",
                "channel": rec.get("channel") or "—",
                "source": rec.get("source") or "Microsoft Update Catalog",
                "created_at": rec.get("created_at") or "—",
            }
            for key, value in values.items():
                detail_fields[key].setText(str(value))
            url = rec.get("source_url") or ""
            url_value.setText(url if url else "Kaynak bağlantısı kayıtlı değil.")
            restore_btn.setEnabled(bool(kb or rec.get("version")))
            top_source_btn.setEnabled(bool(url))
            delete_btn.setEnabled(True)
            saved_badge.setVisible(True)

        def restore_selected():
            rec = current_record()
            if not rec:
                return
            query = rec.get("kb") or self._extract_kb(str(rec.get("title", "")))
            if not query or query == "—":
                query = rec.get("version", "")
            query = str(query or "").strip()
            if not query:
                return
            home = self.window().page_by_name("Güncelleme Merkezi") if hasattr(self.window(), "page_by_name") else None
            if home is None:
                return
            home.search_input.setText(query)
            self.window().show_page_by_name("Güncelleme Merkezi")
            home.start_search()

        def open_source():
            rec = current_record()
            url = (rec or {}).get("source_url", "")
            if url:
                webbrowser.open(url)

        def delete_selected():
            rec = current_record()
            fav_id = (rec or {}).get("id")
            if not fav_id:
                return
            with get_connection() as conn:
                conn.execute("DELETE FROM favorites WHERE id = ?", (fav_id,))
                conn.commit()
            load_records()

        def clear_all():
            if not records:
                return
            from PySide6.QtWidgets import QMessageBox
            answer = QMessageBox.question(
                self,
                "Favorileri temizle",
                f"{len(records)} favorinin tamamı silinsin mi? Bu işlem geri alınamaz.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            with get_connection() as conn:
                conn.execute("DELETE FROM favorites")
                conn.commit()
            load_records()

        table.itemSelectionChanged.connect(show_detail)
        table.itemDoubleClicked.connect(lambda _item: restore_selected())
        search.textChanged.connect(populate_table)
        refresh_btn.clicked.connect(load_records)
        restore_btn.clicked.connect(restore_selected)
        top_source_btn.clicked.connect(open_source)
        delete_btn.clicked.connect(delete_selected)
        top_clear_btn.clicked.connect(clear_all)
        close_btn.clicked.connect(lambda: self.window().show_page_by_name("Güncelleme Merkezi") if hasattr(self.window(), "show_page_by_name") else None)

        load_records()
