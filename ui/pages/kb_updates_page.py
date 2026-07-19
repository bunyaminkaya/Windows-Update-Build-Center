from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.build_tracker_service import BuildTrackerRecord, BuildTrackerService
from services.settings_service import SettingsService
from ui.widgets.message_dialog import show_error, show_information
from ui.widgets.modern_combo_box import ModernComboBox


class TrackerFetchWorker(QThread):
    loaded = Signal(object, str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            records, last_update = BuildTrackerService().fetch()
            self.loaded.emit(records, last_update)
        except Exception as exc:
            self.failed.emit(str(exc))


class NewUpdateCard(QFrame):
    clicked = Signal(object)

    def __init__(self, record: BuildTrackerRecord, parent=None):
        super().__init__(parent)
        self.record = record
        self.setObjectName("newUpdateCard")
        self.setCursor(Qt.PointingHandCursor)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        icon = QLabel("▣")
        icon.setObjectName("windowsTileIcon")
        icon.setFixedSize(42, 42)
        icon.setAlignment(Qt.AlignCenter)
        root.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(2)
        kb = QLabel(record.kb_number or f"Build {record.build_number}")
        kb.setObjectName("newUpdateTitle")
        version = QLabel(f"Windows 11 {record.windows_version or ''}".strip())
        version.setObjectName("newUpdateMeta")
        build = QLabel(f"OS Build {record.build_number}")
        build.setObjectName("newUpdateMeta")
        date = QLabel(_display_date(record.release_date))
        date.setObjectName("newUpdateDate")
        text.addWidget(kb)
        text.addWidget(version)
        text.addWidget(build)
        text.addWidget(date)
        root.addLayout(text, 1)

        badge = QLabel(_kind_text(record))
        badge.setObjectName("updateKindBadge")
        badge.setProperty("kind", _kind_key(record))
        badge.setAlignment(Qt.AlignCenter)
        root.addWidget(badge, 0, Qt.AlignTop)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.record)


def _display_date(value: str) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        return value


def _kind_key(record: BuildTrackerRecord) -> str:
    channel = (record.channel or "").lower()
    if "retail" in channel or channel == "ga" or "ga / retail" in channel:
        return "security"
    if "preview" in channel or "beta" in channel or "experimental" in channel:
        return "preview"
    if "dev" in channel or "canary" in channel:
        return "insider"
    return "neutral"


def _kind_text(record: BuildTrackerRecord) -> str:
    key = _kind_key(record)
    return {
        "security": "Güvenlik",
        "preview": "Önizleme",
        "insider": "Insider",
        "neutral": record.channel or "Build",
    }.get(key, "Build")


class BuildTrackerTable(QTableWidget):
    """Build Tracker tablosu için yerleşik Qt sağ tık menüsü.

    QTableWidget bir QAbstractItemView olduğu için gerçek fare olayları viewport
    üzerinde oluşur. Bu nedenle ActionsContextMenu politikası doğrudan viewport'a
    uygulanır; menüyü Qt'nin kendisi oluşturup açar.
    """

    copy_kb_requested = Signal(int)
    copy_build_requested = Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.copy_kb_action = QAction("KB Numarasını Kopyala", self)
        self.copy_build_action = QAction("Build Numarasını Kopyala", self)
        self.copy_kb_action.triggered.connect(
            lambda _checked=False: self.copy_kb_requested.emit(self.currentRow())
        )
        self.copy_build_action.triggered.connect(
            lambda _checked=False: self.copy_build_requested.emit(self.currentRow())
        )

        # Sağ tık olayını alan gerçek widget viewport'tur. Qt'nin kendi
        # ActionsContextMenu mekanizması kullanıldığı için özel QMenu/eventFilter
        # koduna ihtiyaç yoktur.
        self.viewport().setContextMenuPolicy(Qt.ActionsContextMenu)
        self.viewport().addAction(self.copy_kb_action)
        self.viewport().addAction(self.copy_build_action)

        # Klavye Menü tuşu gibi durumlarda da tablo üzerinde aynı eylemler hazır olsun.
        self.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.addAction(self.copy_kb_action)
        self.addAction(self.copy_build_action)

        self._update_context_actions(-1)

    def _update_context_actions(self, row: int) -> None:
        kb_item = self.item(row, 0) if row >= 0 else None
        build_item = self.item(row, 2) if row >= 0 else None
        kb_value = (kb_item.text() if kb_item else "").strip()
        build_value = (build_item.text() if build_item else "").strip()
        self.copy_kb_action.setEnabled(bool(kb_value and kb_value != "—"))
        self.copy_build_action.setEnabled(bool(build_value and build_value != "—"))

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                row = item.row()
                self.setCurrentCell(row, item.column())
                self.selectRow(row)
                self._update_context_actions(row)
            else:
                self._update_context_actions(-1)
        super().mousePressEvent(event)


class KbUpdatesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[BuildTrackerRecord] = []
        self.filtered_records: list[BuildTrackerRecord] = []
        self.selected_record: BuildTrackerRecord | None = None
        self.last_update = ""
        self.worker: TrackerFetchWorker | None = None
        self._build_ui()
        self._apply_styles()

        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.timeout.connect(self.refresh)
        self.apply_settings(SettingsService.load())

        # Önbelleği anında göster; canlı kontrol ayarlardaki tercihe göre yapılır.
        self._load_cache_then_refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        subtitle = QLabel(
            "Windows build ve KB güncellemelerini keşfedin, filtreleyin ve resmi Microsoft kaynaklarına erişin."
        )
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        refresh_box = QVBoxLayout()
        refresh_box.setContentsMargins(0, 0, 0, 0)
        refresh_box.setSpacing(5)

        self.refresh_button = QPushButton("Şimdi Güncelle")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)
        refresh_box.addWidget(self.refresh_button, 0, Qt.AlignRight)

        self.freshness = QLabel("Son güncelleme: —")
        self.freshness.setObjectName("freshnessInfo")
        self.freshness.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.freshness.setToolTip(
            "Kaynak: https://bunyaminkaya.com/windows-build-tracker/\n"
            "Program açılışında ve her saat otomatik olarak kontrol edilir."
        )
        refresh_box.addWidget(self.freshness, 0, Qt.AlignRight)

        header.addLayout(refresh_box)
        root.addLayout(header)

        latest_box = QFrame()
        latest_box.setObjectName("latestPanel")
        latest_layout = QVBoxLayout(latest_box)
        latest_layout.setContentsMargins(14, 12, 14, 14)
        latest_layout.setSpacing(10)
        latest_header = QHBoxLayout()
        latest_title = QLabel("Yeni Güncellemeler")
        latest_title.setObjectName("sectionTitle")
        self.latest_count = QLabel("Son yayınlanan build kayıtları")
        self.latest_count.setObjectName("sectionHint")
        latest_header.addWidget(latest_title)
        latest_header.addStretch()
        latest_header.addWidget(self.latest_count)
        latest_layout.addLayout(latest_header)
        self.latest_cards_layout = QHBoxLayout()
        self.latest_cards_layout.setSpacing(10)
        latest_layout.addLayout(self.latest_cards_layout)
        root.addWidget(latest_box)

        body = QHBoxLayout()
        body.setSpacing(12)

        # Left filters
        filter_panel = QFrame()
        filter_panel.setObjectName("filterPanel")
        filter_panel.setFixedWidth(225)
        fp = QVBoxLayout(filter_panel)
        fp.setContentsMargins(14, 14, 14, 14)
        fp.setSpacing(10)

        fh = QHBoxLayout()
        ft = QLabel("Filtreler")
        ft.setObjectName("panelTitle")
        clear = QPushButton("Temizle")
        clear.setObjectName("textButton")
        clear.clicked.connect(self._clear_filters)
        fh.addWidget(ft)
        fh.addStretch()
        fh.addWidget(clear)
        fp.addLayout(fh)

        self.search = QLineEdit()
        self.search.setObjectName("filterSearch")
        self.search.setPlaceholderText("Build veya KB ara...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filters)
        fp.addWidget(self.search)

        fp.addWidget(self._small_label("Windows Sürümü"))
        self.version_combo = ModernComboBox()
        self.version_combo.addItems(["Windows Sürümü: Tümü", "Windows Sürümü: 26H2", "Windows Sürümü: 26H1", "Windows Sürümü: 25H2", "Windows Sürümü: 24H2", "Windows Sürümü: 23H2", "Windows Sürümü: Future Platforms"])
        self.version_combo.currentTextChanged.connect(self.apply_filters)
        fp.addWidget(self.version_combo)

        fp.addWidget(self._small_label("Mimari"))
        self.arch_x64 = QCheckBox("x64")
        self.arch_x64.setChecked(True)
        self.arch_arm64 = QCheckBox("ARM64")
        self.arch_arm64.setChecked(True)
        self.arch_x64.stateChanged.connect(self.apply_filters)
        self.arch_arm64.stateChanged.connect(self.apply_filters)
        fp.addWidget(self.arch_x64)
        fp.addWidget(self.arch_arm64)

        fp.addWidget(self._small_label("Güncelleme Türü"))
        self.type_security = QCheckBox("GA / Retail")
        self.type_preview = QCheckBox("Önizleme / Beta")
        self.type_insider = QCheckBox("Dev / Canary / Insider")
        for cb in (self.type_security, self.type_preview, self.type_insider):
            cb.setChecked(True)
            cb.stateChanged.connect(self.apply_filters)
            fp.addWidget(cb)

        fp.addWidget(self._small_label("Tarih Aralığı"))
        self.date_combo = ModernComboBox()
        self.date_combo.addItems(["Tarih Aralığı: Tümü", "Tarih Aralığı: Son 30 gün", "Tarih Aralığı: Son 90 gün", "Tarih Aralığı: Bu yıl"])
        self.date_combo.currentTextChanged.connect(self.apply_filters)
        fp.addWidget(self.date_combo)

        self.apply_button = QPushButton("Filtreleri Uygula")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self.apply_filters)
        fp.addWidget(self.apply_button)
        fp.addStretch()
        body.addWidget(filter_panel)

        # Center list
        center = QFrame()
        center.setObjectName("listPanel")
        cp = QVBoxLayout(center)
        cp.setContentsMargins(12, 12, 12, 12)
        cp.setSpacing(8)

        list_header = QHBoxLayout()
        self.result_info = QLabel("Kayıtlar yükleniyor...")
        self.result_info.setObjectName("resultInfo")
        list_header.addWidget(self.result_info)
        list_header.addStretch()
        sort_label = QLabel("Sırala:")
        sort_label.setObjectName("sectionHint")
        self.sort_combo = ModernComboBox()
        self.sort_combo.addItems(["Sıralama: Yayın Tarihi (En Yeni)", "Sıralama: Build (Yüksek)", "Sıralama: KB Numarası"])
        self.sort_combo.currentTextChanged.connect(self.apply_filters)
        list_header.addWidget(sort_label)
        list_header.addWidget(self.sort_combo)
        cp.addLayout(list_header)

        self.table = BuildTrackerTable(0, 6)
        self.table.setObjectName("buildTable")
        self.table.setHorizontalHeaderLabels(["KB Numarası", "Windows Sürümü", "Build", "Yayın Tarihi", "Tür", "Kanal"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(1, 145)
        self.table.setColumnWidth(2, 130)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 105)
        self.table.cellClicked.connect(self._table_clicked)

        # Qt'nin viewport üzerindeki yerleşik ActionsContextMenu sistemi.
        self.table.copy_kb_requested.connect(self._copy_kb_from_row)
        self.table.copy_build_requested.connect(self._copy_build_from_row)
        cp.addWidget(self.table, 1)
        body.addWidget(center, 1)

        # Right details
        details = QFrame()
        details.setObjectName("detailsPanel")
        details.setFixedWidth(390)
        dp = QVBoxLayout(details)
        dp.setContentsMargins(16, 16, 16, 16)
        dp.setSpacing(10)

        self.detail_title = QLabel("Bir güncelleme seçin")
        self.detail_title.setObjectName("detailTitle")
        self.detail_badge = QLabel("")
        self.detail_badge.setObjectName("updateKindBadge")
        detail_head = QHBoxLayout()
        detail_head.addWidget(self.detail_title, 1)
        detail_head.addWidget(self.detail_badge, 0, Qt.AlignTop)
        dp.addLayout(detail_head)

        self.detail_grid = QVBoxLayout()
        self.detail_labels: dict[str, QLabel] = {}
        for key, caption in (
            ("version", "Windows Sürümü"),
            ("build", "Build"),
            ("date", "Yayın Tarihi"),
            ("channel", "Kanal"),
            ("group", "Yayın Grubu"),
            ("kb", "KB Numarası"),
        ):
            row = QHBoxLayout()
            left = QLabel(caption)
            left.setObjectName("detailKey")
            value = QLabel("—")
            value.setObjectName("detailValue")
            value.setWordWrap(True)
            row.addWidget(left)
            row.addStretch()
            row.addWidget(value)
            self.detail_grid.addLayout(row)
            self.detail_labels[key] = value
        dp.addLayout(self.detail_grid)

        sep = QFrame()
        sep.setObjectName("softSeparator")
        sep.setFrameShape(QFrame.HLine)
        dp.addWidget(sep)

        description_title = QLabel("Açıklama")
        description_title.setObjectName("panelTitle")
        self.detail_description = QLabel("Seçilen build kaydının açıklaması burada gösterilir.")
        self.detail_description.setObjectName("detailDescription")
        self.detail_description.setWordWrap(True)
        dp.addWidget(description_title)
        dp.addWidget(self.detail_description)

        article_title = QLabel("İlgili İçerik")
        article_title.setObjectName("panelTitle")
        self.article_link = QPushButton("İlgili yazıyı aç")
        self.article_link.setObjectName("secondaryButton")
        self.article_link.clicked.connect(self._open_article)
        dp.addWidget(article_title)
        dp.addWidget(self.article_link)

        actions_title = QLabel("İşlemler")
        actions_title.setObjectName("panelTitle")
        dp.addWidget(actions_title)
        self.package_button = QPushButton("Microsoft Paketlerini Aç")
        self.package_button.setObjectName("primaryButton")
        self.package_button.clicked.connect(self._open_microsoft)
        dp.addWidget(self.package_button)

        note = QLabel("İndirme işlemleri Microsoft'un resmi kaynakları üzerinden gerçekleştirilir.")
        note.setObjectName("infoNote")
        note.setWordWrap(True)
        dp.addStretch()
        dp.addWidget(note)
        body.addWidget(details)

        root.addLayout(body, 1)

    @staticmethod
    def _small_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("filterLabel")
        return label

    def _load_cache_then_refresh(self) -> None:
        records, last_update, fetched_at = BuildTrackerService.load_cache()
        if records:
            self.records = records
            self.last_update = last_update
            self._update_freshness(fetched_at)
            self.apply_filters()
        settings = SettingsService.load()
        general = settings.get("general", {})
        tracker = settings.get("build_tracker", {})
        if general.get("check_tracker_on_start", True) and tracker.get("refresh_on_start", True):
            self.refresh()

    def apply_settings(self, settings) -> None:
        tracker = dict((settings or {}).get("build_tracker", {}))
        minutes = int(tracker.get("refresh_interval_minutes", 60) or 60)
        minutes = max(30, minutes)
        self.auto_refresh_timer.setInterval(minutes * 60 * 1000)
        if not self.auto_refresh_timer.isActive():
            self.auto_refresh_timer.start()

    def refresh(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Güncelleniyor...")
        self.worker = TrackerFetchWorker(self)
        self.worker.loaded.connect(self._on_loaded)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_loaded(self, records, last_update: str) -> None:
        self.records = list(records)
        self.last_update = last_update
        self._update_freshness(datetime.now().isoformat(timespec="seconds"))
        self.freshness.setToolTip(
            "Kaynak: https://bunyaminkaya.com/windows-build-tracker/\n"
            "Program açılışında ve her saat otomatik olarak kontrol edilir."
        )
        self.apply_filters()

    def _on_failed(self, message: str) -> None:
        if not self.records:
            show_error(self, "Windows Build Tracker", message)
        else:
            # Son başarılı güncelleme zamanı ekranda kalır; mevcut önbellek kullanılmaya devam eder.
            self.freshness.setToolTip(
                "Canlı güncelleme alınamadı. Son başarılı veriler gösteriliyor.\n"
                "Kaynak: https://bunyaminkaya.com/windows-build-tracker/"
            )

    def _on_finished(self) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Şimdi Güncelle")

    def _combo_value(self, text: str) -> str:
        return text.split(": ", 1)[1] if ": " in text else text

    def _update_freshness(self, fetched_at: str) -> None:
        stamp = ""
        if fetched_at:
            try:
                stamp = datetime.fromisoformat(fetched_at).strftime("%d.%m.%Y %H:%M")
            except Exception:
                stamp = fetched_at

        if stamp:
            self.freshness.setText(f"Son güncelleme: {stamp}")
        else:
            self.freshness.setText("Son güncelleme: —")

    def _clear_filters(self) -> None:
        self.search.clear()
        self.version_combo.setCurrentIndex(0)
        self.date_combo.setCurrentIndex(0)
        self.arch_x64.setChecked(True)
        self.arch_arm64.setChecked(True)
        self.type_security.setChecked(True)
        self.type_preview.setChecked(True)
        self.type_insider.setChecked(True)
        self.apply_filters()

    def apply_filters(self, *_args) -> None:
        text = self.search.text().strip().lower()
        version = self._combo_value(self.version_combo.currentText())
        date_filter = self._combo_value(self.date_combo.currentText())
        allowed_kinds = set()
        if self.type_security.isChecked():
            allowed_kinds.add("security")
        if self.type_preview.isChecked():
            allowed_kinds.add("preview")
        if self.type_insider.isChecked():
            allowed_kinds.add("insider")
        allowed_kinds.add("neutral")

        now = datetime.now()
        rows = []
        for record in self.records:
            if text and text not in record.search_text:
                continue
            if version != "Tümü" and (record.windows_version or "") != version:
                continue
            if _kind_key(record) not in allowed_kinds:
                continue
            if date_filter != "Tümü" and record.release_date:
                try:
                    dt = datetime.strptime(record.release_date, "%Y-%m-%d")
                    days = (now - dt).days
                    if date_filter == "Son 30 gün" and days > 30:
                        continue
                    if date_filter == "Son 90 gün" and days > 90:
                        continue
                    if date_filter == "Bu yıl" and dt.year != now.year:
                        continue
                except Exception:
                    pass
            rows.append(record)

        sort_mode = self._combo_value(self.sort_combo.currentText())
        if sort_mode == "Build (Yüksek)":
            def build_key(r):
                try:
                    return tuple(int(x) for x in r.build_number.split("."))
                except Exception:
                    return (0,)
            rows.sort(key=build_key, reverse=True)
        elif sort_mode == "KB Numarası":
            rows.sort(key=lambda r: r.kb_number or "", reverse=True)
        else:
            rows.sort(key=lambda r: r.release_date or "", reverse=True)

        self.filtered_records = rows
        self._render_latest(rows)
        self._render_table(rows)

    def _render_latest(self, rows: list[BuildTrackerRecord]) -> None:
        while self.latest_cards_layout.count():
            item = self.latest_cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        latest = rows[:3]
        for record in latest:
            card = NewUpdateCard(record)
            card.clicked.connect(self._select_record)
            self.latest_cards_layout.addWidget(card, 1)
        if not latest:
            empty = QLabel("Filtrelere uygun yeni güncelleme bulunamadı.")
            empty.setObjectName("sectionHint")
            self.latest_cards_layout.addWidget(empty)
        self.latest_count.setText(f"{len(rows)} kayıt içinde en yeni {len(latest)} kayıt")

    def _render_table(self, rows: list[BuildTrackerRecord]) -> None:
        self.table.setRowCount(0)
        self.result_info.setText(f"Toplam {len(rows)} güncelleme bulundu")
        for record in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                record.kb_number or "—",
                f"Windows 11 {record.windows_version or ''}".strip(),
                record.build_number,
                _display_date(record.release_date),
                _kind_text(record),
                record.channel or "—",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record)
                if col == 0:
                    item.setFont(self.table.font())
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 50)

        if rows:
            self.table.selectRow(0)
            self._select_record(rows[0])
        else:
            self._select_record(None)

    def _table_clicked(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        record = item.data(Qt.UserRole) if item else None
        if isinstance(record, BuildTrackerRecord):
            self._select_record(record)

    def _record_for_row(self, row: int) -> BuildTrackerRecord | None:
        if row < 0 or row >= self.table.rowCount():
            return None
        record_item = self.table.item(row, 0)
        record = record_item.data(Qt.UserRole) if record_item else None
        return record if isinstance(record, BuildTrackerRecord) else None

    def _copy_kb_from_row(self, row: int) -> None:
        record = self._record_for_row(row)
        if record is None:
            return
        value = (record.kb_number or "").strip()
        if value and value != "—":
            QApplication.clipboard().setText(value)

    def _copy_build_from_row(self, row: int) -> None:
        record = self._record_for_row(row)
        if record is None:
            return
        value = (record.build_number or "").strip()
        if value and value != "—":
            QApplication.clipboard().setText(value)

    def _select_record(self, record: BuildTrackerRecord | None) -> None:
        self.selected_record = record
        if record is None:
            self.detail_title.setText("Bir güncelleme seçin")
            self.detail_badge.setText("")
            for label in self.detail_labels.values():
                label.setText("—")
            self.detail_description.setText("Seçilen build kaydının açıklaması burada gösterilir.")
            self.article_link.setEnabled(False)
            self.package_button.setEnabled(False)
            return

        self.detail_title.setText(record.kb_number or f"Build {record.build_number}")
        self.detail_badge.setText(_kind_text(record))
        self.detail_badge.setProperty("kind", _kind_key(record))
        self.detail_badge.style().unpolish(self.detail_badge)
        self.detail_badge.style().polish(self.detail_badge)
        self.detail_labels["version"].setText(f"Windows 11 {record.windows_version or '—'}")
        self.detail_labels["build"].setText(record.build_number or "—")
        self.detail_labels["date"].setText(_display_date(record.release_date))
        self.detail_labels["channel"].setText(record.channel or "—")
        self.detail_labels["group"].setText(record.release_group or "—")
        self.detail_labels["kb"].setText(record.kb_number or "—")
        self.detail_description.setText(record.description or "Bu build için açıklama bilgisi bulunmuyor.")
        self.article_link.setEnabled(bool(record.article_url))
        self.package_button.setEnabled(bool(record.microsoft_url))

    def _open_article(self) -> None:
        record = self.selected_record
        if not record or not record.article_url:
            show_information(self, "Windows Build Tracker", "Bu kayıt için ilgili yazı bağlantısı bulunmuyor.")
            return
        QDesktopServices.openUrl(QUrl(record.article_url))

    def _open_microsoft(self) -> None:
        record = self.selected_record
        if not record or not record.microsoft_url:
            show_information(self, "Windows Build Tracker", "Bu kayıt için Microsoft kaynak bağlantısı bulunmuyor.")
            return
        QDesktopServices.openUrl(QUrl(record.microsoft_url))

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QLabel#pageTitle { font-size: 26px; font-weight: 700; color: #10213D; }
            QLabel#pageSubtitle, QLabel#freshnessInfo, QLabel#sectionHint, QLabel#resultInfo {
                color: #6C7C93; font-size: 12px;
            }
            QLabel#sectionTitle, QLabel#panelTitle { font-weight: 700; color: #13243B; font-size: 14px; }
            QFrame#latestPanel, QFrame#filterPanel, QFrame#listPanel, QFrame#detailsPanel {
                background: #FFFFFF; border: 1px solid #DCE5F0; border-radius: 10px;
            }
            QFrame#newUpdateCard {
                background: #FFFFFF; border: 1px solid #DCE5F0; border-radius: 9px;
            }
            QFrame#newUpdateCard:hover { border-color: #77A7EE; background: #F8FBFF; }
            QLabel#windowsTileIcon { background: #EAF3FF; color: #2167D5; border-radius: 8px; font-size: 22px; font-weight: 700; }
            QLabel#newUpdateTitle { color: #10213D; font-weight: 700; font-size: 14px; }
            QLabel#newUpdateMeta { color: #53657D; font-size: 11px; }
            QLabel#newUpdateDate { color: #7E8EA3; font-size: 10px; }
            QLabel#updateKindBadge { padding: 4px 8px; border-radius: 7px; font-size: 10px; font-weight: 700; }
            QLabel#updateKindBadge[kind="security"] { background: #E8F7EF; color: #26834A; }
            QLabel#updateKindBadge[kind="preview"] { background: #FFF1DC; color: #C87A12; }
            QLabel#updateKindBadge[kind="insider"] { background: #EDE8FF; color: #6744C6; }
            QLabel#updateKindBadge[kind="neutral"] { background: #EDF2F8; color: #53657D; }
            QLabel#filterLabel { color: #53657D; font-size: 11px; font-weight: 600; margin-top: 4px; }
            QLineEdit#filterSearch {
                background: #F8FAFD; border: 1px solid #D7E1ED; border-radius: 7px; padding: 8px 10px;
            }
            QLineEdit#filterSearch:focus { border: 1px solid #2167D5; }
            QCheckBox { color: #34465D; spacing: 7px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QPushButton#primaryButton {
                background: #2167D5; color: white; border: none; border-radius: 7px; padding: 9px 15px; font-weight: 600;
            }
            QPushButton#primaryButton:hover { background: #1C59BA; }
            QPushButton#secondaryButton {
                background: #FFFFFF; color: #1C4F98; border: 1px solid #CAD8EA; border-radius: 7px; padding: 9px 15px; font-weight: 600;
            }
            QPushButton#secondaryButton:hover { background: #F4F8FD; border-color: #8CB0E5; }
            QPushButton#textButton { background: transparent; border: none; color: #2167D5; font-size: 11px; }
            QTableWidget#buildTable {
                background: #FFFFFF; border: none; gridline-color: transparent; outline: none;
                selection-background-color: #EAF3FF; selection-color: #10213D;
            }
            QTableWidget#buildTable::item { border-bottom: 1px solid #EDF1F6; padding: 7px; }
            QHeaderView::section {
                background: #F7F9FC; color: #53657D; border: none; border-bottom: 1px solid #DCE5F0;
                padding: 8px; font-size: 11px; font-weight: 700;
            }
            QLabel#detailTitle { color: #10213D; font-size: 20px; font-weight: 700; }
            QLabel#detailKey { color: #6C7C93; font-size: 11px; }
            QLabel#detailValue { color: #243750; font-size: 11px; font-weight: 600; }
            QLabel#detailDescription { color: #53657D; line-height: 1.4; }
            QFrame#softSeparator { background: #E5EBF2; color: #E5EBF2; max-height: 1px; border: none; }
            QLabel#infoNote { background: #F2F7FF; color: #55708E; border: 1px solid #D7E5F7; border-radius: 8px; padding: 10px; font-size: 10px; }
            """
        )
