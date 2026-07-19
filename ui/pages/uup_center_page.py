from datetime import datetime
from pathlib import Path
import re
import webbrowser

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
)

from ui.widgets.message_dialog import show_message
from ui.widgets.modern_combo_box import ModernComboBox
from workers.uup_search_worker import UupSearchWorker
from workers.uup_prepare_worker import UupPrepareWorker
from services.download_manager import DownloadManager
from services.system_profile import SystemProfileService
from services.settings_service import SettingsService


class UupCenterPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_build = ""
        self.current_title = ""
        self.current_channel = ""
        self.current_source = ""
        self._thread = None
        self._worker = None
        self._results = []
        self._prepare_thread = None
        self._prepare_worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(16)

        subtitle = QLabel(
            "KB numarası bulunmayan Insider build'leri için "
            "UUP seçeneklerini arayın ve uygun build kaydını doğrulayın."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("searchCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(8)

        self.build_label = QLabel("Build: —")
        self.build_label.setObjectName("detailName")
        self.title_label = QLabel("Kayıt: —")
        self.title_label.setObjectName("detailMeta")
        self.title_label.setWordWrap(True)
        self.channel_label = QLabel("Kanal: —")
        self.channel_label.setObjectName("detailMeta")
        self.source_label = QLabel("Kaynak: —")
        self.source_label.setObjectName("detailMeta")

        card_layout.addWidget(self.build_label)
        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.channel_label)
        card_layout.addWidget(self.source_label)
        layout.addWidget(card)

        options = QFrame()
        options.setObjectName("searchCard")
        options_layout = QHBoxLayout(options)
        options_layout.setContentsMargins(16, 14, 16, 14)
        options_layout.setSpacing(10)

        self.system_profile = SystemProfileService.current()

        self.arch_combo = ModernComboBox()
        self.arch_combo.addItems(["Mimari: x64", "Mimari: ARM64", "Mimari: x86"])
        preferred_arch_index = self.arch_combo.findText(
            f"Mimari: {self.system_profile.architecture}"
        )
        if preferred_arch_index >= 0:
            self.arch_combo.setCurrentIndex(preferred_arch_index)
        self.arch_combo.setToolTip(
            f"Windows sistem mimarisi otomatik seçildi: {self.system_profile.architecture}. "
            "Farklı bir mimari indirmek için listeden değiştirebilirsiniz."
        )

        self.language_combo = ModernComboBox()
        self.language_combo.addItems(
            [f"Dil: {name}" for name in SystemProfileService.language_options()]
        )
        preferred_language_index = self.language_combo.findText(
            f"Dil: {self.system_profile.language_name}"
        )
        if preferred_language_index >= 0:
            self.language_combo.setCurrentIndex(preferred_language_index)
        self.language_combo.setToolTip(
            f"Windows arayüz dili otomatik seçildi: {self.system_profile.language_name}. "
            "Farklı bir dil indirmek için listeden değiştirebilirsiniz."
        )

        self.edition_combo = ModernComboBox()
        self.edition_combo.addItems([
            "Edition: Windows 11",
            "Edition: Windows 11 Pro",
        ])
        self.apply_settings(SettingsService.load())

        options_layout.addWidget(self.arch_combo)
        options_layout.addWidget(self.language_combo)
        options_layout.addWidget(self.edition_combo)
        layout.addWidget(options)

        self.detected_profile_label = QLabel(
            f"Sistem varsayılanları: {self.system_profile.architecture} • "
            f"{self.system_profile.language_name}. İsterseniz yukarıdaki menülerden değiştirebilirsiniz."
        )
        self.detected_profile_label.setObjectName("subtleInfoBox")
        self.detected_profile_label.setWordWrap(True)
        layout.addWidget(self.detected_profile_label)

        self.status = QLabel(
            "Bir Insider build seçildiğinde bilgiler burada gösterilecek."
        )
        self.status.setObjectName("infoBox")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        button_row = QHBoxLayout()

        self.find_button = QPushButton(
            "UUP / ISO Seçeneklerini Bul"
        )
        self.find_button.setEnabled(False)
        self.find_button.clicked.connect(
            self.start_search
        )

        self.stop_button = QPushButton("Aramayı Durdur")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(
            self.stop_search
        )

        button_row.addWidget(self.find_button, 1)
        button_row.addWidget(self.stop_button)
        layout.addLayout(button_row)

        self.result_table = QTableWidget(0, 9)
        self.result_table.setHorizontalHeaderLabels([
            "Build",
            "Mimari",
            "Başlık",
            "Dil",
            "Edition",
            "Dosya",
            "Toplam Boyut",
            "Tarih",
            "Kaynak",
        ])
        self.result_table.setSelectionBehavior(
            QTableWidget.SelectRows
        )
        self.result_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionMode(QTableWidget.SingleSelection)
        self.result_table.setShowGrid(False)
        self.result_table.setFocusPolicy(Qt.NoFocus)
        self.result_table.verticalHeader().setVisible(False)

        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(
            2,
            QHeaderView.Stretch,
        )
        for column in [0, 1, 3, 4, 5, 6, 7, 8]:
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeToContents,
            )

        layout.addWidget(self.result_table, 1)

        action_row = QHBoxLayout()

        self.open_button = QPushButton(
            "UUP Sayfasını Aç"
        )
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(
            self.open_selected_result
        )

        self.prepare_button = QPushButton(
            "UUP Dosyalarını İndir"
        )
        self.prepare_button.setEnabled(False)
        self.prepare_button.clicked.connect(
            self.prepare_selected_result
        )

        self.download_manager_button = QPushButton(
            "İndirme Yöneticisini Aç"
        )
        self.download_manager_button.setEnabled(False)
        self.download_manager_button.clicked.connect(
            self._open_download_manager
        )

        action_row.addWidget(self.open_button)
        action_row.addWidget(self.prepare_button)
        action_row.addWidget(self.download_manager_button)
        layout.addLayout(action_row)

        self.result_table.itemSelectionChanged.connect(
            self._on_selection_changed
        )

    @staticmethod
    def _format_size(size_bytes):
        if not size_bytes:
            return "—"
        if size_bytes >= 1024 ** 3:
            return f"{size_bytes / 1024 ** 3:.2f} GB"
        if size_bytes >= 1024 ** 2:
            return f"{size_bytes / 1024 ** 2:.1f} MB"
        return f"{size_bytes / 1024:.1f} KB"

    @staticmethod
    def _format_date(timestamp):
        if not timestamp:
            return "—"
        try:
            return datetime.fromtimestamp(
                timestamp
            ).strftime("%d.%m.%Y")
        except Exception:
            return "—"

    def set_build_context(
        self,
        build,
        title,
        channel="",
        source="",
    ):
        self.current_build = build or ""
        self.current_title = title or ""
        self.current_channel = channel or ""
        self.current_source = source or ""

        self.build_label.setText(
            f"Build: {self.current_build or '—'}"
        )
        self.title_label.setText(
            f"Kayıt: {self.current_title or '—'}"
        )
        self.channel_label.setText(
            f"Kanal: {self.current_channel or '—'}"
        )
        self.source_label.setText(
            f"Kaynak: {self.current_source or 'Microsoft'}"
        )

        self.find_button.setEnabled(
            bool(self.current_build)
        )
        self.result_table.setRowCount(0)
        self._results = []
        self.open_button.setEnabled(False)
        self.prepare_button.setEnabled(False)
        self.download_manager_button.setEnabled(False)

        self.status.setText(
            "Build bilgisi hazır. Mimari, dil ve edition "
            "seçip UUP aramasını başlatabilirsiniz."
        )

    def apply_settings(self, settings) -> None:
        prefs = dict((settings or {}).get("uup_iso", {}))
        arch = prefs.get("default_architecture", "Sistem varsayılanı")
        if arch == "Sistem varsayılanı":
            arch = self.system_profile.architecture
        language = prefs.get("default_language", "Sistem varsayılanı")
        if language == "Sistem varsayılanı":
            language = self.system_profile.language_name
        edition = prefs.get("default_edition", "Windows 11 Pro")
        for combo, text in (
            (self.arch_combo, f"Mimari: {arch}"),
            (self.language_combo, f"Dil: {language}"),
            (self.edition_combo, f"Edition: {edition}"),
        ):
            index = combo.findText(text)
            if index >= 0:
                combo.setCurrentIndex(index)

    def _combo_value(self, text: str) -> str:
        return text.split(": ", 1)[1] if ": " in text else text

    def start_search(self):
        if not self.current_build:
            return

        if self._thread and self._thread.isRunning():
            return

        self.result_table.setRowCount(0)
        self._results = []
        self.find_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.prepare_button.setEnabled(False)

        self.status.setText(
            f"{self.current_build} için UUP kayıtları aranıyor..."
        )

        self._thread = QThread(self)
        self._worker = UupSearchWorker(
            self.current_build,
            self._combo_value(self.arch_combo.currentText()),
            self._combo_value(self.language_combo.currentText()),
            self._combo_value(self.edition_combo.currentText()),
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(
            self._worker.run
        )
        self._worker.finished.connect(
            self._on_search_finished
        )
        self._worker.failed.connect(
            self._on_search_failed
        )
        self._worker.finished.connect(
            self._thread.quit
        )
        self._worker.failed.connect(
            self._thread.quit
        )
        self._thread.finished.connect(
            self._cleanup_thread
        )

        self._thread.start()

    def stop_search(self):
        if self._thread and self._thread.isRunning():
            self._thread.requestInterruption()
            self._thread.quit()

        self.find_button.setEnabled(
            bool(self.current_build)
        )
        self.stop_button.setEnabled(False)
        self.status.setText(
            "UUP araması kullanıcı tarafından durduruldu."
        )

    def _on_search_finished(self, results):
        self.find_button.setEnabled(
            bool(self.current_build)
        )
        self.stop_button.setEnabled(False)

        if self._thread and self._thread.isInterruptionRequested():
            return

        self._results = list(results)
        self.result_table.setRowCount(
            len(self._results)
        )

        for row, result in enumerate(self._results):
            language_text = (
                result.language_code
                if result.language_available
                else "Yok"
            )
            edition_text = (
                result.edition_name
                if result.edition_available
                else "Yok"
            )

            values = [
                result.build,
                result.architecture,
                result.title,
                language_text,
                edition_text,
                str(result.file_count or "—"),
                self._format_size(result.total_size),
                self._format_date(result.created),
                "UUP dump API",
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column != 2:
                    item.setTextAlignment(Qt.AlignCenter)
                self.result_table.setItem(
                    row,
                    column,
                    item,
                )

        if not self._results:
            self.status.setText(
                "Seçilen build ve mimari için UUP kaydı bulunamadı."
            )
            return

        valid_count = sum(
            1
            for result in self._results
            if (
                result.language_available
                and result.edition_available
            )
        )

        self.status.setText(
            f"{len(self._results)} UUP kaydı bulundu. "
            f"{valid_count} kayıt seçilen dil ve edition ile uyumlu."
        )

        self.result_table.selectRow(0)

    def _on_search_failed(self, message):
        self.find_button.setEnabled(
            bool(self.current_build)
        )
        self.stop_button.setEnabled(False)
        self.status.setText(
            "UUP araması tamamlanamadı."
        )

        show_message(
            self,
            "UUP Arama Hatası",
            "UUP kayıtları alınamadı",
            message,
        )

    def _cleanup_thread(self):
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()

        self._worker = None
        self._thread = None

    def _selected_result(self):
        rows = (
            self.result_table
            .selectionModel()
            .selectedRows()
        )
        if not rows:
            return None

        row = rows[0].row()
        if row < 0 or row >= len(self._results):
            return None

        return self._results[row]

    def _on_selection_changed(self):
        result = self._selected_result()
        self.open_button.setEnabled(
            result is not None
        )
        self.prepare_button.setEnabled(
            bool(
                result
                and result.language_available
                and result.edition_available
            )
        )

    def open_selected_result(self):
        result = self._selected_result()
        if result and result.source_url:
            webbrowser.open(
                result.source_url
            )

    def prepare_selected_result(self):
        result = self._selected_result()
        if result is None:
            return

        if not (
            result.language_available
            and result.edition_available
        ):
            show_message(
                self,
                "UUP İndirme",
                "Seçilen seçenek kullanılamıyor",
                "Bu build için seçtiğiniz dil veya edition bulunamadı.",
            )
            return

        if self._prepare_thread and self._prepare_thread.isRunning():
            return

        self.prepare_button.setEnabled(False)
        self.find_button.setEnabled(False)
        self.status.setText(
            "Microsoft UUP dosya bağlantıları hazırlanıyor..."
        )

        self._prepare_thread = QThread(self)
        self._prepare_worker = UupPrepareWorker(
            result.uuid,
            result.language_code,
            result.edition_code,
            result.architecture,
        )
        self._prepare_worker.moveToThread(self._prepare_thread)
        self._prepare_thread.started.connect(self._prepare_worker.run)
        self._prepare_worker.finished.connect(self._on_uup_packages_ready)
        self._prepare_worker.failed.connect(self._on_uup_prepare_failed)
        self._prepare_worker.finished.connect(self._prepare_thread.quit)
        self._prepare_worker.failed.connect(self._prepare_thread.quit)
        self._prepare_thread.finished.connect(self._cleanup_prepare_thread)
        self._prepare_thread.start()

    @staticmethod
    def _safe_folder_name(value: str) -> str:
        value = re.sub(r'[<>:"/\|?*]+', '_', value)
        value = re.sub(r'\s+', '_', value.strip())
        return value[:120] or "UUP_Download"

    @staticmethod
    def _unique_project_dir(base_folder: str, folder_name: str) -> Path:
        base_path = Path(base_folder)
        candidate = base_path / folder_name
        if not candidate.exists():
            return candidate

        suffix = 2
        while True:
            candidate = base_path / f"{folder_name}_{suffix}"
            if not candidate.exists():
                return candidate
            suffix += 1

    def _on_uup_packages_ready(self, packages):
        result = self._selected_result()
        if result is None:
            self.status.setText("Seçili UUP kaydı artık mevcut değil.")
            self.find_button.setEnabled(bool(self.current_build))
            return

        if not packages:
            self.status.setText("UUP dosya bağlantısı bulunamadı.")
            self.prepare_button.setEnabled(True)
            self.find_button.setEnabled(bool(self.current_build))
            return

        batch_meta = {
            "build": result.build,
            "architecture": result.architecture,
            "language": result.language_code,
            "edition": result.edition_code,
            "title": result.title,
            "auto_create_iso": True,
        }

        manager = DownloadManager.instance()

        settings = SettingsService.load()
        configured_folder = str(settings.get("downloads", {}).get("default_folder", "") or "").strip()
        initial_folder = configured_folder if configured_folder and Path(configured_folder).exists() else str(Path.home() / "Downloads")
        base_folder = QFileDialog.getExistingDirectory(
            self,
            "UUP Dosyalarının Kaydedileceği Klasörü Seç",
            initial_folder,
        )
        if not base_folder:
            self.status.setText("UUP indirme işlemi iptal edildi.")
            self.prepare_button.setEnabled(True)
            self.find_button.setEnabled(bool(self.current_build))
            return

        folder_name = self._safe_folder_name(
            f"Windows_{result.build}_{result.architecture}_{result.language_code}_{result.edition_code}"
        )
        project_dir = self._unique_project_dir(base_folder, folder_name)
        target_dir = project_dir / "UUPs"
        target_dir.mkdir(parents=True, exist_ok=True)

        items = []
        for package in packages:
            target_path = target_dir / package.filename
            items.append((package, str(target_path)))

        batch_meta.update({
            "project_dir": str(project_dir),
            "uup_dir": str(target_dir),
        })

        job_ids = manager.add_downloads(
            items,
            batch_meta=batch_meta,
            batch_kind="uup_iso",
            open_manager=False,
        )

        if not job_ids:
            show_message(
                self,
                "İndirme Başlatılamadı",
                "UUP dosyaları indirme kuyruğuna eklenemedi",
                "Lütfen yeniden deneyin veya farklı bir kayıt klasörü seçin.",
            )
            self.status.setText("UUP dosyaları indirme kuyruğuna eklenemedi.")
        else:
            self.download_manager_button.setEnabled(True)
            self.status.setText(
                f"{len(job_ids)} UUP dosyası indirme kuyruğuna eklendi. "
                f"Yeni indirme klasörü: {project_dir.name}. "
                "Aynı build ve sürüm tekrar indirilebilir. "
                "UUP / ISO Merkezi açık kalacak. İndirme durumunu görmek için "
                "İndirme Yöneticisini Aç düğmesini kullanabilirsiniz. "
                "İndirme tamamlandığında ISO otomatik olarak oluşturulacak."
            )
        self.prepare_button.setEnabled(True)
        self.find_button.setEnabled(bool(self.current_build))

    def _on_uup_prepare_failed(self, message):
        self.status.setText("UUP indirme bağlantıları alınamadı.")
        self.prepare_button.setEnabled(True)
        self.find_button.setEnabled(bool(self.current_build))
        show_message(
            self,
            "UUP İndirme Hatası",
            "Microsoft UUP bağlantıları hazırlanamadı",
            message,
        )

    def _open_download_manager(self):
        window = self.window()
        if hasattr(window, "show_page_by_name"):
            window.show_page_by_name("İndirme Yöneticisi")

    def _cleanup_prepare_thread(self):
        if self._prepare_worker is not None:
            self._prepare_worker.deleteLater()
        if self._prepare_thread is not None:
            self._prepare_thread.deleteLater()
        self._prepare_worker = None
        self._prepare_thread = None
