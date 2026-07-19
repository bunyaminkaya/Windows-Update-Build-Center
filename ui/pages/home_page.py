from pathlib import Path
import re
import json
import webbrowser
from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton,  QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QSizePolicy, QListWidget, QListWidgetItem, QApplication, QScrollArea, QFileDialog, QCompleter, QDialog
)

from database.connection import get_connection
from workers.catalog_search_worker import CatalogSearchWorker
from workers.package_lookup_worker import PackageLookupWorker
from services.download_manager import DownloadManager
from services.system_profile import SystemProfileService
from services.settings_service import SettingsService
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


class HomePage(QWidget):
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)

        subtitle = QLabel("KB numarası veya Windows build numarasıyla resmi Microsoft güncellemelerini bulun, filtreleyin ve doğrudan indirin.")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        search_card = QFrame()
        search_card.setObjectName("searchCard")
        s = QVBoxLayout(search_card)
        s.setContentsMargins(16, 16, 16, 16)
        s.setSpacing(12)

        top = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("KB5101650 veya 26200.8875 gibi bir değer girin...")
        self.search_input.returnPressed.connect(self.start_search)
        self._refresh_search_completer()

        self.search_button = QPushButton("Ara")
        self.search_button.clicked.connect(self.start_search)

        self.stop_button = QPushButton("Aramayı Durdur")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_search)

        top.addWidget(self.search_input, 1)
        top.addWidget(self.search_button)
        top.addWidget(self.stop_button)
        s.addLayout(top)

        filters = QHBoxLayout()
        filters.setSpacing(10)

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
        self.language_filter.addItems(["Dil: Tümü"])
        self.language_filter.setToolTip("Paket dili filtresi. Catalog sonucu dil bilgisi sağladığında seçenekler otomatik genişletilebilir.")

        self.version_filter = ModernComboBox()
        self.version_filter.addItems([
            "Windows Sürümü: Tümü",
            "Windows Sürümü: 24H2",
            "Windows Sürümü: 25H2",
            "Windows Sürümü: 26H1",
            "Windows Sürümü: 26H2",
        ])
        self.version_filter.setToolTip("Windows sürümünü / özellik güncellemesi dalını filtreler.")
        for combo in [self.source_filter, self.type_filter, self.arch_filter, self.language_filter, self.version_filter]:
            combo.currentIndexChanged.connect(self.apply_filters)
            filters.addWidget(combo)
        s.addLayout(filters)
        layout.addWidget(search_card)

        stats = QGridLayout()
        self.last_search_card = StatCard("Son Arama", "—", "Henüz arama yapılmadı")
        self.count_card = StatCard("Bulunan Kayıt", "0", "Catalog sonuçları")
        self.match_card = StatCard("Arama Türü", "Hazır", "KB veya build bekleniyor")
        self.status_card = StatCard("Durum", "Hazır", "Aramaya hazır")
        stats.addWidget(self.last_search_card, 0, 0)
        stats.addWidget(self.count_card, 0, 1)
        stats.addWidget(self.match_card, 0, 2)
        stats.addWidget(self.status_card, 0, 3)
        layout.addLayout(stats)

        self.status_label = QLabel("Hazır. KB veya build numarası girerek arama yapabilirsiniz.")
        self.status_label.setObjectName("infoBox")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.explainer_label = QLabel("Burada bulunan sonuçlar, Microsoft Update Catalog'un döndürdüğü resmi kayıtlardır.")
        self.explainer_label.setObjectName("subtleInfoBox")
        self.explainer_label.setWordWrap(True)
        layout.addWidget(self.explainer_label)

        self.results_table = QTableWidget(0, 9)
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
        ])
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.setShowGrid(False)
        self.results_table.setFocusPolicy(Qt.NoFocus)
        self.results_table.setWordWrap(False)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.verticalHeader().setDefaultSectionSize(34)
        header = self.results_table.horizontalHeader()
        header.setStretchLastSection(False)

        # Öncelikli sütunlar daha geniş ve görünür tutulur.
        header.setSectionResizeMode(0, QHeaderView.Stretch)           # Başlık
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents) # Sürüm / Build
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents) # KB
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents) # Mimari
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents) # Boyut
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents) # Tarih
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents) # Sınıflandırma
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents) # Ürün
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents) # Kaynak

        self.results_table.setColumnWidth(1, 120)
        self.results_table.setColumnWidth(2, 100)
        self.results_table.setColumnWidth(3, 85)
        self.results_table.setColumnWidth(4, 100)
        self.results_table.setColumnWidth(5, 100)

        self.results_table.itemSelectionChanged.connect(
            self._on_selection_changed
        )
        self.results_table.cellDoubleClicked.connect(
            self._on_result_double_clicked
        )

        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("detailPanel")
        self.detail_panel.setMinimumWidth(430)
        self.detail_panel.setMaximumWidth(620)

        detail_outer_layout = QVBoxLayout(self.detail_panel)
        detail_outer_layout.setContentsMargins(0, 0, 0, 0)
        detail_outer_layout.setSpacing(0)

        # Scrollable content prevents labels and package cards from being
        # compressed when Windows scaling or window height changes.
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("detailScroll")
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.detail_scroll.setFrameShape(QFrame.NoFrame)

        detail_content = QWidget()
        detail_content.setObjectName("detailScrollContent")
        detail_layout = QVBoxLayout(detail_content)
        detail_layout.setContentsMargins(18, 18, 18, 16)
        detail_layout.setSpacing(10)

        detail_title = QLabel("Seçili Kayıt")
        detail_title.setObjectName("detailTitle")
        detail_layout.addWidget(detail_title)

        self.detail_name = QLabel(
            "Detayları görmek için listeden bir kayıt seçin."
        )
        self.detail_name.setObjectName("detailName")
        self.detail_name.setWordWrap(True)
        self.detail_name.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Minimum,
        )
        detail_layout.addWidget(self.detail_name)

        # Compact metadata cards use the empty horizontal space in the
        # selected-record panel and keep package information higher on screen.
        metadata_frame = QFrame()
        metadata_frame.setObjectName("detailMetadataGrid")
        metadata_grid = QGridLayout(metadata_frame)
        metadata_grid.setContentsMargins(0, 0, 0, 0)
        metadata_grid.setHorizontalSpacing(8)
        metadata_grid.setVerticalSpacing(8)

        def create_meta_card(caption, value_label, row, column, column_span=1):
            card = QFrame()
            card.setObjectName("detailMetaCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 7, 10, 7)
            card_layout.setSpacing(1)

            caption_label = QLabel(caption)
            caption_label.setObjectName("detailMetaCaption")
            value_label.setObjectName("detailMetaValue")
            value_label.setWordWrap(True)
            value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

            card_layout.addWidget(caption_label)
            card_layout.addWidget(value_label)
            metadata_grid.addWidget(card, row, column, 1, column_span)

        def create_dual_meta_card(caption_left, value_left, caption_right, value_right, row, column):
            card = QFrame()
            card.setObjectName("detailMetaCard")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 7, 10, 7)
            card_layout.setSpacing(14)

            left_layout = QVBoxLayout()
            left_layout.setSpacing(1)
            left_caption = QLabel(caption_left)
            left_caption.setObjectName("detailMetaCaption")
            value_left.setObjectName("detailMetaValue")
            value_left.setWordWrap(False)
            left_layout.addWidget(left_caption)
            left_layout.addWidget(value_left)

            right_layout = QVBoxLayout()
            right_layout.setSpacing(1)
            right_caption = QLabel(caption_right)
            right_caption.setObjectName("detailMetaCaption")
            value_right.setObjectName("detailMetaValue")
            value_right.setWordWrap(False)
            right_layout.addWidget(right_caption)
            right_layout.addWidget(value_right)

            card_layout.addLayout(left_layout, 1)
            card_layout.addLayout(right_layout, 1)
            metadata_grid.addWidget(card, row, column)

        self.detail_version = QLabel("—")
        self.detail_kb = QLabel("—")
        self.detail_arch = QLabel("—")
        self.detail_size = QLabel("—")
        self.detail_date = QLabel("—")
        self.detail_channel = QLabel("—")
        self.detail_classification = QLabel("—")
        self.detail_source = QLabel("—")
        self.detail_product = QLabel("—")

        create_dual_meta_card("Sürüm / Build", self.detail_version, "KB", self.detail_kb, 0, 0)
        create_dual_meta_card("Mimari", self.detail_arch, "Boyut", self.detail_size, 0, 1)
        create_dual_meta_card("Yayın Tarihi", self.detail_date, "Kanal", self.detail_channel, 0, 2)
        create_meta_card("Sınıflandırma", self.detail_classification, 1, 0, 2)
        create_meta_card("Kaynak", self.detail_source, 1, 2)
        create_meta_card("Ürün", self.detail_product, 2, 0, 3)

        metadata_grid.setColumnStretch(0, 1)
        metadata_grid.setColumnStretch(1, 1)
        metadata_grid.setColumnStretch(2, 1)
        detail_layout.addWidget(metadata_frame)

        package_title = QLabel("İndirme Paketleri")
        package_title.setObjectName("detailSectionTitle")
        detail_layout.addWidget(package_title)

        self.package_status = QLabel("Henüz paket aranmadı.")
        self.package_status.setObjectName("detailMeta")
        self.package_status.setWordWrap(True)
        self.package_status.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Minimum,
        )
        detail_layout.addWidget(self.package_status)

        package_workspace = QFrame()
        package_workspace.setObjectName("packageWorkspace")
        package_workspace_layout = QHBoxLayout(package_workspace)
        package_workspace_layout.setContentsMargins(0, 0, 0, 0)
        package_workspace_layout.setSpacing(8)

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
        package_workspace_layout.addWidget(self.package_list, 5)

        # The previously unused area is now a compact selected-package summary.
        self.package_info_card = QFrame()
        self.package_info_card.setObjectName("packageInfoCard")
        self.package_info_card.setMinimumHeight(116)
        self.package_info_card.setMaximumHeight(156)
        self.package_info_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )
        package_info_layout = QVBoxLayout(self.package_info_card)
        package_info_layout.setContentsMargins(10, 8, 10, 8)
        package_info_layout.setSpacing(5)

        package_info_title = QLabel("Seçili Paket")
        package_info_title.setObjectName("packageInfoTitle")
        package_info_layout.addWidget(package_info_title)

        package_quick_grid = QGridLayout()
        package_quick_grid.setHorizontalSpacing(6)
        package_quick_grid.setVerticalSpacing(5)

        def add_package_quick_item(caption, value_label, row, column):
            card = QFrame()
            card.setObjectName("packageQuickCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(7, 5, 7, 5)
            card_layout.setSpacing(1)
            caption_label = QLabel(caption)
            caption_label.setObjectName("packageQuickCaption")
            value_label.setObjectName("packageQuickValue")
            value_label.setWordWrap(False)
            card_layout.addWidget(caption_label)
            card_layout.addWidget(value_label)
            package_quick_grid.addWidget(card, row, column)

        self.package_arch_label = QLabel("—")
        self.package_type_label = QLabel("—")
        self.package_size_label = QLabel("—")
        self.package_link_status = QLabel("—")

        add_package_quick_item("Mimari", self.package_arch_label, 0, 0)
        add_package_quick_item("Tür", self.package_type_label, 0, 1)
        add_package_quick_item("Boyut", self.package_size_label, 1, 0)
        add_package_quick_item("Bağlantı", self.package_link_status, 1, 1)
        package_quick_grid.setColumnStretch(0, 1)
        package_quick_grid.setColumnStretch(1, 1)
        package_info_layout.addLayout(package_quick_grid)

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
        package_info_layout.addWidget(self.package_file_label)

        package_workspace_layout.addWidget(self.package_info_card, 7)
        detail_layout.addWidget(package_workspace)

        # Package action buttons live in the fixed footer below.
        # Keeping them out of the scroll area makes them permanently visible.
        detail_layout.addStretch(1)

        self.detail_scroll.setWidget(detail_content)
        detail_outer_layout.addWidget(self.detail_scroll, 1)

        # Fixed action footer stays visible; only the record/package details
        # above it scroll when vertical space is limited.
        detail_footer = QFrame()
        detail_footer.setObjectName("detailFooter")
        footer_layout = QVBoxLayout(detail_footer)
        footer_layout.setContentsMargins(14, 10, 14, 14)
        footer_layout.setSpacing(8)

        fixed_package_action_row = QHBoxLayout()
        fixed_package_action_row.setSpacing(8)

        self.copy_package_link_button = QPushButton(
            "Bağlantıyı Kopyala"
        )
        self.copy_package_link_button.setObjectName("fixedPackageActionButton")
        self.copy_package_link_button.setEnabled(False)
        self.copy_package_link_button.clicked.connect(
            self._copy_selected_package_link
        )
        fixed_package_action_row.addWidget(self.copy_package_link_button)

        self.open_package_button = QPushButton(
            "Microsoft'tan İndir"
        )
        self.open_package_button.setObjectName("fixedPackageActionButton")
        self.open_package_button.setEnabled(False)
        self.open_package_button.clicked.connect(
            self._open_selected_package
        )
        fixed_package_action_row.addWidget(self.open_package_button)

        footer_layout.addLayout(fixed_package_action_row)

        self.find_packages_button = QPushButton("Paketleri Bul")
        self.find_packages_button.setEnabled(False)
        self.find_packages_button.clicked.connect(
            self._prepare_package_lookup
        )

        self.open_source_button = QPushButton(
            "Microsoft Sayfasını Aç"
        )
        self.open_source_button.setEnabled(False)
        self.open_source_button.clicked.connect(
            self._open_selected_source
        )

        self.favorite_button = QPushButton("Favorilere Ekle")
        self.favorite_button.setEnabled(False)
        self.favorite_button.clicked.connect(
            self._add_selected_to_favorites
        )
        self.view_favorites_button = QPushButton("Favorilerim")
        self.view_favorites_button.clicked.connect(self._show_favorites_dialog)

        footer_layout.addWidget(self.find_packages_button)
        footer_layout.addWidget(self.open_source_button)
        footer_layout.addWidget(self.favorite_button)
        footer_layout.addWidget(self.view_favorites_button)
        detail_outer_layout.addWidget(detail_footer, 0)

        splitter = QSplitter()
        splitter.setObjectName("resultSplitter")
        splitter.addWidget(self.results_table)
        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([820, 500])

        layout.addWidget(splitter, 1)

    def _detect_query_type(self, query: str) -> str:
        q = query.strip().lower()
        if re.fullmatch(r"kb\s*\d+", q):
            return "KB"
        if re.fullmatch(r"\d{4,5}\.\d{1,5}", q):
            return "Build"
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
        self._worker = CatalogSearchWorker(query)
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
                if col != 0:
                    table_item.setTextAlignment(Qt.AlignCenter)
                self.results_table.setItem(row, col, table_item)


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
        self.find_packages_button.setEnabled(False)
        self.open_source_button.setEnabled(False)
        self.favorite_button.setEnabled(False)
        self.package_list.clear()
        self.package_file_label.setText("Paket seçildiğinde tam dosya adı burada gösterilecek.")
        self.package_link_status.setText("—")
        self.copy_package_link_button.setEnabled(False)
        self.package_status.setText("Henüz paket aranmadı.")
        self.open_package_button.setEnabled(False)

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
        self.open_package_button.setEnabled(False)

    def _prepare_package_lookup(self):
        if self._selected_result is None:
            return

        kb = self._extract_kb(
            self._selected_result.title
        )

        if kb == "—":
            build = self._extract_release(
                self._selected_result.title,
                self._selected_result.version,
            )
            window = self.window()
            try:
                uup_page = window.page_by_name("UUP Merkezi") if hasattr(window, "page_by_name") else None
                if uup_page is None:
                    raise RuntimeError("UUP Merkezi bulunamadı.")
                if hasattr(uup_page, "set_build_context"):
                    uup_page.set_build_context(
                        build,
                        self._selected_result.title,
                        getattr(self._selected_result, "channel", ""),
                        getattr(self._selected_result, "source", ""),
                    )
                if hasattr(window, "show_page_by_name"):
                    window.show_page_by_name("UUP Merkezi")
            except Exception:
                show_message(
                    self,
                    "UUP / ISO Merkezi",
                    "Bu build KB tabanlı değil",
                    "Seçili Insider build için doğrudan KB bulunamadı. UUP / ISO Merkezi üzerinden devam edin.",
                )
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
            completer.setFilterMode(Qt.MatchContains)
            self.search_input.setCompleter(completer)
            self._search_completer = completer
        except Exception:
            self._search_completer = None

    def _show_favorites_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Favorilerim")
        dialog.resize(720, 430)
        layout = QVBoxLayout(dialog)
        info = QLabel("Kaydettiğiniz güncelleme kayıtlarını buradan açabilir veya silebilirsiniz.")
        info.setWordWrap(True)
        layout.addWidget(info)
        listing = QListWidget()
        layout.addWidget(listing, 1)

        def reload_items():
            listing.clear()
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, title, metadata_json FROM favorites ORDER BY id DESC"
                ).fetchall()
            for fav_id, title, metadata_json in rows:
                item = QListWidgetItem(str(title))
                try:
                    metadata = json.loads(metadata_json or "{}")
                except Exception:
                    metadata = {}
                item.setData(Qt.UserRole, {
                    "id": fav_id,
                    "url": metadata.get("source_url", ""),
                })
                listing.addItem(item)

        buttons = QHBoxLayout()
        open_btn = QPushButton("Microsoft Sayfasını Aç")
        delete_btn = QPushButton("Favoriden Sil")
        close_btn = QPushButton("Kapat")
        buttons.addWidget(open_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        def open_selected():
            item = listing.currentItem()
            data = item.data(Qt.UserRole) if item else {}
            url = (data or {}).get("url", "")
            if url:
                webbrowser.open(url)
            else:
                show_information(dialog, "Favoriler", "Bu kayıt için Microsoft kaynak bağlantısı bulunmuyor.")

        def delete_selected():
            item = listing.currentItem()
            data = item.data(Qt.UserRole) if item else {}
            fav_id = (data or {}).get("id")
            if not fav_id:
                return
            with get_connection() as conn:
                conn.execute("DELETE FROM favorites WHERE id = ?", (fav_id,))
                conn.commit()
            reload_items()

        open_btn.clicked.connect(open_selected)
        delete_btn.clicked.connect(delete_selected)
        close_btn.clicked.connect(dialog.accept)
        listing.itemDoubleClicked.connect(lambda _item: open_selected())
        reload_items()
        dialog.exec()

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

        if results:
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
            message + "\n\nNot: Insider build'leri Microsoft Update Catalog'da bulunmayabilir; program Flight Hub'ı da kontrol eder."
        )

    def _cleanup_thread(self):
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
