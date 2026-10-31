from pathlib import Path
import re
import json
import webbrowser
from PySide6.QtCore import QThread, Qt, Signal, QEvent, QSize, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton,  QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QSizePolicy, QListWidget, QListWidgetItem, QApplication, QScrollArea, QFileDialog, QCompleter,
    QStackedWidget, QStyledItemDelegate, QStyle
)

from database.connection import get_connection
from workers.catalog_search_worker import CatalogSearchWorker
from workers.package_lookup_worker import PackageLookupWorker
from services.download_manager import DownloadManager
from services.iso_version_service import parse_version_query
from services.system_profile import SystemProfileService
from services.settings_service import SettingsService
from ui import icons, styles
from ui.widgets.message_dialog import show_message, show_information, show_warning, show_error
from ui.widgets.modern_combo_box import ModernComboBox


class StatCard(QFrame):
    def __init__(self, title, value, note):
        super().__init__()
        self.setObjectName("statCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("statTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("statValue")
        self.note_label = QLabel(note)
        self.note_label.setObjectName("statNote")
        self.note_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.note_label)


class CompletionDelegate(QStyledItemDelegate):
    """Öneri listesinde yazılan kısmı soluk, tamamlayıcı kısmı kalın gösterir."""

    def __init__(self, line_edit, parent=None):
        super().__init__(parent)
        self._edit = line_edit

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 38)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(option.rect).adjusted(6, 2, -6, -2)
        selected = bool(option.state & (QStyle.State_Selected | QStyle.State_MouseOver))
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#E8F1FE"))
            painter.drawRoundedRect(rect, 8, 8)

        text = str(index.data(Qt.DisplayRole) or "")
        typed = self._edit.text()
        font = QFont(option.font)
        font.setPixelSize(15)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        x = rect.left() + 12
        y_rect = QRectF(x, rect.top(), rect.width() - 24, rect.height())

        n = len(typed)
        if n and text.casefold().startswith(typed.casefold()):
            head, tail = text[:n], text[n:]
            painter.setPen(QColor("#6B7C97"))
            painter.drawText(y_rect, Qt.AlignVCenter | Qt.AlignLeft, head)
            x += metrics.horizontalAdvance(head)
            bold = QFont(font)
            bold.setWeight(QFont.Bold)
            painter.setFont(bold)
            painter.setPen(QColor("#0F2347"))
            painter.drawText(QRectF(x, rect.top(), rect.right() - x - 12, rect.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, tail)
        else:
            painter.setPen(QColor("#0F2347"))
            painter.drawText(y_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


class AutoHideButton(QPushButton):
    """Etkin değilken görünmez olan düğme (yalnızca arayüz davranışı)."""

    def changeEvent(self, event):
        if event.type() == QEvent.EnabledChange:
            self.setVisible(self.isEnabled())
        super().changeEvent(event)


class ClickableCard(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _pix_label(name, color="#FFFFFF", size=20, bg="#FFFFFF", stroke=1.9):
    label = QLabel()
    label.setPixmap(icons.pixmap(name, color, size, bg=bg, stroke=stroke))
    label.setFixedSize(size, size)
    label.setAttribute(Qt.WA_TranslucentBackground, True)
    return label


class HomePage(QWidget):
    # Arama başarıyla tamamlandığında sol menüdeki "Son kontrol" bilgisini
    # güncellemek için kullanılır (yalnızca arayüz bildirimi).
    search_completed = Signal()

    BLUE = "#1F6FEB"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._last_results = []
        self._selected_result = None
        self._displayed_results = []
        self._package_thread = None
        self._package_worker = None
        self._packages = []
        self._wide_cols = None
        self._wide_filters = None

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("muScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("muContent")
        self._scroll.setWidget(content)
        page_layout.addWidget(self._scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(18)

        root.addLayout(self._build_header())
        root.addLayout(self._build_search_row())

        self._cols = QGridLayout()
        self._cols.setHorizontalSpacing(18)
        self._cols.setVerticalSpacing(18)
        self._left_col = QWidget()
        left = QVBoxLayout(self._left_col)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(18)
        left.addWidget(self._build_results_card())
        left.addWidget(self._build_selected_card())
        left.addStretch(1)

        self._right_col = QWidget()
        self._right_col.setFixedWidth(306)
        right = QVBoxLayout(self._right_col)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(18)
        right.addWidget(self._build_about_card())
        right.addWidget(self._build_quick_card())
        right.addStretch(1)

        self._cols.setColumnStretch(0, 1)
        root.addLayout(self._cols)
        root.addStretch(1)

        self._build_hidden_legacy_widgets()
        self._wire_dynamic_visibility()
        self._apply_page_styles()
        self._refresh_mockup_fields(None)
        self._sync_package_area()
        self._on_results_changed()
        self._relayout_responsive()

    # ------------------------------------------------------------------
    # Arayüz kurulumu (yalnızca görünüm)
    # ------------------------------------------------------------------
    def _build_header(self):
        head = QHBoxLayout()
        head.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(icons.pixmap("windows", size=52))
        logo.setFixedSize(52, 52)
        head.addWidget(logo, 0, Qt.AlignTop)

        box = QVBoxLayout()
        box.setSpacing(3)
        title = QLabel("Güncelleme Merkezi")
        title.setObjectName("muTitle")
        subtitle = QLabel(
            "Windows güncellemelerini ve build'leri arayın, "
            "resmi ISO veya UUP paketlerine ulaşın."
        )
        subtitle.setObjectName("muSubtitle")
        subtitle.setWordWrap(True)
        box.addWidget(title)
        box.addWidget(subtitle)
        head.addLayout(box, 1)
        return head

    def _build_search_row(self):
        top = QHBoxLayout()
        top.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("muSearch")
        self.search_input.setPlaceholderText("KB5101650 veya 26200.8875 gibi bir değer girin...")
        self.search_input.setMinimumHeight(52)
        self.search_input.returnPressed.connect(self.start_search)
        self._clear_action = self.search_input.addAction(
            icons.icon("x", "#5C6B82", 16, stroke=2.2), QLineEdit.TrailingPosition
        )
        self._clear_action.setVisible(False)
        self._clear_action.triggered.connect(self.search_input.clear)
        self.search_input.textChanged.connect(
            lambda text: self._clear_action.setVisible(bool(text))
        )
        self._refresh_search_completer()

        self.search_button = QPushButton("  Ara")
        self.search_button.setObjectName("muSearchBtn")
        self.search_button.setIcon(icons.icon("search", "#FFFFFF", 20, stroke=2.2))
        self.search_button.setIconSize(QSize(20, 20))
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.setFixedHeight(52)
        self.search_button.setMinimumWidth(122)
        self.search_button.clicked.connect(self.start_search)

        self.stop_button = AutoHideButton("Aramayı Durdur")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setFixedHeight(52)
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_search)

        top.addWidget(self.search_input, 1)
        top.addWidget(self.search_button)
        top.addWidget(self.stop_button)
        return top

    def _make_filters(self):
        # Filtre kutularında yalnızca "Tümü" yazmak kullanıcıya neyi seçtiğini
        # anlatmıyordu. Her kutu artık kendi amacını doğrudan seçili metinde gösterir.
        self.source_filter = ModernComboBox()
        self.source_filter.addItems([
            "Kaynak: Tümü",
            "Kaynak: Microsoft Update Catalog",
        ])
        self.source_filter.setToolTip("Arama sonucunun geldiği Microsoft kaynağını filtreler.")

        self.type_filter = ModernComboBox()
        self.type_filter.addItems([
            "Güncelleme Türü: Tümü",
            "Tür: Güvenlik Güncellemeleri",
            "Tür: Genel Güncellemeler",
            "Tür: Sürücüler",
        ])
        self.type_filter.setToolTip("Güvenlik, genel güncelleme veya sürücü kayıtlarını filtreler.")

        self.system_profile = SystemProfileService.current()
        self.arch_filter = ModernComboBox()
        self.arch_filter.addItems([
            "Mimari: Tümü",
            "Mimari: x64",
            "Mimari: ARM64",
            "Mimari: x86",
        ])
        preferred_arch_index = self.arch_filter.findText(f"Mimari: {self.system_profile.architecture}")
        if preferred_arch_index >= 0:
            self.arch_filter.setCurrentIndex(preferred_arch_index)
        self.arch_filter.setToolTip(
            f"Varsayılan mimari Windows sisteminize göre seçildi: {self.system_profile.architecture}. "
            "Tüm mimarileri görmek için Tümü seçeneğini kullanabilirsiniz."
        )
        self.language_filter = ModernComboBox()
        self.language_filter.addItems(["Dil: Tümü"] + [f"Dil: {name}" for name in SystemProfileService.language_options()])
        self.language_filter.setToolTip(
            "26H2 / 25H2 gibi sürüm adıyla ISO ararken ISO Merkezi'nde seçili gelecek dil. "
            "Tümü seçiliyse sistem dili kullanılır. Güncelleme (KB/build) aramalarını etkilemez."
        )

        self.version_filter = ModernComboBox()
        self.version_filter.addItems([
            "Windows Sürümü: Tümü",
            "Windows Sürümü: 24H2",
            "Windows Sürümü: 25H2",
            "Windows Sürümü: 26H1",
            "Windows Sürümü: 26H2",
        ])
        self.version_filter.setToolTip("Windows sürümünü / özellik güncellemesi dalını filtreler.")

        box = QWidget()
        self._filters_grid = QGridLayout(box)
        self._filters_grid.setContentsMargins(0, 0, 0, 0)
        self._filters_grid.setHorizontalSpacing(10)
        self._filters_grid.setVerticalSpacing(10)
        self._filter_combos = [
            self.source_filter, self.type_filter, self.arch_filter,
            self.language_filter, self.version_filter,
        ]
        for combo in self._filter_combos:
            combo.setMinimumHeight(40)
            combo.setMaximumHeight(40)
            combo.setMinimumContentsLength(6)
            combo.setSizeAdjustPolicy(ModernComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumWidth(110)
            combo.setMaximumWidth(210)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.currentIndexChanged.connect(self.apply_filters)
        return box

    def _arrange_filters(self, one_row: bool):
        grid = self._filters_grid
        for combo in self._filter_combos:
            grid.removeWidget(combo)
        for col in range(5):
            grid.setColumnStretch(col, 0)
        columns = 5 if one_row else 3
        for index, combo in enumerate(self._filter_combos):
            combo.setMaximumWidth(210 if one_row else 16777215)
            grid.addWidget(combo, index // columns, index % columns)
        for col in range(columns):
            grid.setColumnStretch(col, 1)

    def _build_results_card(self):
        card = QFrame()
        card.setObjectName("muCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QWidget()
        header.setObjectName("muCardHeader")
        self._results_header = QGridLayout(header)
        self._results_header.setContentsMargins(20, 14, 20, 14)
        self._results_header.setHorizontalSpacing(14)
        self._results_header.setVerticalSpacing(12)

        title_box = QWidget()
        tb = QHBoxLayout(title_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(10)
        tb.addWidget(_pix_label("user", "#1F4FA3", 22, stroke=1.9))
        self.results_title = QLabel("Arama Sonuçları (0)")
        self.results_title.setObjectName("muCardTitle")
        tb.addWidget(self.results_title)
        tb.addStretch(1)
        self._results_title_box = title_box
        self._filters_box = self._make_filters()
        v.addWidget(header)

        # Sonuç tablosu
        self.results_table = QTableWidget(0, 10)
        self.results_table.setObjectName("muTable")
        self.results_table.setHorizontalHeaderLabels([
            "Başlık",
            "Sürüm / Build",
            "KB",
            "Mimari",
            "Boyut",
            "Tarih",
            "Sınıflandırma",
            "Ürün",
            "Kaynak",
            "",
        ])
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.setShowGrid(False)
        self.results_table.setFocusPolicy(Qt.NoFocus)
        self.results_table.setWordWrap(True)
        self.results_table.setFrameShape(QFrame.NoFrame)
        self.results_table.setIconSize(QSize(26, 26))
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.verticalHeader().setDefaultSectionSize(58)
        header_view = self.results_table.horizontalHeader()
        header_view.setStretchLastSection(False)
        header_view.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header_view.setFixedHeight(40)
        header_view.setHighlightSections(False)

        # Öncelikli sütunlar daha geniş ve görünür tutulur.
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)           # Başlık
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents) # Sürüm / Build
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents) # KB
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents) # Mimari
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents) # Boyut
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents) # Tarih
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents) # Sınıflandırma
        header_view.setSectionResizeMode(7, QHeaderView.ResizeToContents) # Ürün
        header_view.setSectionResizeMode(8, QHeaderView.ResizeToContents) # Kaynak
        header_view.setSectionResizeMode(9, QHeaderView.Fixed)             # Ok
        self.results_table.setColumnWidth(9, 46)

        # Sınıflandırma / Ürün / Kaynak bilgisi tabloda tutulur ancak görsel
        # tasarımda seçili kayıt kartındaki etiketlerde gösterilir.
        for hidden_col in (6, 7, 8):
            self.results_table.setColumnHidden(hidden_col, True)

        self.results_table.setColumnWidth(1, 120)
        self.results_table.setColumnWidth(2, 110)
        self.results_table.setColumnWidth(3, 90)
        self.results_table.setColumnWidth(4, 110)
        self.results_table.setColumnWidth(5, 110)

        self.results_table.itemSelectionChanged.connect(
            self._on_selection_changed
        )
        self.results_table.cellDoubleClicked.connect(
            self._on_result_double_clicked
        )

        # Boş durum: durum + açıklama metinleri tablo yerine gösterilir.
        self.status_label = QLabel("Hazır. KB veya build numarası girerek arama yapabilirsiniz.")
        self.status_label.setObjectName("muEmptyStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)

        self.explainer_label = QLabel("Burada bulunan sonuçlar, Microsoft Update Catalog'un döndürdüğü resmi kayıtlardır.")
        self.explainer_label.setObjectName("muEmptyHint")
        self.explainer_label.setWordWrap(True)
        self.explainer_label.setAlignment(Qt.AlignCenter)

        empty_page = QWidget()
        ev = QVBoxLayout(empty_page)
        ev.setContentsMargins(40, 20, 40, 20)
        ev.setSpacing(8)
        ev.addStretch(1)
        empty_icon = QLabel()
        empty_icon.setPixmap(icons.pixmap("search", "#B5C4DA", 38, stroke=1.6))
        empty_icon.setAlignment(Qt.AlignCenter)
        ev.addWidget(empty_icon)
        ev.addWidget(self.status_label)
        ev.addWidget(self.explainer_label)
        ev.addStretch(1)

        self._results_stack = QStackedWidget()
        self._results_stack.setObjectName("muResultsStack")
        self._results_stack.addWidget(empty_page)
        self._results_stack.addWidget(self.results_table)
        self._results_stack.setFixedHeight(340)
        v.addWidget(self._results_stack)
        return card

    def _meta_tile(self, icon_name, caption, value_label):
        card = QFrame()
        card.setObjectName("muMetaCard")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        tile = QLabel()
        tile.setObjectName("muMetaIcon")
        tile.setFixedSize(42, 42)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap(icon_name, self.BLUE, 22, stroke=1.9))
        box = QVBoxLayout()
        box.setSpacing(2)
        cap = QLabel(caption)
        cap.setObjectName("muMetaCaption")
        value_label.setObjectName("muMetaValue")
        value_label.setWordWrap(True)
        box.addWidget(cap)
        box.addWidget(value_label)
        lay.addWidget(tile, 0, Qt.AlignVCenter)
        lay.addLayout(box, 1)
        return card

    def _build_selected_card(self):
        card = QFrame()
        card.setObjectName("muCard")
        self.detail_panel = card
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(18)

        # --- Üst bölüm: logo, başlık, etiketler, eylem düğmeleri
        top = QHBoxLayout()
        top.setSpacing(18)
        logo_tile = QLabel()
        logo_tile.setObjectName("muLogoTile")
        logo_tile.setFixedSize(72, 72)
        logo_tile.setAlignment(Qt.AlignCenter)
        logo_tile.setPixmap(icons.pixmap("windows", size=46))
        top.addWidget(logo_tile, 0, Qt.AlignTop)

        title_box = QVBoxLayout()
        title_box.setSpacing(5)
        self.result_badge = QLabel("Bulunan Sonuç")
        self.result_badge.setObjectName("muBadge")
        badge_row = QHBoxLayout()
        badge_row.addWidget(self.result_badge)
        badge_row.addStretch(1)
        title_box.addLayout(badge_row)

        self.detail_name = QLabel(
            "Detayları görmek için listeden bir kayıt seçin."
        )
        self.detail_name.setObjectName("muSelTitle")
        self.detail_name.setWordWrap(True)
        self.detail_name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        title_box.addWidget(self.detail_name)

        self.build_line = QLabel("")
        self.build_line.setObjectName("muSelBuild")
        title_box.addWidget(self.build_line)

        self.detail_kb = QLabel("—")
        self.detail_size = QLabel("—")
        self.detail_classification = QLabel("—")
        self.detail_product = QLabel("—")
        self.detail_source = QLabel("—")
        self._chips = [
            self.detail_kb, self.detail_size, self.detail_classification,
            self.detail_product, self.detail_source,
        ]
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        for chip in self._chips:
            chip.setObjectName("muChip")
            chip_row.addWidget(chip)
        chip_row.addStretch(1)
        top.addLayout(title_box, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)
        self.favorite_button = QPushButton("Favorilere Ekle")
        self.favorite_button.setObjectName("muGhostBtn")
        self.favorite_button.setIcon(icons.icon("star", self.BLUE, 17, stroke=2.0))
        self.favorite_button.setIconSize(QSize(17, 17))
        self.favorite_button.setCursor(Qt.PointingHandCursor)
        self.favorite_button.setEnabled(False)
        self.favorite_button.clicked.connect(
            self._add_selected_to_favorites
        )
        self.open_source_button = QPushButton(
            "Microsoft Sayfasını Aç"
        )
        self.open_source_button.setObjectName("muGhostBtn")
        self.open_source_button.setIcon(icons.icon("external", self.BLUE, 16, stroke=2.0))
        self.open_source_button.setIconSize(QSize(16, 16))
        self.open_source_button.setCursor(Qt.PointingHandCursor)
        self.open_source_button.setEnabled(False)
        self.open_source_button.clicked.connect(
            self._open_selected_source
        )
        actions.addWidget(self.favorite_button)
        actions.addWidget(self.open_source_button)
        actions.addStretch(1)
        top.addLayout(actions, 0)
        v.addLayout(top)
        v.addLayout(chip_row)
        v.setSpacing(16)

        # --- Dört bilgi kutusu
        self.card_version = QLabel("—")
        self.card_build = QLabel("—")
        self.card_channel = QLabel("—")
        self.card_date = QLabel("—")
        tiles = QHBoxLayout()
        tiles.setSpacing(14)
        tiles.addWidget(self._meta_tile("gear-outline", "Sürüm", self.card_version), 1)
        tiles.addWidget(self._meta_tile("calendar", "Build No", self.card_build), 1)
        tiles.addWidget(self._meta_tile("cube", "Kanal", self.card_channel), 1)
        tiles.addWidget(self._meta_tile("clock", "Yayın Tarihi", self.card_date), 1)
        v.addLayout(tiles)

        # --- İndirme seçenekleri
        section = QFrame()
        section.setObjectName("muSection")
        sv = QVBoxLayout(section)
        sv.setContentsMargins(0, 0, 0, 14)
        sv.setSpacing(10)
        section_title = QLabel("İndirme Seçenekleri")
        section_title.setObjectName("muSectionTitle")
        sv.addWidget(section_title)

        # Satır 1: Microsoft paketi
        row1 = QFrame()
        row1.setObjectName("muRow")
        r1 = QHBoxLayout(row1)
        r1.setContentsMargins(18, 14, 14, 14)
        r1.setSpacing(14)
        r1.addWidget(_pix_label("windows-color", size=34), 0, Qt.AlignVCenter)
        t1 = QVBoxLayout()
        t1.setSpacing(2)
        l1 = QLabel("Microsoft Orijinal ISO Linki")
        l1.setObjectName("muRowTitle")
        d1 = QLabel("Resmi Microsoft paketlerini bulun ve doğrudan indirin.")
        d1.setObjectName("muRowDesc")
        self.package_card_title = l1
        self.package_card_desc = d1
        d1.setWordWrap(True)
        t1.addWidget(l1)
        t1.addWidget(d1)
        r1.addLayout(t1, 1)

        self.find_packages_button = QPushButton("Paketleri Bul")
        self.find_packages_button.setObjectName("muGhostBtn")
        self.find_packages_button.setCursor(Qt.PointingHandCursor)
        self.find_packages_button.setEnabled(False)
        self.find_packages_button.clicked.connect(
            self._prepare_package_lookup
        )
        self.open_package_button = QPushButton(
            "Microsoft'tan İndir"
        )
        self.open_package_button.setObjectName("muPrimaryBtn")
        self.open_package_button.setIcon(icons.icon("external", "#FFFFFF", 17, stroke=2.1))
        self.open_package_button.setIconSize(QSize(17, 17))
        self.open_package_button.setCursor(Qt.PointingHandCursor)
        self.open_package_button.setEnabled(False)
        self.open_package_button.clicked.connect(
            self._open_selected_package
        )
        r1.addWidget(self.find_packages_button, 0, Qt.AlignVCenter)
        r1.addWidget(self.open_package_button, 0, Qt.AlignVCenter)
        r1.addWidget(_pix_label("chevron-right", "#6E7F99", 18, stroke=2.1), 0, Qt.AlignVCenter)

        # Paket listesi (paketler bulunduğunda açılır)
        self.package_area = QFrame()
        self.package_area.setObjectName("muPackageArea")
        pa = QHBoxLayout(self.package_area)
        pa.setContentsMargins(14, 14, 14, 14)
        pa.setSpacing(12)

        self.package_list = QListWidget()
        self.package_list.setObjectName("packageList")
        self.package_list.setMinimumHeight(116)
        self.package_list.setFocusPolicy(Qt.NoFocus)
        self.package_list.setMaximumHeight(156)
        self.package_list.setMinimumWidth(150)
        self.package_list.itemDoubleClicked.connect(
            self._open_selected_package
        )
        self.package_list.currentItemChanged.connect(
            self._on_package_item_changed
        )
        pa.addWidget(self.package_list, 5)

        self.package_info_card = QFrame()
        self.package_info_card.setObjectName("packageInfoCard")
        self.package_info_card.setMinimumHeight(116)
        self.package_info_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        pi = QVBoxLayout(self.package_info_card)
        pi.setContentsMargins(12, 10, 12, 10)
        pi.setSpacing(6)

        pi_head = QHBoxLayout()
        pi_title = QLabel("Seçili Paket")
        pi_title.setObjectName("packageInfoTitle")
        pi_head.addWidget(pi_title)
        pi_head.addStretch(1)
        self.copy_package_link_button = QPushButton(
            "Bağlantıyı Kopyala"
        )
        self.copy_package_link_button.setObjectName("muGhostBtnSmall")
        self.copy_package_link_button.setCursor(Qt.PointingHandCursor)
        self.copy_package_link_button.setEnabled(False)
        self.copy_package_link_button.clicked.connect(
            self._copy_selected_package_link
        )
        pi_head.addWidget(self.copy_package_link_button)
        pi.addLayout(pi_head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)

        def add_quick(caption, value_label, row, column):
            quick = QFrame()
            quick.setObjectName("packageQuickCard")
            ql = QVBoxLayout(quick)
            ql.setContentsMargins(8, 5, 8, 5)
            ql.setSpacing(1)
            cap = QLabel(caption)
            cap.setObjectName("packageQuickCaption")
            value_label.setObjectName("packageQuickValue")
            value_label.setWordWrap(False)
            ql.addWidget(cap)
            ql.addWidget(value_label)
            grid.addWidget(quick, row, column)

        self.package_arch_label = QLabel("—")
        self.package_type_label = QLabel("—")
        self.package_size_label = QLabel("—")
        self.package_link_status = QLabel("—")
        add_quick("Mimari", self.package_arch_label, 0, 0)
        add_quick("Tür", self.package_type_label, 0, 1)
        add_quick("Boyut", self.package_size_label, 1, 0)
        add_quick("Bağlantı", self.package_link_status, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        pi.addLayout(grid)

        self.package_file_label = QLabel(
            "Paket seçildiğinde dosya adı burada gösterilecek."
        )
        self.package_file_label.setObjectName("packageFileLabel")
        self.package_file_label.setWordWrap(True)
        self.package_file_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self.package_file_label.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        pi.addWidget(self.package_file_label)
        pa.addWidget(self.package_info_card, 7)

        # Satır 2: UUP ISO Oluşturucu
        row2 = QFrame()
        row2.setObjectName("muRow")
        r2 = QHBoxLayout(row2)
        r2.setContentsMargins(18, 14, 14, 14)
        r2.setSpacing(14)
        r2.addWidget(_pix_label("cloud-down", self.BLUE, 36, bg="#FFFFFF"), 0, Qt.AlignVCenter)
        t2 = QVBoxLayout()
        t2.setSpacing(2)
        l2 = QLabel("UUP ISO Oluşturucu")
        l2.setObjectName("muRowTitle")
        d2 = QLabel("Bu build için UUP kaynakları üzerinden ISO seçeneklerini açın.")
        d2.setObjectName("muRowDesc")
        d2.setWordWrap(True)
        t2.addWidget(l2)
        t2.addWidget(d2)
        r2.addLayout(t2, 1)
        self.uup_go_button = QPushButton("UUP'ye Git")
        self.uup_go_button.setObjectName("muPrimaryBtn")
        self.uup_go_button.setCursor(Qt.PointingHandCursor)
        self.uup_go_button.setEnabled(False)
        self.uup_go_button.clicked.connect(self._open_uup_for_selected)
        r2.addWidget(self.uup_go_button, 0, Qt.AlignVCenter)
        r2.addWidget(_pix_label("chevron-right", "#6E7F99", 18, stroke=2.1), 0, Qt.AlignVCenter)

        for widget in (row1, self.package_area, row2):
            wrapper = QHBoxLayout()
            wrapper.setContentsMargins(14, 0, 14, 0)
            wrapper.addWidget(widget)
            sv.addLayout(wrapper)

        # Durum notu (paket arama durumu burada gösterilir)
        self.note_frame = QFrame()
        self.note_frame.setObjectName("muNote")
        self.note_frame.setProperty("ok", False)
        nl = QHBoxLayout(self.note_frame)
        nl.setContentsMargins(16, 12, 16, 12)
        nl.setSpacing(14)
        self.note_icon = QLabel()
        self.note_icon.setFixedSize(26, 26)
        nl.addWidget(self.note_icon, 0, Qt.AlignVCenter)
        self.package_status = QLabel("Henüz paket aranmadı.")
        self.package_status.setObjectName("muNoteText")
        self.package_status.setWordWrap(True)
        self.package_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        nl.addWidget(self.package_status, 1)
        note_wrap = QHBoxLayout()
        note_wrap.setContentsMargins(14, 0, 14, 0)
        note_wrap.addWidget(self.note_frame)
        sv.addLayout(note_wrap)

        v.addWidget(section)
        return card

    def _about_row(self, caption, value_label):
        row = QFrame()
        row.setObjectName("muAboutRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(10)
        cap = QLabel(caption)
        cap.setObjectName("muAboutCap")
        value_label.setObjectName("muAboutValue")
        value_label.setWordWrap(True)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        lay.addWidget(cap, 0, Qt.AlignVCenter)
        lay.addWidget(value_label, 1)
        return row

    def _build_about_card(self):
        card = QFrame()
        card.setObjectName("muCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(_pix_label("windows", size=26))
        title = QLabel("Build Hakkında")
        title.setObjectName("muCardTitle")
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)
        v.addSpacing(8)

        self.detail_build = QLabel("—")
        self.detail_version = QLabel("—")
        self.detail_channel = QLabel("—")
        self.detail_date = QLabel("—")
        self.detail_arch = QLabel("—")
        self.detail_language = QLabel("—")
        for caption, label in (
            ("Build Numarası", self.detail_build),
            ("Sürüm", self.detail_version),
            ("Kanal", self.detail_channel),
            ("Yayın Tarihi", self.detail_date),
            ("Mimari", self.detail_arch),
            ("Dil", self.detail_language),
        ):
            v.addWidget(self._about_row(caption, label))

        v.addSpacing(10)
        self.warning_box = QFrame()
        self.warning_box.setObjectName("muWarning")
        wl = QHBoxLayout(self.warning_box)
        wl.setContentsMargins(14, 12, 14, 12)
        wl.setSpacing(12)
        wl.addWidget(_pix_label("warning", "#F2A600", 26, stroke=1.2), 0, Qt.AlignTop)
        wt = QVBoxLayout()
        wt.setSpacing(3)
        wtitle = QLabel("Uyarı")
        wtitle.setObjectName("muWarningTitle")
        wtext = QLabel(
            "Bu build, test amaçlıdır ve kararlı sürüm değildir. "
            "Kullanımda kararsızlıklar yaşanabilir."
        )
        wtext.setObjectName("muWarningText")
        wtext.setWordWrap(True)
        wt.addWidget(wtitle)
        wt.addWidget(wtext)
        wl.addLayout(wt, 1)
        v.addWidget(self.warning_box)
        return card

    def _quick_item(self, icon_name, title, desc, slot):
        item = ClickableCard()
        item.setObjectName("muQuick")
        lay = QHBoxLayout(item)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        tile = QLabel()
        tile.setObjectName("muQuickIcon")
        tile.setFixedSize(44, 44)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap(icon_name, self.BLUE, 26, bg="#EAF2FF", stroke=1.8))
        box = QVBoxLayout()
        box.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("muQuickTitle")
        t.setWordWrap(True)
        d = QLabel(desc)
        d.setObjectName("muQuickDesc")
        d.setWordWrap(True)
        box.addWidget(t)
        box.addWidget(d)
        lay.addWidget(tile, 0, Qt.AlignVCenter)
        lay.addLayout(box, 1)
        lay.addWidget(_pix_label("chevron-right", "#6E7F99", 18, stroke=2.1), 0, Qt.AlignVCenter)
        item.clicked.connect(slot)
        return item

    def _build_quick_card(self):
        card = QFrame()
        card.setObjectName("muCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 18, 16, 16)
        v.setSpacing(12)
        title = QLabel("Hızlı Erişim")
        title.setObjectName("muCardTitle")
        title.setContentsMargins(4, 0, 0, 0)
        v.addWidget(title)
        v.addWidget(self._quick_item(
            "shield", "Microsoft Update Kataloğu",
            "Alternatif kaynaklar ve güncellemeler.", self._open_catalog_site,
        ))
        v.addWidget(self._quick_item(
            "cloud-down", "UUP ISO Oluşturucu",
            "UUP dosyalarını keşfet ve indir.", self._open_uup_center,
        ))
        return card

    def _build_hidden_legacy_widgets(self):
        # Bilgi kartları (Son Arama / Bulunan Kayıt / Arama Türü / Durum) yeni
        # tasarımda görünmez; arama mantığı değerlerini güncellemeye devam eder.
        self.last_search_card = StatCard("Son Arama", "—", "Henüz arama yapılmadı")
        self.count_card = StatCard("Bulunan Kayıt", "0", "Catalog sonuçları")
        self.match_card = StatCard("Arama Türü", "Hazır", "KB veya build bekleniyor")
        self.status_card = StatCard("Durum", "Hazır", "Aramaya hazır")
        for card in (self.last_search_card, self.count_card, self.match_card, self.status_card):
            card.setParent(self)
            card.setVisible(False)

    def _wire_dynamic_visibility(self):
        model = self.results_table.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged):
            signal.connect(self._on_results_changed)
        pmodel = self.package_list.model()
        for signal in (pmodel.rowsInserted, pmodel.rowsRemoved, pmodel.modelReset):
            signal.connect(self._sync_package_area)

    # ------------------------------------------------------------------
    # Görünümle ilgili yardımcılar
    # ------------------------------------------------------------------
    def _on_results_changed(self, *args):
        try:
            count = self.results_table.rowCount()
        except RuntimeError:  # pencere kapanırken Qt nesneleri silinmiş olabilir
            return
        self.results_title.setText(f"Arama Sonuçları ({count})")
        self._results_stack.setCurrentIndex(1 if count > 0 else 0)

    def _sync_package_area(self, *args):
        try:
            has = self.package_list.count() > 0
        except RuntimeError:  # pencere kapanırken Qt nesneleri silinmiş olabilir
            return
        self.package_area.setVisible(has)
        self.note_frame.setProperty("ok", has)
        self.note_icon.setPixmap(
            icons.pixmap(
                "check-circle" if has else "info-fill",
                "#1FA35C" if has else "#5B8FD9",
                26,
                bg="#EAF2FF",
            )
        )
        style = self.note_frame.style()
        style.unpolish(self.note_frame)
        style.polish(self.note_frame)

    @staticmethod
    def _extract_build(item) -> str:
        for text in (getattr(item, "title", ""), getattr(item, "version", "")):
            match = re.search(r"\b(\d{5}\.\d{1,5})\b", text or "")
            if match:
                return match.group(1)
        return "—"

    def _refresh_mockup_fields(self, item=None):
        """Yeni tasarımdaki ek alanları seçili kayda göre günceller."""
        if item is None:
            for label in (self.card_version, self.card_build, self.card_channel, self.card_date):
                label.setText("—")
            self.detail_build.setText("—")
            self.detail_language.setText("—")
            self.build_line.setVisible(False)
            self.result_badge.setVisible(False)
            self.warning_box.setVisible(False)
            self.uup_go_button.setEnabled(False)
            for chip in self._chips:
                chip.setVisible(False)
            return

        build = self._extract_build(item)
        release = self._extract_release(item.title, item.version)
        channel = (getattr(item, "channel", "") or "").strip()
        date = item.last_updated or "—"

        self.card_version.setText(release)
        self.card_build.setText(build)
        self.card_channel.setText(channel or "—")
        self.card_date.setText(date)
        self.detail_build.setText(build)
        language = self.language_filter.currentText().replace("Dil: ", "", 1).strip()
        self.detail_language.setText(language or "—")

        self.result_badge.setVisible(True)
        self.build_line.setText(build if build != "—" else "")
        self.build_line.setVisible(build != "—")
        self.uup_go_button.setEnabled(True)

        low_channel = channel.casefold()
        is_test_build = any(
            key in low_channel
            for key in ("canary", "dev", "beta", "insider", "preview")
        )
        self.warning_box.setVisible(is_test_build)

        for chip in self._chips:
            text = (chip.text() or "").strip()
            chip.setVisible(text not in ("", "—"))

    def _relayout_responsive(self):
        width = self.width()
        wide_cols = width >= 1180
        wide_filters = width >= 1560

        if wide_cols != self._wide_cols:
            self._wide_cols = wide_cols
            self._cols.removeWidget(self._left_col)
            self._cols.removeWidget(self._right_col)
            if wide_cols:
                self._cols.addWidget(self._left_col, 0, 0)
                self._cols.addWidget(self._right_col, 0, 1, Qt.AlignTop)
                self._cols.setColumnStretch(1, 0)
                self._right_col.setFixedWidth(306)
            else:
                self._cols.addWidget(self._left_col, 0, 0)
                self._cols.addWidget(self._right_col, 1, 0)
                self._right_col.setMinimumWidth(0)
                self._right_col.setMaximumWidth(16777215)

        if wide_filters != self._wide_filters:
            self._wide_filters = wide_filters
            grid = self._results_header
            grid.removeWidget(self._results_title_box)
            grid.removeWidget(self._filters_box)
            for col in range(2):
                grid.setColumnStretch(col, 0)
            self._arrange_filters(wide_filters)
            if wide_filters:
                grid.addWidget(self._results_title_box, 0, 0)
                grid.addWidget(self._filters_box, 0, 1)
                grid.setColumnStretch(1, 1)
            else:
                grid.addWidget(self._results_title_box, 0, 0)
                grid.addWidget(self._filters_box, 1, 0)
                grid.setColumnStretch(0, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_responsive()

    def _open_catalog_site(self):
        webbrowser.open("https://www.catalog.update.microsoft.com/")

    def _open_uup_center(self):
        window = self.window()
        if hasattr(window, "show_page_by_name"):
            window.show_page_by_name("UUP ISO Oluşturucu")

    def _apply_page_styles(self):
        self.setStyleSheet(
            styles.qss('''
            QScrollArea#muScroll { background: transparent; border: none; }
            QWidget#muContent { background: #F4F7FB; }

            QLabel#muTitle { font-size: 30px; font-weight: 700; color: #0A1F44; }
            QLabel#muSubtitle { font-size: 14px; color: #5F7090; }

            QLineEdit#muSearch {
                background: #FFFFFF; border: 1px solid #C7D5E8; border-radius: 11px;
                padding: 0 14px 0 18px; font-size: 17px; color: #0F2347; min-height: 50px; max-height: 50px;
                selection-background-color: #1F6FEB;
            }
            QLineEdit#muSearch:focus { border: 2px solid #1F6FEB; }
            QPushButton#muSearchBtn {
                background: @BLUE@; color: #FFFFFF; border: none; border-radius: 11px;
                font-size: 15px; font-weight: 700; padding: 0 26px;
                min-height: 52px; max-height: 52px;
            }
            QPushButton#dangerButton { min-height: 50px; max-height: 50px; border-radius: 11px; padding: 0 18px; font-size: 13px; }
            QPushButton#muSearchBtn:hover { background: #1259C4; }
            QPushButton#muSearchBtn:disabled { background: #AFC4E6; color: #EEF3FB; }

            QFrame#muCard {
                background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px;
            }
            QWidget#muCardHeader { background: transparent; }
            QLabel#muCardTitle { font-size: 16px; font-weight: 700; color: #0F2347; }
            QStackedWidget#muResultsStack { background: transparent; }

            QLabel#muEmptyStatus { font-size: 14px; font-weight: 600; color: #3E5276; }
            QLabel#muEmptyHint { font-size: 12px; color: #7E8EA8; }

            QTableWidget#muTable {
                background: #FFFFFF; border: none; border-top: 1px solid #E6EDF6;
                border-bottom-left-radius: 13px; border-bottom-right-radius: 13px;
                alternate-background-color: #FAFCFE;
                selection-background-color: #E4EFFD; selection-color: #0F2347;
                color: #1B2B48; font-size: 12px; outline: none;
            }
            QTableWidget#muTable::item {
                padding: 4px 10px; border: none; border-bottom: 1px solid #EEF2F8;
            }
            QTableWidget#muTable::item:hover { background: #F2F7FE; }
            QTableWidget#muTable::item:selected,
            QTableWidget#muTable::item:selected:active,
            QTableWidget#muTable::item:selected:!active {
                background: #E4EFFD; color: #0F2347; border-bottom: 1px solid #D5E5FA;
            }
            QTableWidget#muTable QHeaderView::section {
                background: #F6F9FD; color: #51627F; font-size: 12px; font-weight: 700;
                border: none; border-bottom: 1px solid #E3EAF4; padding: 0 12px;
            }
            QTableWidget#muTable QTableCornerButton::section { background: #F6F9FD; border: none; }

            QLabel#muLogoTile {
                background: #EDF4FE; border: 1px solid #DCE8F8; border-radius: 16px;
            }
            QLabel#muBadge {
                background: #E4F6EA; color: #1C8A4D; border: 1px solid #C4E8D1;
                border-radius: 9px; padding: 2px 10px; font-size: 11px; font-weight: 600;
            }
            QLabel#muSelTitle { font-size: 20px; font-weight: 700; color: #0F2347; }
            QLabel#muSelBuild { font-size: 17px; font-weight: 500; color: #3C4F72; }
            QLabel#muChip {
                background: #F1F5FB; color: #4A5D7A; border: 1px solid #E0E8F3;
                border-radius: 10px; padding: 3px 10px; font-size: 11px; font-weight: 500;
            }

            QPushButton#muGhostBtn {
                background: #FFFFFF; color: #1A5FD0; border: 1px solid #CBD9EC;
                border-radius: 10px; padding: 8px 16px; font-size: 12px; font-weight: 600;
                min-height: 20px;
            }
            QPushButton#muGhostBtn:hover { background: #F2F7FF; border-color: #9DBBEA; }
            QPushButton#muGhostBtn:disabled { background: #F6F8FB; color: #9AA9BF; border-color: #E1E8F2; }
            QPushButton#muGhostBtnSmall {
                background: #FFFFFF; color: #1A5FD0; border: 1px solid #CBD9EC;
                border-radius: 8px; padding: 3px 10px; font-size: 11px; font-weight: 600;
                min-height: 16px;
            }
            QPushButton#muGhostBtnSmall:hover { background: #F2F7FF; }
            QPushButton#muGhostBtnSmall:disabled { background: #F6F8FB; color: #9AA9BF; border-color: #E1E8F2; }
            QPushButton#muPrimaryBtn {
                background: @BLUE@; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 10px 22px; font-size: 13px; font-weight: 700; min-height: 22px;
                min-width: 118px;
            }
            QPushButton#muPrimaryBtn:hover { background: #1259C4; }
            QPushButton#muPrimaryBtn:disabled { background: #B9CBE8; color: #F2F6FC; }

            QFrame#muMetaCard {
                background: #FFFFFF; border: 1px solid #DEE7F3; border-radius: 12px;
            }
            QLabel#muMetaIcon { background: #EAF2FE; border-radius: 21px; }
            QLabel#muMetaCaption { font-size: 12px; color: #6E7F99; }
            QLabel#muMetaValue { font-size: 17px; font-weight: 700; color: #0F2347; }

            QFrame#muSection { background: #F4F7FC; border: 1px solid #E3EAF4; border-radius: 12px; }
            QLabel#muSectionTitle {
                font-size: 15px; font-weight: 700; color: #0F2347;
                padding: 14px 18px 4px 18px;
            }
            QFrame#muRow { background: #FFFFFF; border: 1px solid #DCE6F2; border-radius: 11px; }
            QLabel#muRowTitle { font-size: 14px; font-weight: 700; color: #0F2347; }
            QLabel#muRowDesc { font-size: 12px; color: #6E7F99; }
            QFrame#muPackageArea { background: #FFFFFF; border: 1px solid #DCE6F2; border-radius: 11px; }

            QFrame#muNote { background: #EAF2FE; border: 1px solid #CFE0F7; border-radius: 11px; }
            QFrame#muNote[ok="true"] { background: #E8F6EE; border: 1px solid #C3E6D2; }
            QLabel#muNoteText { font-size: 12px; color: #34527F; }
            QFrame#muNote[ok="true"] QLabel#muNoteText { color: #2D6A47; }

            QFrame#muAboutRow { background: transparent; border: none; border-bottom: 1px solid #EEF2F8; }
            QLabel#muAboutCap { font-size: 13px; color: #6E7F99; }
            QLabel#muAboutValue { font-size: 13px; font-weight: 700; color: #0F2347; }

            QFrame#muWarning { background: #FFF7E1; border: 1px solid #F4DFA3; border-radius: 11px; }
            QLabel#muWarningTitle { font-size: 13px; font-weight: 700; color: #1E2A44; }
            QLabel#muWarningText { font-size: 11px; color: #8A6A1F; }

            QFrame#muQuick { background: #FFFFFF; border: 1px solid #DCE6F2; border-radius: 12px; }
            QFrame#muQuick:hover { background: #F5F9FF; border-color: #B5CCEE; }
            QLabel#muQuickIcon { background: #EAF2FE; border-radius: 12px; }
            QLabel#muQuickTitle { font-size: 13px; font-weight: 700; color: #0F2347; }
            QLabel#muQuickDesc { font-size: 11px; color: #7787A1; }

            QComboBox#modernComboBox {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 10px;
                padding: 0 24px 0 10px; font-size: 11px; color: #2B3B58; min-height: 38px; max-height: 38px;
            }
            QComboBox#modernComboBox[popupOpen="true"] { border: 1px solid #1F6FEB; }
            ''')
        )

    def _detect_query_type(self, query: str) -> str:
        q = query.strip().lower()
        if re.fullmatch(r"kb\s*\d+", q):
            return "KB"
        if re.fullmatch(r"\d{4,5}\.\d{1,5}", q):
            return "Build"
        if parse_version_query(query):
            return "Sürüm (ISO)"
        return "Genel"

    def start_search(self):
        try:
            query = self.search_input.text().strip()
            if not query:
                show_information(self, "Arama", "KB veya build numarası girin.")
                return
            if self._thread and self._thread.isRunning():
                return

            self._last_results = []
            self.results_table.setRowCount(0)
            self.search_button.setEnabled(False)
            self.stop_button.setEnabled(True)

            query_type = self._detect_query_type(query)
        except Exception as exc:
            self.search_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            show_error(self, "Arama başlatılamadı", str(exc))
            return
        self.last_search_card.value_label.setText(query)
        self.last_search_card.note_label.setText("Son çalıştırılan sorgu")
        self.match_card.value_label.setText(query_type)
        self.match_card.note_label.setText("Algılanan arama tipi")
        self.status_card.value_label.setText("Aranıyor")
        self.status_card.note_label.setText("Microsoft kaynakları kontrol ediliyor")
        self.count_card.value_label.setText("0")

        self.status_label.setText(f"{query} Microsoft resmi kaynaklarında aranıyor...")

        self._thread = QThread(self)
        arch = self.arch_filter.currentText().replace("Mimari: ", "", 1).strip()
        iso_archs = ("x64", "ARM64") if arch == "Tümü" else (("ARM64",) if arch == "ARM64" else ("x64",))
        self._worker = CatalogSearchWorker(query, architectures=iso_archs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def stop_search(self):
        if self._thread and self._thread.isRunning():
            self._thread.requestInterruption()
            self._thread.quit()
            self.status_label.setText("Arama kullanıcı tarafından durduruldu.")
            self.status_card.value_label.setText("Durduruldu")
            self.status_card.note_label.setText("Kullanıcı işlemi iptal etti")
        self.search_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def _sort_results(self, results):
        order = {"x64": 0, "ARM64": 1, "x86": 2, "Belirsiz": 3}
        def score(item):
            arch = order.get(item.architecture, 9)
            title = item.title.lower()
            insider_penalty = 1 if "insider" in title else 0
            return (insider_penalty, arch, title)
        return sorted(results, key=score)

    def _extract_kb(self, title: str) -> str:
        m = re.search(r"(KB\d+)", title, re.I)
        return m.group(1).upper() if m else "—"

    def _extract_release(self, title: str, fallback: str) -> str:
        m = re.search(r"version\s+([0-9A-Za-zH]+)", title, re.I)
        if m:
            return m.group(1).upper()
        if fallback and fallback.lower() != "yok":
            return fallback
        m = re.search(r"(2[4-9]H[1-2])", title, re.I)
        if m:
            return m.group(1).upper()
        return "—"

    def _set_explanation(self, query: str, result_count: int):
        query_type = self._detect_query_type(query)
        if query_type == "Build":
            self.explainer_label.setText(
                "Bu arama bir build numarasıyla yapıldı. Program Microsoft Update Catalog ile birlikte resmi Microsoft Insider kaynaklarını da kontrol eder. Catalog kaydı yoksa Flight Hub sonucu gösterilebilir."
            )
        elif query_type == "Sürüm (ISO)":
            self.explainer_label.setText(
                "Bu arama bir Windows sürüm adıyla yapıldı. Listede iki kaynak çıkar: Microsoft'un resmi sitesindeki ISO "
                "(Microsoft yalnızca güncel sürümü sunar) ve UUP ile hazırlanan en son yayın build'i. Birini seçip ISO Merkezi'nde devam edin."
            )
        elif query_type == "KB":
            self.explainer_label.setText(
                "Bu arama bir KB numarasıyla yapıldı. Aşağıda Microsoft Update Catalog'da bulunan resmi KB kayıtları listelenir."
            )
        else:
            self.explainer_label.setText(
                f"Arama metninize göre Microsoft Update Catalog'dan {result_count} resmi kayıt bulundu."
            )

    @staticmethod
    def _normalize_classification(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return "—"

        low = text.casefold()
        mappings = (
            (("security update", "security updates", "보안 업데이트", "安全更新", "güvenlik"), "Güvenlik Güncellemesi"),
            (("critical update", "critical updates", "중요 업데이트", "关键更新"), "Kritik Güncelleme"),
            (("definition update", "definition updates", "정의 업데이트", "定义更新"), "Tanım Güncellemesi"),
            (("driver", "drivers", "드라이버", "驱动"), "Sürücü"),
            (("update rollup", "rollup", "업데이트 롤업"), "Güncelleştirme Paketi"),
            (("update", "updates", "업데이트", "更新"), "Güncelleme"),
        )
        for needles, translated in mappings:
            if any(needle in low for needle in needles):
                return translated
        return text

    @staticmethod
    def _normalize_product(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return "—"
        # Catalog bazı bölgelerde ürün adını yerelleştirebilir. Bilinen Windows
        # ürün adlarını kullanıcıya tutarlı biçimde gösteriyoruz.
        low = text.casefold()
        if "windows 11" in low:
            return "Windows 11"
        if "windows 10" in low:
            return "Windows 10"
        if "server" in low:
            return text.replace("Microsoft ", "").strip()
        return text

    def _display_title(self, item) -> str:
        title = (item.title or "").strip()
        # Microsoft Update Catalog, kullanıcının bölgesine göre Korece/Çince gibi
        # yerelleştirilmiş başlık döndürebiliyor. Latin olmayan bir başlıkta bilgi
        # kaybetmeden Türkçe, yapılandırılmış bir başlık üretiriz.
        has_non_latin = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", title))
        if not has_non_latin:
            return title

        kb = self._extract_kb(title)
        release = self._extract_release(title, item.version)
        product = self._normalize_product(item.product)
        arch = item.architecture if item.architecture != "—" else ""

        parts = []
        if product != "—":
            parts.append(product)
        if release != "—":
            parts.append(release)
        if kb != "—":
            parts.append(kb)
        if arch:
            parts.append(arch)
        return " • ".join(parts) + " güncellemesi" if parts else "Microsoft Windows güncellemesi"

    def _row_icon(self):
        if not hasattr(self, "_row_icon_cache"):
            self._row_icon_cache = icons.icon("windows", size=26)
        return self._row_icon_cache

    def _chevron_icon(self):
        if not hasattr(self, "_chevron_icon_cache"):
            self._chevron_icon_cache = icons.icon("chevron-right", "#7586A0", 18, stroke=2.1)
        return self._chevron_icon_cache

    def _fill_table(self, results):
        self._displayed_results = list(results)
        self._selected_result = None
        self._reset_detail_panel()
        self.results_table.setRowCount(len(results))
        for row, item in enumerate(results):
            values = [
                self._display_title(item),
                self._extract_release(item.title, item.version),
                self._extract_kb(item.title),
                item.architecture,
                item.size,
                item.last_updated,
                self._normalize_classification(item.classification),
                self._normalize_product(item.product),
                getattr(item, "source", "Microsoft"),
            ]
            for col, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if col == 0:
                    table_item.setIcon(self._row_icon())
                else:
                    table_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.results_table.setItem(row, col, table_item)
            arrow_item = QTableWidgetItem()
            arrow_item.setIcon(self._chevron_icon())
            arrow_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(row, 9, arrow_item)


    def _on_selection_changed(self):
        selected = self.results_table.selectionModel().selectedRows()
        if not selected:
            self._selected_result = None
            self._reset_detail_panel()
            return

        row = selected[0].row()
        if row < 0 or row >= len(self._displayed_results):
            return

        self._selected_result = self._displayed_results[row]
        self._update_detail_panel(self._selected_result)

    def _on_result_double_clicked(self, row, column):
        if row < 0 or row >= len(self._displayed_results):
            return
        self._selected_result = self._displayed_results[row]
        self._update_detail_panel(self._selected_result)
        self.detail_panel.setFocus()

    def _reset_detail_panel(self):
        self.detail_name.setText(
            "Detayları görmek için listeden bir kayıt seçin."
        )
        self.detail_version.setText("—")
        self.detail_kb.setText("—")
        self.detail_arch.setText("—")
        self.detail_size.setText("—")
        self.detail_date.setText("—")
        self.detail_classification.setText("—")
        self.detail_product.setText("—")
        self.detail_source.setText("—")
        self.detail_channel.setText("—")
        self.package_card_title.setText("Microsoft Güncelleme Paketi")
        self.package_card_desc.setText(
            "Resmi Microsoft güncelleme paketini (MSU/CAB) bulun ve indirin. Bu bir ISO değildir; "
            "ISO için aşağıdaki UUP ISO Oluşturucu'yu kullanın."
        )
        self.find_packages_button.setEnabled(False)
        self.open_source_button.setEnabled(False)
        self.favorite_button.setEnabled(False)
        self.package_list.clear()
        self.package_file_label.setText("Paket seçildiğinde tam dosya adı burada gösterilecek.")
        self.package_link_status.setText("—")
        self.copy_package_link_button.setEnabled(False)
        self.package_status.setText("Henüz paket aranmadı.")
        self.open_package_button.setEnabled(False)
        self._refresh_mockup_fields(None)

    def _update_detail_panel(self, item):
        self.detail_name.setText(self._display_title(item))
        self.detail_version.setText(self._extract_release(item.title, item.version))
        self.detail_kb.setText(self._extract_kb(item.title))
        self.detail_arch.setText(item.architecture or "—")
        self.detail_size.setText(item.size or "—")
        self.detail_date.setText(item.last_updated or "—")
        self.detail_classification.setText(self._normalize_classification(item.classification))
        self.detail_product.setText(self._normalize_product(item.product))
        self.detail_source.setText(getattr(item, "source", "") or "Microsoft")
        self.detail_channel.setText(getattr(item, "channel", "") or "—")

        kb_value = self._extract_kb(item.title)
        is_uup_iso = self._is_iso_row(item)
        if is_uup_iso:
            self.package_card_title.setText("Windows ISO (Microsoft / UUP)")
            self.package_card_desc.setText(
                "Microsoft'tan İndir, ISO Merkezi'ni açar. Dil ve mimariyi seçip indirmeyi başlatırsınız; program önce Microsoft'un "
                "resmi ISO'sunu dener, sürümü sunmuyorsa ya da isteği reddederse ISO'yu UUP ile kendisi hazırlar."
            )
            self.find_packages_button.setText("ISO Seçenekleri")
        else:
            self.package_card_title.setText("Microsoft Güncelleme Paketi")
            self.package_card_desc.setText(
                "Resmi Microsoft güncelleme paketini (MSU/CAB) bulun ve indirin. Bu bir ISO değildir; "
                "ISO için aşağıdaki UUP ISO Oluşturucu'yu kullanın."
            )
            if kb_value == "—":
                self.find_packages_button.setText("UUP / ISO Seçenekleri")
            else:
                self.find_packages_button.setText("Paketleri Bul")
        self.find_packages_button.setEnabled(True)
        self.open_source_button.setEnabled(
            bool(getattr(item, "source_url", ""))
        )
        self.favorite_button.setEnabled(True)
        self.package_list.clear()
        self.package_status.setText("Henüz paket aranmadı.")
        self.open_package_button.setEnabled(is_uup_iso)
        self._refresh_mockup_fields(item)

    def _open_uup_for_selected(self):
        """Seçili kaydı UUP / ISO Merkezi'ne build bağlamıyla taşır."""
        if self._selected_result is None:
            return

        if getattr(self._selected_result, "source", "") == "Microsoft ISO":
            show_message(
                self, "UUP / ISO Merkezi", "Bu kayıt Microsoft'un resmi ISO'su",
                "Bu kaydın bir build numarası yok. UUP ile hazırlamak için listedeki UUP satırını seçin ya da ISO Merkezi'nde Kaynak: UUP'yi seçin.",
            )
            return

        kb = self._extract_kb(self._selected_result.title)
        is_uup_iso = getattr(self._selected_result, "source", "") == "Microsoft UUP"
        if is_uup_iso:
            build = self._extract_build(self._selected_result)
        elif kb == "—":
            build = self._extract_release(
                self._selected_result.title,
                self._selected_result.version,
            )
        else:
            build = self._extract_build(self._selected_result)
            if build == "—":
                build = self._extract_release(
                    self._selected_result.title,
                    self._selected_result.version,
                )
        window = self.window()
        try:
            uup_page = window.page_by_name("UUP ISO Oluşturucu") if hasattr(window, "page_by_name") else None
            if uup_page is None:
                raise RuntimeError("UUP ISO Oluşturucu bulunamadı.")
            if hasattr(uup_page, "set_build_context"):
                uup_page.set_build_context(
                    build,
                    self._selected_result.title,
                    getattr(self._selected_result, "channel", ""),
                    getattr(self._selected_result, "source", ""),
                )
            if is_uup_iso:
                # Update Center'da seçilen mimari ve dil, UUP sayfasında hazır gelsin.
                self._preselect_uup_options(uup_page, self._selected_result.architecture)
            if hasattr(window, "show_page_by_name"):
                window.show_page_by_name("UUP ISO Oluşturucu")
        except Exception:
            show_message(
                self,
                "UUP / ISO Merkezi",
                "Bu build KB tabanlı değil",
                "Seçili Insider build için doğrudan KB bulunamadı. UUP / ISO Merkezi üzerinden devam edin.",
            )

    ISO_SOURCES = ("Microsoft ISO", "Microsoft UUP")

    @classmethod
    def _is_iso_row(cls, item) -> bool:
        return getattr(item, "source", "") in cls.ISO_SOURCES

    def _open_iso_center_for_selected(self):
        """ISO satırını ISO Merkezi'ndeki 'ISO İndir' paneline taşır (dil, mimari orada seçilir)."""
        item = self._selected_result
        if item is None:
            return
        window = self.window()
        iso_page = window.page_by_name("ISO Merkezi") if hasattr(window, "page_by_name") else None
        if iso_page is None or not hasattr(iso_page, "set_download_context"):
            show_message(self, "ISO Merkezi", "ISO Merkezi açılamadı", "ISO Merkezi sayfası bulunamadı.")
            return
        language = self.language_filter.currentText().replace("Dil: ", "", 1).strip()
        iso_page.set_download_context(
            "auto",
            version=item.version,
            build=(self._extract_build(item) if self._extract_build(item) != "—" else ""),
            architecture=item.architecture,
            language=None if language in ("", "Tümü") else language,
        )
        if hasattr(window, "show_page_by_name"):
            window.show_page_by_name("ISO Merkezi")

    def _preselect_uup_options(self, uup_page, architecture: str) -> None:
        picks = []
        if architecture in ("x64", "ARM64", "x86"):
            picks.append((getattr(uup_page, "arch_combo", None), architecture))
        language = self.language_filter.currentText().replace("Dil: ", "", 1).strip()
        if language and language != "Tümü":
            picks.append((getattr(uup_page, "language_combo", None), language))
        for combo, text in picks:
            if combo is None:
                continue
            index = combo.findText(text)
            if index >= 0:
                combo.setCurrentIndex(index)

    def _prepare_package_lookup(self):
        if self._selected_result is None:
            return

        if self._is_iso_row(self._selected_result):
            self._open_iso_center_for_selected()
            return

        kb = self._extract_kb(
            self._selected_result.title
        )

        if kb == "—":
            self._open_uup_for_selected()
            return

        if (
            self._package_thread
            and self._package_thread.isRunning()
        ):
            return

        self.package_list.clear()
        self._packages = []

        self.package_status.setText(
            f"{kb} için Microsoft paketleri aranıyor..."
        )

        self.find_packages_button.setEnabled(False)
        self.open_package_button.setEnabled(False)

        self._package_thread = QThread(self)
        self._package_worker = PackageLookupWorker(kb)
        self._package_worker.moveToThread(
            self._package_thread
        )

        self._package_thread.started.connect(
            self._package_worker.run
        )
        self._package_worker.finished.connect(
            self._on_packages_found
        )
        self._package_worker.failed.connect(
            self._on_package_lookup_failed
        )

        self._package_worker.finished.connect(
            self._package_thread.quit
        )
        self._package_worker.failed.connect(
            self._package_thread.quit
        )

        self._package_thread.finished.connect(
            self._cleanup_package_thread
        )

        self._package_thread.start()

    def _on_packages_found(self, packages):
        self._packages = list(packages)
        self.package_list.clear()

        if not self._packages:
            self.package_status.setText(
                "Catalog kaydı bulundu fakat bu kaydın doğrudan indirme "
                "bağlantısı Microsoft yanıtından ayrıştırılamadı."
            )
            self.find_packages_button.setText(
                "Paketleri Yeniden Dene"
            )
            self.find_packages_button.setEnabled(True)
            return

        self.package_status.setText(
            f"{len(self._packages)} resmi Microsoft paketi bulundu. "
            "İndirmek istediğiniz mimariyi seçin."
        )

        for index, package in enumerate(
            self._packages
        ):
            summary = (
                f"{package.architecture} • "
                f"{package.file_type} • "
                f"{package.size}"
            )

            list_item = QListWidgetItem(summary)
            list_item.setData(Qt.UserRole, index)
            self.package_list.addItem(list_item)

        preferred_row = 0
        for index, package in enumerate(self._packages):
            if package.architecture == self.system_profile.architecture:
                preferred_row = index
                break
        self.package_list.setCurrentRow(preferred_row)
        self.open_package_button.setEnabled(True)

        self.find_packages_button.setText(
            "Paketleri Yenile"
        )
        self.find_packages_button.setEnabled(True)

    def _on_package_lookup_failed(
        self,
        message,
    ):
        self.package_status.setText(
            "Paket bağlantıları alınamadı."
        )
        self.find_packages_button.setText(
            "Paketleri Yeniden Dene"
        )
        self.find_packages_button.setEnabled(True)
        self.package_file_label.setText("Paket ayrıntıları alınamadı.")
        self.package_link_status.setText("Alınamadı")
        self.copy_package_link_button.setEnabled(False)

        show_message(
            self,
            "Paket Arama Hatası",
            "Microsoft paket bağlantıları alınamadı",
            message,
        )

    def _cleanup_package_thread(self):
        if self._package_worker is not None:
            self._package_worker.deleteLater()

        if self._package_thread is not None:
            self._package_thread.deleteLater()

        self._package_worker = None
        self._package_thread = None

    def _on_package_item_changed(
        self,
        current,
        previous=None,
    ):
        if current is None:
            self.package_file_label.setText(
                "Paket seçildiğinde tam dosya adı burada gösterilecek."
            )
            self.package_link_status.setText(
                "Microsoft bağlantısı: —"
            )
            self.package_arch_label.setText("—")
            self.package_type_label.setText("—")
            self.package_size_label.setText("—")
            self.copy_package_link_button.setEnabled(False)
            self.open_package_button.setEnabled(False)
            return

        index = current.data(Qt.UserRole)
        if index is None:
            self.package_file_label.setText(
                "Seçili paketin ayrıntıları okunamadı."
            )
            self.package_link_status.setText(
                "Microsoft bağlantısı: alınamadı"
            )
            self.package_arch_label.setText("—")
            self.package_type_label.setText("—")
            self.package_size_label.setText("—")
            self.copy_package_link_button.setEnabled(False)
            self.open_package_button.setEnabled(False)
            return

        try:
            package = self._packages[int(index)]
        except Exception:
            self.package_file_label.setText(
                "Seçili paketin ayrıntıları okunamadı."
            )
            self.package_link_status.setText(
                "Microsoft bağlantısı: alınamadı"
            )
            self.package_arch_label.setText("—")
            self.package_type_label.setText("—")
            self.package_size_label.setText("—")
            self.copy_package_link_button.setEnabled(False)
            self.open_package_button.setEnabled(False)
            return

        self.package_arch_label.setText(package.architecture or "—")
        self.package_type_label.setText(package.file_type or "—")
        self.package_size_label.setText(package.size or "—")
        self.package_file_label.setText(package.filename or "—")

        if package.direct_url:
            self.package_link_status.setText(
                "Microsoft bağlantısı: Hazır ✓"
            )
            self.package_link_status.setToolTip(
                package.direct_url
            )
            self.copy_package_link_button.setEnabled(True)
            self.open_package_button.setEnabled(True)
        else:
            self.package_link_status.setText(
                "Microsoft bağlantısı: alınamadı"
            )
            self.package_link_status.setToolTip("")
            self.copy_package_link_button.setEnabled(False)
            self.open_package_button.setEnabled(False)

    def _copy_selected_package_link(self):
        current = self.package_list.currentItem()
        if current is None:
            return

        index = current.data(Qt.UserRole)
        if index is None:
            return

        try:
            package = self._packages[int(index)]
        except Exception:
            return

        if not package.direct_url:
            return

        QApplication.clipboard().setText(
            package.direct_url
        )
        self.package_link_status.setText(
            "Microsoft bağlantısı: Panoya kopyalandı ✓"
        )

    def _open_selected_package(
        self,
        *args,
    ):
        if self._is_iso_row(self._selected_result):
            # ISO kayıtlarında bu düğme ISO Merkezi'ne götürür (dil, mimari orada seçilir, indirme orada başlar).
            self._open_iso_center_for_selected()
            return

        current = self.package_list.currentItem()
        if current is None:
            return

        index = current.data(Qt.UserRole)
        if index is None:
            return

        try:
            package = self._packages[int(index)]
        except Exception:
            return

        if not package.direct_url:
            return

        default_name = package.filename or "Microsoft_Update_Package"
        settings = SettingsService.load()
        base_folder = str(settings.get("downloads", {}).get("default_folder", "") or "").strip()
        initial_path = str(Path(base_folder) / default_name) if base_folder and Path(base_folder).exists() else default_name
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Microsoft paketini kaydet",
            initial_path,
            "Tüm Dosyalar (*.*)",
        )
        if not target_path:
            return

        DownloadManager.instance().add_download(
            package,
            target_path,
        )
        self.package_link_status.setText(
            "İndirme Yöneticisine eklendi ✓"
        )


    def _open_selected_source(self):
        if self._selected_result is None:
            return
        url = getattr(
            self._selected_result,
            "source_url",
            "",
        )
        if not url:
            show_information(
                self,
                "Microsoft Sayfası",
                "Bu kayıt için kaynak sayfası bulunamadı."
            )
            return
        webbrowser.open(url)

    def _refresh_search_completer(self):
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT query FROM search_history GROUP BY query "
                    "ORDER BY MAX(id) DESC LIMIT 50"
                ).fetchall()
            values = [str(row[0]) for row in rows if row and row[0]]
            completer = QCompleter(values, self.search_input)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            # Yazılan ifadeyle başlayan geçmiş aramalar tamamlayıcı olarak önerilir.
            completer.setFilterMode(Qt.MatchStartsWith)
            completer.setMaxVisibleItems(8)
            popup = completer.popup()
            popup.setItemDelegate(CompletionDelegate(self.search_input, popup))
            popup.setMouseTracking(True)
            popup.setFrameShape(QFrame.NoFrame)
            popup.setStyleSheet(
                "QListView { background: #FFFFFF; border: 1px solid #B9CCE8;"
                " border-radius: 10px; padding: 4px; outline: none; }"
            )
            self.search_input.setCompleter(completer)
            self._search_completer = completer
        except Exception:
            self._search_completer = None

    def _add_selected_to_favorites(self):
        if self._selected_result is None:
            return

        item = self._selected_result
        metadata = {
            "title": item.title,
            "version": item.version,
            "architecture": item.architecture,
            "classification": item.classification,
            "product": item.product,
            "source": getattr(item, "source", ""),
            "source_url": getattr(item, "source_url", ""),
            "channel": getattr(item, "channel", ""),
        }

        item_key = (
            getattr(item, "update_id", "")
            or f"{item.title}|{item.version}"
        )

        try:
            with get_connection() as conn:
                exists = conn.execute(
                    "SELECT id FROM favorites "
                    "WHERE item_key = ? LIMIT 1",
                    (item_key,),
                ).fetchone()

                if exists:
                    show_information(
                        self,
                        "Favoriler",
                        "Bu kayıt zaten favorilerde."
                    )
                    return

                conn.execute(
                    "INSERT INTO favorites "
                    "(item_type, item_key, title, metadata_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "update",
                        item_key,
                        item.title,
                        json.dumps(
                            metadata,
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.commit()

            show_information(
                self,
                "Favoriler",
                "Kayıt favorilere eklendi."
            )
        except Exception as exc:
            show_warning(
                self,
                "Favori eklenemedi",
                str(exc),
            )

    def apply_filters(self):
        if not self._last_results:
            return

        filtered = []
        selected_arch = self.arch_filter.currentText().replace("Mimari: ", "", 1)
        selected_type = self.type_filter.currentText()
        selected_version = self.version_filter.currentText().replace("Windows Sürümü: ", "", 1)

        for item in self._last_results:
            if selected_arch != "Tümü" and item.architecture != selected_arch:
                continue

            normalized_type = self._normalize_classification(item.classification).casefold()
            if selected_type == "Tür: Güvenlik Güncellemeleri" and "güvenlik" not in normalized_type:
                continue
            if selected_type == "Tür: Genel Güncellemeler" and not any(
                token in normalized_type for token in ("güncelleme", "paketi", "kritik")
            ):
                continue
            if selected_type == "Tür: Sürücüler" and "sürücü" not in normalized_type:
                continue

            if selected_version != "Tümü":
                release = self._extract_release(item.title, item.version)
                if release != selected_version:
                    continue

            filtered.append(item)

        self._fill_table(filtered)
        self.count_card.value_label.setText(str(len(filtered)))
        self.count_card.note_label.setText("Filtrelenmiş sonuç sayısı")

    def _on_finished(self, results):
        if self._thread and self._thread.isInterruptionRequested():
            return

        query = self.search_input.text().strip()
        results = self._sort_results(results)
        self._last_results = results
        self._fill_table(results)

        self.search_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.count_card.value_label.setText(str(len(results)))
        self.count_card.note_label.setText("Catalog sonuçları")
        self.status_card.value_label.setText("Tamamlandı")
        self.status_card.note_label.setText("Arama başarıyla tamamlandı")

        if results and all(self._is_iso_row(r) for r in results):
            self.status_label.setText(
                f"{query} için ISO bulundu. Seçip Microsoft'tan İndir'e basın; dil ve mimariyi ISO Merkezi'nde seçersiniz. "
                "Program önce Microsoft'un sitesinden dener, yoksa UUP ile hazırlar."
            )
        elif results:
            self.status_label.setText(f"{query} için {len(results)} güncelleme kaydı bulundu.")
        else:
            self.status_label.setText(
                f"{query} için Microsoft Update Catalog üzerinde eşleşen kayıt bulunamadı."
            )
        self._set_explanation(query, len(results))

        try:
            with get_connection() as conn:
                conn.execute("INSERT INTO search_history(query) VALUES (?)", (query,))
                conn.execute(
                    "DELETE FROM search_history WHERE id NOT IN "
                    "(SELECT id FROM search_history ORDER BY id DESC LIMIT 100)"
                )
                conn.commit()
            self._refresh_search_completer()
        except Exception:
            pass
        self.search_completed.emit()

    def _on_failed(self, message):
        self.search_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Arama başarısız.")
        self.status_card.value_label.setText("Hata")
        self.status_card.note_label.setText("Arama tamamlanamadı")
        self.explainer_label.setText("Arama sırasında Catalog yanıtı okunamadı veya sonuç bulunamadı.")
        show_warning(
            self,
            "Arama tamamlanamadı",
            message if parse_version_query(self.search_input.text())
            else message + "\n\nNot: Insider build'leri Microsoft Update Catalog'da bulunmayabilir; program Flight Hub'ı da kontrol eder."
        )

    def _cleanup_thread(self):
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
