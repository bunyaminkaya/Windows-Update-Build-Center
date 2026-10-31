from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFrame, QSizePolicy, QMenu, QAbstractItemView, QTextEdit, QDialog,
    QGridLayout, QFileDialog, QStackedWidget
)

from ui import icons, styles
from ui.theme import raw_qcolor

from services.download_manager import DownloadManager
from services.iso_build_manager import IsoBuildManager
from ui.widgets.iso_build_panel import IsoBuildPanel
from ui.widgets.modern_combo_box import ModernComboBox
from ui.widgets.message_dialog import show_information, show_warning, show_error, ask_confirmation, ask_choice, DialogAction


def format_bytes(value: int) -> str:
    if value <= 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "—"


def format_speed(value: float) -> str:
    return "—" if value <= 0 else f"{format_bytes(int(value))}/sn"


def format_eta(seconds: float) -> str:
    if seconds < 0:
        return "—"
    # Yuvarlama kaynaklı 29 sn -> 1 dk gibi görsel sıçramaları azaltmak için
    # en yakın saniyeyi kullanıyoruz. Hız tarafındaki EMA zaten ana stabilizasyonu sağlar.
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours} sa {minutes:02d} dk {sec:02d} sn"
    if minutes:
        return f"{minutes} dk {sec:02d} sn"
    return f"{sec} sn"


class IsoProgressDialog(QDialog):
    """Non-modal ISO conversion progress window.

    Closing the window only hides the progress UI; the ISO conversion continues
    in the background. The same dialog instance can be reopened from the
    Download Manager at any time.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ISO Oluşturma İlerlemesi")
        self.setObjectName("isoProgressDialog")
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1080, 620)
        self.setMinimumSize(920, 520)

        self.setStyleSheet(styles.qss("""
            QDialog#isoProgressDialog {
                background: #F4F7FB;
                color: #14213D;
            }
            QFrame#isoMainCard {
                background: #FFFFFF;
                border: 1px solid #DCE5F0;
                border-radius: 14px;
            }
            QPushButton {
                min-height: 38px;
                padding: 0 18px;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#primaryButton {
                background: @BLUE@;
                color: #FFFFFF;
                border: 1px solid @BLUE@;
            }
            QPushButton#primaryButton:hover {
                background: #1859C0;
                border-color: #1859C0;
            }
            QPushButton#secondaryButton {
                background: #FFFFFF;
                color: @BLUE@;
                border: 1px solid #BFD0E6;
            }
            QPushButton#secondaryButton:hover {
                background: #F0F6FF;
                border-color: #8EB2E7;
            }
            QPushButton#dangerButton {
                background: #FFFFFF;
                color: #D23B3B;
                border: 1px solid #F0A7A7;
            }
            QPushButton#dangerButton:hover {
                background: #FFF2F2;
                border-color: #E56A6A;
            }
            QPushButton:disabled {
                background: #E2E7EF;
                color: #94A0B2;
                border: 1px solid #D7DEE8;
            }
            QLabel#isoCurrentStatus {
                color: #17365D;
                font-size: 13px;
                font-weight: 600;
                background: #F6F9FE;
                border: 1px solid #D9E6F7;
                border-radius: 8px;
                padding: 10px 12px;
            }
            QLabel#isoInfoLabel {
                color: #60738E;
                font-size: 12px;
                background: transparent;
            }
            QLabel#isoStagePending {
                color: #728199;
                background: #F4F7FB;
                border: 1px solid #DCE5F0;
                border-radius: 9px;
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#isoStageActive {
                color: #FFFFFF;
                background: @BLUE@;
                border: 1px solid @BLUE@;
                border-radius: 9px;
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#isoStageDone {
                color: #176B3A;
                background: #EAF7EF;
                border: 1px solid #BDE3CA;
                border-radius: 9px;
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QProgressBar#isoBuildProgress {
                background: #E7EEF7;
                border: 1px solid #D2DEEC;
                border-radius: 10px;
                text-align: center;
                color: #17365D;
                font-weight: 700;
                min-height: 26px;
            }
            QProgressBar#isoBuildProgress::chunk {
                background: @BLUE@;
                border-radius: 9px;
            }
            QTextEdit#isoLogView {
                background: #111827;
                color: #E5EEF9;
                border: 1px solid #2A3A52;
                border-radius: 9px;
                padding: 10px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
                selection-background-color: @BLUE@;
            }
            QLabel#statNote {
                color: #7D8A9E;
                font-size: 11px;
                background: transparent;
            }
        """))

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(18, 18, 18, 18)
        outer_layout.setSpacing(0)

        main_card = QFrame()
        main_card.setObjectName("isoMainCard")
        outer_layout.addWidget(main_card)

        layout = QVBoxLayout(main_card)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        header_text = QVBoxLayout()
        header_text.setSpacing(3)
        title = QLabel("Otomatik ISO Oluşturma")
        title.setObjectName("pageTitle")
        self.meta = QLabel(
            "UUP indirmeleri tamamlandığında boot edilebilir ISO otomatik olarak oluşturulur."
        )
        self.meta.setObjectName("pageSubtitle")
        self.meta.setWordWrap(True)
        header_text.addWidget(title)
        header_text.addWidget(self.meta)
        header.addLayout(header_text, 1)

        self.details_button = QPushButton("Ayrıntıları Göster")
        self.details_button.setObjectName("secondaryButton")
        self.stop_button = QPushButton("İşlemi Durdur")
        self.stop_button.setObjectName("dangerButton")
        self.retry_button = QPushButton("Yeniden Dene")
        self.retry_button.setObjectName("secondaryButton")
        self.retry_button.setEnabled(False)
        self.change_work_button = QPushButton("Çalışma Konumu Seç")
        self.change_work_button.setObjectName("secondaryButton")
        self.change_work_button.setVisible(False)
        self.open_iso_button = QPushButton("ISO Klasörünü Aç")
        self.open_iso_button.setObjectName("primaryButton")
        self.open_iso_button.setEnabled(False)
        header.addWidget(self.details_button)
        header.addWidget(self.stop_button)
        header.addWidget(self.retry_button)
        header.addWidget(self.change_work_button)
        header.addWidget(self.open_iso_button)
        layout.addLayout(header)

        self.stage_labels = []
        stage_row = QHBoxLayout()
        stage_row.setSpacing(8)
        for index, name in enumerate((
            "1. UUP Doğrulama",
            "2. ESD Hazırlama",
            "3. Windows İmajı",
            "4. Güncellemeler",
            "5. ISO Paketleme",
            "6. Doğrulama",
        )):
            label = QLabel(name)
            label.setObjectName("isoStagePending")
            label.setAlignment(Qt.AlignCenter)
            label.setProperty("stageIndex", index)
            label.setMinimumHeight(48)
            stage_row.addWidget(label, 1)
            self.stage_labels.append(label)
        layout.addLayout(stage_row)

        self.status = QLabel("Hazır")
        self.status.setObjectName("isoCurrentStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setObjectName("isoBuildProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p% — Hazır")
        self.progress.setMinimumHeight(34)
        layout.addWidget(self.progress)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(18)
        info_grid.setVerticalSpacing(6)
        self.elapsed_label = QLabel("Geçen süre: —")
        self.remaining_label = QLabel("Tahmini kalan: —")
        # Uyumluluk için nesne korunur ancak aynı bilgi üst durum alanında
        # zaten gösterildiğinden kullanıcı arayüzünde tekrar gösterilmez.
        self.operation_label = QLabel("")
        self.operation_label.setVisible(False)
        for label in (self.elapsed_label, self.remaining_label):
            label.setObjectName("isoInfoLabel")
        info_grid.addWidget(self.elapsed_label, 0, 0)
        info_grid.addWidget(self.remaining_label, 0, 1)
        layout.addLayout(info_grid)

        self.result_label = QLabel("")
        self.result_label.setObjectName("isoCurrentStatus")
        self.result_label.setWordWrap(True)
        self.result_label.setVisible(False)
        layout.addWidget(self.result_label)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("isoLogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(180)
        self.log_view.setVisible(False)
        layout.addWidget(self.log_view, 1)

        hint = QLabel(
            "Bu pencere kapatılsa bile ISO oluşturma işlemi arka planda devam eder. "
            "İndirme Yöneticisi'ndeki ‘ISO İşlemi’ düğmesiyle tekrar açabilirsiniz."
        )
        hint.setObjectName("statNote")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def closeEvent(self, event):
        # Hide instead of destroying so the live state remains available.
        self.hide()
        event.ignore()


class DownloadManagerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = DownloadManager.instance()
        self.iso_manager = IsoBuildManager.instance()
        self._latest_iso_path = ""
        self._latest_iso_work_dir = ""
        self._latest_iso_batch = ""
        self._row_for_job = {}
        self._stat_values = {}
        self._rebuild_scheduled = False
        self._pending_preferred_job_id = None
        self._current_filter = "all"
        self._last_status_group = {}
        self._iso_started_at = None
        self._iso_progress_value = 0
        self._iso_current_stage = -1
        self._iso_last_operation = "—"
        self._iso_log_lines = []

        self._iso_elapsed_timer = QTimer(self)
        self._iso_elapsed_timer.setInterval(1000)
        self._iso_elapsed_timer.timeout.connect(self._refresh_iso_time_labels)

        self.setObjectName("dmPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(14)

        # ── Başlık ──
        header_row = QHBoxLayout()
        header_row.setSpacing(14)
        head_icon = QLabel()
        head_icon.setPixmap(icons.pixmap("cloud-down", "#1768E0", 46, stroke=1.9))
        head_icon.setFixedSize(58, 58)
        head_icon.setAlignment(Qt.AlignCenter)
        header_row.addWidget(head_icon, 0, Qt.AlignTop)
        head_text = QVBoxLayout()
        head_text.setSpacing(2)
        page_title = QLabel("İndirme Yöneticisi")
        page_title.setObjectName("dmTitle")
        subtitle = QLabel(
            "Devam eden indirmeleri izleyin, kuyruğu duraklatın, sürdürün veya iptal edin."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        head_text.addWidget(page_title)
        head_text.addWidget(subtitle)
        header_row.addLayout(head_text, 1)
        self.refresh_button = QPushButton("Yenile")
        self.refresh_button.setObjectName("dmPrimary")
        self.refresh_button.setIcon(self._dm_icon("refresh", "#FFFFFF"))
        self.refresh_button.setIconSize(QSize(18, 18))
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.setToolTip("Listeyi yeniden çiz")
        self.refresh_button.clicked.connect(lambda: self._rebuild_table())
        header_row.addWidget(self.refresh_button, 0, Qt.AlignTop)
        layout.addLayout(header_row)

        # Mantık tarafı bu etiketi güncellemeye devam eder; görünümde gösterilmez.
        self.summary = QLabel("Henüz indirme yok.")
        self.summary.setObjectName("infoBox")
        self.summary.setVisible(False)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(14)
        self.total_value = self._build_stat_card(
            stats_row, "Toplam", "0", "Toplam indirme sayısı", "doc", "#1768E0", "#E3EEFC")
        self.active_value = self._build_stat_card(
            stats_row, "İndiriliyor", "0", "Aktif indirme sayısı", "download", "#1FA463", "#DFF5E9")
        self.waiting_value = self._build_stat_card(
            stats_row, "Kuyrukta", "0", "Bekleyen indirme sayısı", "clock", "#E8891B", "#FDEBD3")
        self.completed_value = self._build_stat_card(
            stats_row, "Tamamlandı", "0", "Tamamlanan indirme sayısı", "check-circle", "#1768E0", "#E3EEFC")
        layout.addLayout(stats_row)

        # ISO progress is shown in a separate non-modal window so the Download
        # Manager keeps its full vertical workspace.
        self.iso_dialog = IsoProgressDialog(self)
        self.iso_meta = self.iso_dialog.meta
        self.iso_details_button = self.iso_dialog.details_button
        self.open_iso_button = self.iso_dialog.open_iso_button
        self.iso_stop_button = self.iso_dialog.stop_button
        self.iso_retry_button = self.iso_dialog.retry_button
        self.iso_change_work_button = self.iso_dialog.change_work_button
        self.iso_result_label = self.iso_dialog.result_label
        self.iso_stage_labels = self.iso_dialog.stage_labels
        self.iso_status = self.iso_dialog.status
        self.iso_progress = self.iso_dialog.progress
        self.iso_elapsed_label = self.iso_dialog.elapsed_label
        self.iso_remaining_label = self.iso_dialog.remaining_label
        self.iso_operation_label = self.iso_dialog.operation_label
        self.iso_log_view = self.iso_dialog.log_view
        self.iso_details_button.clicked.connect(self._toggle_iso_details)
        self.open_iso_button.clicked.connect(self._open_iso_folder)
        self.iso_stop_button.clicked.connect(self._cancel_iso_build)
        self.iso_retry_button.clicked.connect(self._retry_iso_build)
        self.iso_change_work_button.clicked.connect(self._choose_iso_work_dir)

        # ── İndirme Kuyruğu kartı ──
        queue_card = QFrame()
        queue_card.setObjectName("dmCard")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(18, 16, 18, 16)
        queue_layout.setSpacing(12)

        queue_head = QHBoxLayout()
        queue_head.setSpacing(12)
        queue_head.addWidget(self._dm_tile("cloud-down", "#1768E0", "#E3EEFC"), 0, Qt.AlignTop)
        queue_head_text = QVBoxLayout()
        queue_head_text.setSpacing(1)
        queue_title = QLabel("İndirme Kuyruğu")
        queue_title.setObjectName("dmCardTitle")
        queue_note = QLabel("Microsoft paket indirmelerinizi buradan takip edebilir, işlemleri yönetebilirsiniz.")
        queue_note.setObjectName("dmCardDesc")
        queue_head_text.addWidget(queue_title)
        queue_head_text.addWidget(queue_note)
        queue_head.addLayout(queue_head_text, 1)
        queue_layout.addLayout(queue_head)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_buttons = {}
        for key, text_value in (
            ("all", "Tümü"),
            ("running", "İndiriliyor"),
            ("queued", "Kuyrukta"),
            ("completed", "Tamamlandı"),
            ("problem", "Sorunlu"),
        ):
            button = QPushButton(text_value)
            button.setCheckable(True)
            button.setObjectName("filterChip")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, k=key: self._set_filter(k))
            filter_row.addWidget(button)
            self.filter_buttons[key] = button
        self.filter_buttons["all"].setChecked(True)
        filter_row.addStretch(1)
        self.iso_popup_button = QPushButton("ISO İşlemi")
        self.iso_popup_button.setObjectName("dmPrimary")
        self.iso_popup_button.setIcon(self._dm_icon("cube", "#FFFFFF"))
        self.iso_popup_button.setIconSize(QSize(18, 18))
        self.iso_popup_button.setCursor(Qt.PointingHandCursor)
        self.iso_popup_button.setToolTip("ISO oluşturma ilerleme penceresini aç")
        self.iso_popup_button.clicked.connect(self._show_iso_dialog)
        filter_row.addWidget(self.iso_popup_button)
        queue_layout.addLayout(filter_row)

        self.table = QTableWidget(0, 9)
        self.table.setObjectName("dmTable")
        self.table.setHorizontalHeaderLabels([
            "Dosya", "Mimari", "Durum", "Sıra", "İlerleme", "İndirilen / Toplam",
            "Hız", "Kalan Süre", "Kayıt Yeri"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        # StrongFocus is required for reliable Ctrl/Shift multi-selection on Windows.
        # The visual focus rectangle is suppressed by the global stylesheet.
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(False)
        self.table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setFrameShape(QFrame.NoFrame)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 8):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        header.setFixedHeight(42)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # "Sıra" sütunu görselde yok; veri korunur, sadece gizlenir.
        self.table.setColumnHidden(3, True)

        # Boş durum (tablo yerine gösterilir)
        self.empty_state = QWidget()
        self.empty_state.setObjectName("dmEmpty")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(8)
        empty_circle = QLabel()
        empty_circle.setObjectName("dmEmptyCircle")
        empty_circle.setFixedSize(92, 92)
        empty_circle.setAlignment(Qt.AlignCenter)
        empty_circle.setPixmap(icons.pixmap("cloud-down", "#1768E0", 46, stroke=1.9))
        empty_layout.addWidget(empty_circle, 0, Qt.AlignHCenter)
        empty_layout.addSpacing(6)
        self.empty_title = QLabel("Henüz indirme yok")
        self.empty_title.setObjectName("dmEmptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_text = QLabel(
            "UUP ISO Oluşturucu veya Microsoft paket kaynaklarından bir indirme "
            "başlattığınızda burada görünecek."
        )
        self.empty_text.setObjectName("dmEmptyText")
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setWordWrap(True)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_text)

        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        self.table_stack.addWidget(self.empty_state)
        table_box = QFrame()
        table_box.setObjectName("dmTableBox")
        table_box_layout = QVBoxLayout(table_box)
        table_box_layout.setContentsMargins(0, 0, 0, 0)
        table_box_layout.addWidget(self.table_stack)
        table_box.setMinimumHeight(190)
        queue_layout.addWidget(table_box, 1)
        layout.addWidget(queue_card, 1)

        # ── İndirme İşlemleri kartı ──
        footer_card = QFrame()
        footer_card.setObjectName("dmCard")
        footer_layout = QVBoxLayout(footer_card)
        footer_layout.setContentsMargins(18, 16, 18, 16)
        footer_layout.setSpacing(10)

        footer_head = QHBoxLayout()
        footer_head.setSpacing(12)
        footer_head.addWidget(self._dm_tile("gear", "#1768E0", "#E3EEFC"), 0, Qt.AlignVCenter)
        footer_title = QLabel("İndirme İşlemleri")
        footer_title.setObjectName("dmCardTitle")
        footer_head.addWidget(footer_title)
        footer_head.addSpacing(10)

        strip = QFrame()
        strip.setObjectName("dmInfoStrip")
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(14, 0, 14, 0)
        strip_layout.setSpacing(10)
        strip_icon = QLabel()
        strip_icon.setPixmap(icons.pixmap("info-outline", "#1768E0", 20, stroke=1.9))
        strip_icon.setFixedSize(22, 22)
        strip_layout.addWidget(strip_icon)
        self.manager.job_schedule_changed.connect(self._sync_empty_state)
        self.global_queue_status = QLabel("İndirme kuyruğu çalışıyor.")
        self.global_queue_status.setObjectName("subtleInfoBox")
        if not self.manager.status_counts().get("total", 0):
            self.global_queue_status.setText("İndirme kuyruğu boş. Herhangi bir indirme başlatılmadı.")
        strip_layout.addWidget(self.global_queue_status, 1)
        strip.setFixedHeight(42)
        footer_head.addWidget(strip, 1)
        footer_layout.addLayout(footer_head)

        # Global queue controls live in the same action area as the per-file
        # controls. This keeps all IDM-style download actions in one place.
        bulk_caption = QLabel("Toplu İşlemler")
        bulk_caption.setObjectName("dmSection")
        footer_layout.addWidget(bulk_caption)

        queue_actions = QHBoxLayout()
        queue_actions.setSpacing(10)

        self.pause_all_button = QPushButton("Tümünü Duraklat")
        self.resume_all_button = QPushButton("Tümünü Devam Ettir")
        self.cancel_all_button = QPushButton("Tümünü İptal Et")
        self.cancel_all_button.setObjectName("dmDanger")
        self.pause_all_button.setIcon(self._dm_icon("pause", "#1768E0"))
        self.resume_all_button.setIcon(self._dm_icon("play", "#1768E0"))
        self.cancel_all_button.setIcon(self._dm_icon("x", "#D93C3C"))

        for button in (
            self.pause_all_button,
            self.resume_all_button,
            self.cancel_all_button,
        ):
            if button.objectName() != "dmDanger":
                button.setObjectName("dmAction")
            button.setIconSize(QSize(18, 18))
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(button.sizeHint().width() + 24)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            queue_actions.addWidget(button)

        queue_actions.addStretch(1)

        concurrent_label = QLabel("Aynı anda")
        concurrent_label.setObjectName("dmSection")
        queue_actions.addWidget(concurrent_label)

        self.concurrent_combo = ModernComboBox()
        self.concurrent_combo.setMinimumWidth(130)
        for value in range(1, 7):
            self.concurrent_combo.addItem(f"{value} indirme", value)
        current_index = max(
            0,
            min(self.manager.max_concurrent - 1, self.concurrent_combo.count() - 1),
        )
        self.concurrent_combo.setCurrentIndex(current_index)
        queue_actions.addWidget(self.concurrent_combo)
        footer_layout.addLayout(queue_actions)

        # Per-file actions remain directly below the global queue controls.
        selected_caption = QLabel("Seçili Dosya İşlemleri")
        selected_caption.setObjectName("dmSection")
        footer_layout.addWidget(selected_caption)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.pause_button = QPushButton("Duraklat")
        self.resume_button = QPushButton("Devam Ettir")
        self.cancel_button = QPushButton("İptal Et")
        self.retry_button = QPushButton("Yeniden Dene")
        self.delete_selected_button = QPushButton("Seçilenleri Sil")
        self.clear_completed_button = QPushButton("Tamamlananları Temizle")
        self.open_folder_button = QPushButton("Klasörü Aç")

        for button, icon_name, color, name in (
            (self.pause_button, "pause", "#1768E0", "dmAction"),
            (self.resume_button, "play", "#1768E0", "dmAction"),
            (self.cancel_button, "x", "#D93C3C", "dmDanger"),
            (self.retry_button, "undo", "#1768E0", "dmAction"),
            (self.delete_selected_button, "trash", "#D93C3C", "dmDanger"),
            (self.clear_completed_button, "check-circle", "#1768E0", "dmAction"),
            (self.open_folder_button, "folder", "#1768E0", "dmAction"),
        ):
            button.setObjectName(name)
            button.setIcon(self._dm_icon(icon_name, color))
            button.setIconSize(QSize(18, 18))
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(button.sizeHint().width() + 16)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            actions.addWidget(button, 1)
        footer_layout.addLayout(actions)
        layout.addWidget(footer_card)

        # ── ISO Oluşturma bölümü: indirme (kuyruk + işlemler) bittikten sonraki 2. aşama; iş yoksa gizli ──
        self.iso_panel = IsoBuildPanel(self, manager=self.manager, iso_manager=self.iso_manager)
        self.iso_panel.details_requested.connect(lambda _bid: self._show_iso_dialog())
        self.iso_panel.iso_center_requested.connect(self._open_iso_center)
        layout.addWidget(self.iso_panel)

        self.pause_button.clicked.connect(self._pause)
        self.resume_button.clicked.connect(self._resume)
        self.cancel_button.clicked.connect(self._cancel)
        self.retry_button.clicked.connect(self._retry)
        self.delete_selected_button.clicked.connect(self._delete_selected_files)
        self.clear_completed_button.clicked.connect(self._clear_completed_jobs)
        self.open_folder_button.clicked.connect(self._open_folder)

        self.pause_all_button.clicked.connect(self._pause_all)
        self.resume_all_button.clicked.connect(self._resume_all)
        self.cancel_all_button.clicked.connect(self._cancel_all)
        self.concurrent_combo.currentIndexChanged.connect(self._change_concurrency)

        # Progress signals can arrive many times per second for several active
        # downloads. Coalesce them into one UI refresh window instead of doing
        # expensive sorting/table work for every 1 MB network chunk.
        self._pending_job_updates: set[str] = set()
        self._ui_refresh_timer = QTimer(self)
        self._ui_refresh_timer.setSingleShot(True)
        self._ui_refresh_timer.setInterval(150)
        self._ui_refresh_timer.timeout.connect(self._flush_job_updates)

        self.manager.job_added.connect(self._ensure_job)
        self.manager.job_updated.connect(self._queue_job_refresh)
        self.iso_manager.build_started.connect(self._on_iso_started)
        self.iso_manager.status_changed.connect(self._on_iso_status)
        self.iso_manager.build_finished.connect(self._on_iso_finished)
        self.iso_manager.build_failed.connect(self._on_iso_failed)
        self.iso_manager.build_cancelled.connect(self._on_iso_cancelled)
        self.table.itemSelectionChanged.connect(self._update_action_states)

        # Görünüm: tablo boşken boş durum ekranını göster.
        model = self.table.model()
        model.rowsInserted.connect(self._sync_empty_state)
        model.rowsRemoved.connect(self._sync_empty_state)
        model.modelReset.connect(self._sync_empty_state)
        self._apply_dm_styles()

        self._rebuild_table()
        self._sync_empty_state()
        self._update_action_states()
        self._refresh_summary_only()
        self._update_global_action_states()

    def _open_iso_center(self, _batch_id: str = ""):
        window = self.window()
        if hasattr(window, "show_page_by_name"):
            window.show_page_by_name("ISO Merkezi")

    def _format_duration(self, seconds: float | int) -> str:
        seconds = max(0, int(seconds or 0))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours} sa {minutes:02d} dk"
        if minutes:
            return f"{minutes} dk {secs:02d} sn"
        return f"{secs} sn"

    def _classify_iso_progress(self, message: str) -> tuple[int, int, str]:
        text = (message or "").strip()
        low = text.lower()

        # Milestone ranges are intentionally broad. UUP Converter does not expose
        # one trustworthy end-to-end percentage, but DISM/wimlib sub-operations
        # sometimes do. When such a local percentage is present we interpolate it
        # inside the current stage rather than pretending it is the global percent.
        stage_ranges = (
            (3, 15),   # UUP validation / setup
            (15, 38),  # Reference ESD preparation
            (38, 62),  # Windows image creation
            (62, 82),  # Update integration / servicing
            (82, 96),  # ISO packaging
            (96, 99),  # Final verification
        )

        stage = max(self._iso_current_stage, 0)

        if any(key in low for key in (
            "checking uup info", "configured options", "running uup converter",
            "uup doğrul", "sırasına alındı", "araçları hazırlan",
            "gerekli araç indiriliyor", "converter çalışma klasörüne",
            "dönüştürme işlemi arka planda başlatılıyor"
        )):
            stage = 0
        elif any(key in low for key in (
            "preparing reference esd", "reference esd", "referans esd",
            "stubappsfull", "decrypting esd", "converting esd"
        )):
            stage = 1
        elif any(key in low for key in (
            "creating install.wim", "creating install.esd", "creating install",
            "install.wim", "install.esd", "creating boot.wim", "boot.wim",
            "creating setup media", "applying image", "exporting image",
            "capturing image", "windows image", "windows imaj", "wimlib-imagex"
        )):
            stage = 2
        elif any(key in low for key in (
            "adding updates", "integrating updates", "cumulative update", " lcu",
            "servicing", "package processing", "cleanup-image", "resetbase",
            "enable-feature", "netfx3", "applying package", "installing package"
        )):
            stage = 3
        elif any(key in low for key in (
            "creating iso", "create iso", "oscdimg", "cdimage", "iso image",
            "iso dosyası", "iso paket", "bootable iso", "mastering iso"
        )):
            stage = 4
        elif any(key in low for key in (
            "verifying iso", "checking iso", "sha256", "sha-256", "checksum",
            "iso created", "iso complete", "conversion complete"
        )):
            stage = 5

        start_value, end_value = stage_ranges[stage]
        progress = max(self._iso_progress_value, start_value)

        # Parse a real local tool percentage when one is available.
        match = re.search(r"(?<!\d)(100(?:\.0+)?|\d{1,2}(?:\.\d+)?)\s*%", text)
        if match:
            try:
                local = max(0.0, min(100.0, float(match.group(1))))
                progress = int(start_value + (end_value - start_value) * (local / 100.0))
            except Exception:
                pass

        return stage, progress, text

    def _set_iso_stage(self, stage_index: int):
        self._iso_current_stage = stage_index
        for index, label in enumerate(self.iso_stage_labels):
            if index < stage_index:
                object_name = "isoStageDone"
                prefix = "✓ "
            elif index == stage_index:
                object_name = "isoStageActive"
                prefix = "● "
            else:
                object_name = "isoStagePending"
                prefix = ""
            base = label.text().replace("✓ ", "").replace("● ", "")
            label.setText(prefix + base)
            if label.objectName() != object_name:
                label.setObjectName(object_name)
                label.style().unpolish(label)
                label.style().polish(label)
                label.update()

    def _append_iso_log(self, message: str):
        cleaned = (message or "").strip()
        if not cleaned:
            return
        if self._iso_log_lines and self._iso_log_lines[-1] == cleaned:
            return
        self._iso_log_lines.append(cleaned)
        self._iso_log_lines = self._iso_log_lines[-250:]
        self.iso_log_view.setPlainText("\n".join(self._iso_log_lines))
        cursor = self.iso_log_view.textCursor()
        cursor.movePosition(cursor.End)
        self.iso_log_view.setTextCursor(cursor)

    def _refresh_iso_time_labels(self):
        if not self._iso_started_at:
            return
        import time
        elapsed = max(0.0, time.monotonic() - self._iso_started_at)
        self.iso_elapsed_label.setText(f"Geçen süre: {self._format_duration(elapsed)}")
        progress = max(0, min(100, int(self._iso_progress_value)))
        if progress >= 8 and progress < 100:
            remaining = elapsed * (100 - progress) / max(progress, 1)
            # ISO conversion is non-linear, so present this explicitly as approximate.
            self.iso_remaining_label.setText(
                f"Tahmini kalan: yaklaşık {self._format_duration(remaining)}"
            )
        elif progress >= 100:
            self.iso_remaining_label.setText("Tahmini kalan: 0 sn")
        else:
            self.iso_remaining_label.setText("Tahmini kalan: hesaplanıyor...")

    def _on_iso_started(self, batch_id: str):
        import time
        self._latest_iso_batch = batch_id
        self._latest_iso_path = ""
        self._iso_started_at = time.monotonic()
        self._iso_progress_value = 3
        self._iso_current_stage = 0
        self._iso_last_operation = "ISO oluşturma sırasına alındı"
        self._iso_log_lines = []
        self.iso_log_view.clear()

        state = self.iso_manager.state(batch_id)
        metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
        self._latest_iso_work_dir = str(
            metadata.get("project_dir", "") or metadata.get("uup_dir", "") or ""
        )
        if self._latest_iso_work_dir and Path(self._latest_iso_work_dir).name.lower() == "uups":
            self._latest_iso_work_dir = str(Path(self._latest_iso_work_dir).parent)
        build = metadata.get("build", "—")
        arch = metadata.get("architecture", "—")
        lang = metadata.get("language", "—")
        edition = metadata.get("edition", "—")
        self.iso_meta.setText(
            f"Build {build} • {arch} • {lang} • {edition}"
        )
        self.iso_status.setText("UUP dosyaları doğrulanıyor ve ISO işlemi hazırlanıyor...")
        self.iso_progress.setRange(0, 100)
        self.iso_progress.setValue(self._iso_progress_value)
        self._update_iso_progress_text_color()
        self.iso_progress.setFormat("Aşama 1/6 — Hazırlanıyor")
        self.iso_elapsed_label.setText("Geçen süre: 0 sn")
        self.iso_remaining_label.setText("Tahmini kalan: hesaplanıyor...")
        self.iso_operation_label.setText("Son işlem: ISO oluşturma sırasına alındı")
        self._set_iso_stage(0)
        self._append_iso_log("ISO oluşturma işlemi başlatıldı.")
        self._iso_elapsed_timer.start()
        self.open_iso_button.setEnabled(bool(self._latest_iso_work_dir))
        self.open_iso_button.setText("Çalışma Klasörünü Aç")
        self.iso_stop_button.setEnabled(True)
        self.iso_retry_button.setEnabled(False)
        self.iso_change_work_button.setVisible(False)
        self.iso_result_label.clear()
        self.iso_result_label.setVisible(False)
        self.iso_popup_button.setText("ISO: Aşama 1/6")
        self._show_iso_dialog()

    def _on_iso_status(self, batch_id: str, message: str):
        if self._latest_iso_batch and batch_id != self._latest_iso_batch:
            return
        self._latest_iso_batch = batch_id
        stage, progress, operation = self._classify_iso_progress(message)
        # Never visually move backwards.
        self._iso_progress_value = max(self._iso_progress_value, progress)
        self._set_iso_stage(max(self._iso_current_stage, stage))
        self._iso_last_operation = operation or message
        self.iso_status.setText(operation or message)
        self.iso_progress.setRange(0, 100)
        self.iso_progress.setValue(self._iso_progress_value)
        self._update_iso_progress_text_color()
        stage_name = self.iso_stage_labels[self._iso_current_stage].text().replace("● ", "").replace("✓ ", "")
        # The numeric bar is an overall milestone estimate, not a fake exact
        # converter percentage. The text therefore emphasizes the live stage.
        self.iso_progress.setFormat(
            f"Aşama {self._iso_current_stage + 1}/6 — {stage_name} • çalışıyor"
        )
        self.iso_operation_label.setText(f"Son işlem: {self._iso_last_operation[-180:]}")
        self._append_iso_log(message)
        self._refresh_iso_time_labels()
        self.iso_popup_button.setText(f"ISO: Aşama {self._iso_current_stage + 1}/6")

    def _on_iso_finished(self, batch_id: str, iso_path: str, sha256: str):
        self._latest_iso_batch = batch_id
        self._latest_iso_path = iso_path
        self._iso_progress_value = 100
        self._set_iso_stage(5)
        # Mark final stage completed as well.
        for label in self.iso_stage_labels:
            base = label.text().replace("✓ ", "").replace("● ", "")
            label.setText("✓ " + base)
            label.setObjectName("isoStageDone")
            label.style().unpolish(label)
            label.style().polish(label)
        self.iso_status.setText(f"ISO başarıyla oluşturuldu: {Path(iso_path).name}")
        self.iso_progress.setRange(0, 100)
        self.iso_progress.setValue(100)
        self._update_iso_progress_text_color()
        self.iso_progress.setFormat("100% — ISO Hazır ✓")
        self.iso_operation_label.setText("Son işlem: ISO dosyası doğrulandı ve hazırlandı")
        self._append_iso_log(f"ISO hazır: {iso_path}")
        self._refresh_iso_time_labels()
        self._iso_elapsed_timer.stop()
        self.open_iso_button.setEnabled(True)
        self.open_iso_button.setText("ISO Klasörünü Aç")
        self.iso_stop_button.setEnabled(False)
        self.iso_retry_button.setEnabled(False)
        self.iso_change_work_button.setVisible(False)
        try:
            iso_size = format_bytes(Path(iso_path).stat().st_size)
        except Exception:
            iso_size = "—"
        self.iso_result_label.setText(
            f"✓ ISO Hazır\nDosya: {Path(iso_path).name}\nBoyut: {iso_size}\nSHA-256: {sha256 or '—'}"
        )
        self.iso_result_label.setVisible(True)
        self.iso_popup_button.setText("ISO Hazır ✓")
        self._show_iso_dialog()

    def _on_iso_failed(self, batch_id: str, message: str):
        self._latest_iso_batch = batch_id
        disk_space_error = str(message).startswith("YETERSIZ_DISK_ALANI|")
        if disk_space_error:
            parts = str(message).split("|", 4)
            try:
                required = int(parts[1])
                free = int(parts[2])
                location = parts[3]
            except Exception:
                required, free, location = 0, 0, self._latest_iso_work_dir
            self.iso_status.setText(
                f"Yetersiz disk alanı. Gerekli yaklaşık {format_bytes(required)}, "
                f"mevcut {format_bytes(free)}. Başka bir çalışma diski seçin."
            )
            self.iso_change_work_button.setVisible(True)
            self.iso_change_work_button.setEnabled(True)
            self.iso_result_label.setText(
                "ISO oluşturma, çalışma diskinde yeterli boş alan olmadığı için durduruldu. "
                "UUP dosyalarını yeniden indirmeden başka bir disk seçip işleme devam edebilirsiniz."
            )
        else:
            self.iso_status.setText("ISO oluşturulamadı. Ayrıntıları açarak hata günlüğünü inceleyebilirsiniz.")
            self.iso_change_work_button.setVisible(False)
        self.iso_progress.setRange(0, 100)
        self.iso_progress.setValue(self._iso_progress_value)
        self._update_iso_progress_text_color()
        self.iso_progress.setFormat("ISO Hatası")
        self.iso_operation_label.setText(f"Son işlem: Hata — {message[-180:]}")
        self._append_iso_log("HATA: " + message)
        self._refresh_iso_time_labels()
        self._iso_elapsed_timer.stop()
        work_available = bool(self._latest_iso_work_dir and Path(self._latest_iso_work_dir).exists())
        self.open_iso_button.setEnabled(work_available)
        self.open_iso_button.setText("Çalışma Klasörünü Aç")
        self.iso_stop_button.setEnabled(False)
        self.iso_retry_button.setEnabled(True)
        if not disk_space_error:
            self.iso_result_label.setText("ISO oluşturma başarısız. İşlem günlüğünü inceleyebilir veya Yeniden Dene seçeneğini kullanabilirsiniz.")
        self.iso_result_label.setVisible(True)
        self.iso_log_view.setVisible(True)
        self.iso_details_button.setText("Ayrıntıları Gizle")
        self.iso_popup_button.setText("ISO Hatası")
        self._show_iso_dialog()

    def _cancel_iso_build(self):
        if not self._latest_iso_batch:
            show_information(self, "ISO işlemi", "Durdurulabilecek aktif bir ISO görevi bulunmuyor.")
            return
        if self.iso_manager.cancel_build(self._latest_iso_batch):
            self.iso_status.setText("ISO oluşturma işlemi durduruluyor...")
            self.iso_stop_button.setEnabled(False)
        else:
            show_information(self, "ISO işlemi", "Bu ISO görevi şu anda çalışmıyor veya zaten tamamlanmış.")

    def _retry_iso_build(self):
        if not self._latest_iso_batch:
            show_information(self, "ISO işlemi", "Yeniden denenebilecek bir ISO görevi bulunmuyor.")
            return
        if self.iso_manager.retry_build(self._latest_iso_batch):
            self.iso_retry_button.setEnabled(False)
            self.iso_stop_button.setEnabled(True)
            self.iso_result_label.setVisible(False)
            self.iso_status.setText("ISO görevi yeniden sıraya alındı...")
            self._append_iso_log("Yeniden deneme isteği kabul edildi.")
        else:
            show_warning(self, "Yeniden deneme", "ISO görevi yeniden başlatılamadı. Görev bilgileri eksik olabilir.")

    def _choose_iso_work_dir(self):
        if not self._latest_iso_batch:
            show_information(self, "ISO çalışma konumu", "Aktif bir ISO görevi bulunmuyor.")
            return

        base_folder = QFileDialog.getExistingDirectory(
            self,
            "ISO çalışma diski veya klasörü seçin",
            str(Path.home()),
        )
        if not base_folder:
            return

        required = self.iso_manager.required_space(self._latest_iso_batch)
        try:
            import shutil
            free = int(shutil.disk_usage(base_folder).free)
        except Exception:
            free = 0
        if free and free < required:
            show_warning(
                self,
                "Yetersiz disk alanı",
                f"Seçilen konumda {format_bytes(free)} boş alan var. "
                f"Bu görev için yaklaşık {format_bytes(required)} boş alan öneriliyor.",
            )
            return

        state = self.iso_manager.state(self._latest_iso_batch)
        metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
        build = re.sub(r"[^A-Za-z0-9._-]+", "_", str(metadata.get("build", "Windows")))
        arch = re.sub(r"[^A-Za-z0-9._-]+", "_", str(metadata.get("architecture", "")))
        lang = re.sub(r"[^A-Za-z0-9._-]+", "_", str(metadata.get("language", "")))
        edition = re.sub(r"[^A-Za-z0-9._-]+", "_", str(metadata.get("edition", "")))
        base = Path(base_folder) / f"MDL_ISO_{build}_{arch}_{lang}_{edition}"
        target = base
        counter = 2
        while target.exists() and any(target.iterdir()):
            target = Path(f"{base}_{counter}")
            counter += 1
        target.mkdir(parents=True, exist_ok=True)

        self._latest_iso_work_dir = str(target)
        if self.iso_manager.change_work_dir_and_retry(self._latest_iso_batch, str(target)):
            self.iso_change_work_button.setVisible(False)
            self.iso_retry_button.setEnabled(False)
            self.iso_status.setText(f"Yeni çalışma konumu seçildi: {target}. ISO görevi yeniden başlatılıyor...")
            self._append_iso_log(f"Yeni ISO çalışma konumu: {target}")
        else:
            show_warning(self, "ISO çalışma konumu", "Yeni çalışma konumu kaydedilemedi.")

    def _on_iso_cancelled(self, batch_id: str, message: str):
        if self._latest_iso_batch and batch_id != self._latest_iso_batch:
            return
        self._latest_iso_batch = batch_id
        self._iso_elapsed_timer.stop()
        self.iso_status.setText("ISO oluşturma işlemi durduruldu.")
        self.iso_progress.setFormat("İşlem durduruldu")
        self.iso_operation_label.setText(f"Son işlem: {message}")
        self.iso_stop_button.setEnabled(False)
        self.iso_retry_button.setEnabled(True)
        self.iso_change_work_button.setVisible(False)
        work_available = bool(self._latest_iso_work_dir and Path(self._latest_iso_work_dir).exists())
        self.open_iso_button.setEnabled(work_available)
        self.open_iso_button.setText("Çalışma Klasörünü Aç")
        self.iso_result_label.setText("ISO görevi durduruldu. Hazır olduğunuzda Yeniden Dene ile kaldığınız akışı yeniden başlatabilirsiniz.")
        self.iso_result_label.setVisible(True)
        self.iso_popup_button.setText("ISO Durduruldu")
        self._append_iso_log("İPTAL: " + message)
        self._show_iso_dialog()

    def _show_iso_dialog(self):
        self.iso_dialog.show()
        self.iso_dialog.raise_()
        self.iso_dialog.activateWindow()

    def _toggle_iso_details(self):
        visible = not self.iso_log_view.isVisible()
        self.iso_log_view.setVisible(visible)
        self.iso_details_button.setText(
            "Ayrıntıları Gizle" if visible else "Ayrıntıları Göster"
        )

    def _update_iso_progress_text_color(self):
        """Keep progress text readable over the filled blue area."""
        try:
            value = int(self.iso_progress.value())
        except Exception:
            value = 0
        color = "#FFFFFF" if value >= 35 else "#17365D"
        self.iso_progress.setStyleSheet(f"QProgressBar#isoBuildProgress {{ color: {color}; }}")

    def _open_iso_folder(self):
        """Open the ISO output/work folder using multiple Windows-native fallbacks.

        When a finished ISO exists, Explorer opens the parent folder and selects the
        ISO file. During an active/failed build, the best available working folder
        is opened instead. The action never fails silently.
        """
        import os
        import subprocess

        iso_file = None
        candidates = []

        # 1) Prefer the exact ISO path reported by the build worker.
        if self._latest_iso_path:
            candidate_iso = Path(self._latest_iso_path).expanduser()
            try:
                candidate_iso = candidate_iso.resolve()
            except Exception:
                pass
            if candidate_iso.is_file() and candidate_iso.suffix.lower() == ".iso":
                iso_file = candidate_iso
                candidates.append(candidate_iso.parent)

        # 2) Recover ISO path from persisted task state when the popup has been
        # reopened after the build completed.
        if self._latest_iso_batch:
            try:
                state = self.iso_manager.state(self._latest_iso_batch) or {}
            except Exception:
                state = {}

            state_iso = str(state.get("iso_path", "") or "").strip()
            if state_iso and iso_file is None:
                candidate_iso = Path(state_iso).expanduser()
                try:
                    candidate_iso = candidate_iso.resolve()
                except Exception:
                    pass
                if candidate_iso.is_file() and candidate_iso.suffix.lower() == ".iso":
                    iso_file = candidate_iso
                    self._latest_iso_path = str(candidate_iso)
                    candidates.append(candidate_iso.parent)

            metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
            for key in ("output_dir", "work_dir", "project_dir", "uup_dir"):
                raw = str(metadata.get(key, "") or "").strip()
                if not raw:
                    continue
                candidate = Path(raw).expanduser()
                if candidate.name.lower() == "uups":
                    candidate = candidate.parent
                candidates.append(candidate)

        # 3) Use the latest in-memory work directory.
        if self._latest_iso_work_dir:
            candidates.append(Path(self._latest_iso_work_dir).expanduser())

        # 4) Recover a project directory from download jobs belonging to the batch.
        if self._latest_iso_batch:
            for job in self.manager.all_jobs():
                if getattr(job, "batch_id", "") != self._latest_iso_batch:
                    continue
                candidate = Path(job.target_path).expanduser().parent
                if candidate.name.lower() == "uups":
                    candidate = candidate.parent
                candidates.append(candidate)
                break

        unique_candidates = []
        seen = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            key = os.path.normcase(os.path.normpath(str(resolved)))
            if key in seen:
                continue
            seen.add(key)
            if resolved.exists() and resolved.is_dir():
                unique_candidates.append(resolved)

        target = iso_file.parent if iso_file is not None else (unique_candidates[0] if unique_candidates else None)
        if target is None:
            show_warning(
                self,
                "Klasör bulunamadı",
                "Bu ISO görevi için açılabilecek bir ISO veya çalışma klasörü bulunamadı.\n\n"
                "ISO görevinin çıktı yolu kaydedilmemiş olabilir.",
            )
            return

        errors = []

        # A finished ISO should be selected in Explorer. This makes the button's
        # result immediately visible to the user instead of merely opening a folder.
        if iso_file is not None and os.name == "nt":
            try:
                normalized_iso = os.path.normpath(str(iso_file))
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.Popen(
                    ["explorer.exe", f"/select,{normalized_iso}"],
                    creationflags=creationflags,
                )
                self.iso_status.setText(f"ISO klasörü açıldı: {iso_file.parent}")
                return
            except Exception as exc:
                errors.append(f"Explorer /select: {exc}")

        # Windows ShellExecute is more reliable than Qt for local Explorer actions
        # on paths containing spaces or non-ASCII characters.
        if os.name == "nt":
            try:
                import ctypes
                result = ctypes.windll.shell32.ShellExecuteW(
                    None, "open", os.path.normpath(str(target)), None, None, 1
                )
                if int(result) > 32:
                    self.iso_status.setText(f"Klasör açıldı: {target}")
                    return
                errors.append(f"ShellExecuteW kodu: {int(result)}")
            except Exception as exc:
                errors.append(f"ShellExecuteW: {exc}")

        # Native Python fallback.
        try:
            if hasattr(os, "startfile"):
                os.startfile(os.path.normpath(str(target)))
                self.iso_status.setText(f"Klasör açıldı: {target}")
                return
        except Exception as exc:
            errors.append(f"os.startfile: {exc}")

        # Explorer folder fallback.
        if os.name == "nt":
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.Popen(
                    ["explorer.exe", os.path.normpath(str(target))],
                    creationflags=creationflags,
                )
                self.iso_status.setText(f"Klasör açıldı: {target}")
                return
            except Exception as exc:
                errors.append(f"Explorer: {exc}")

        # Cross-platform Qt fallback.
        try:
            if QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
                self.iso_status.setText(f"Klasör açıldı: {target}")
                return
            errors.append("QDesktopServices.openUrl false döndürdü")
        except Exception as exc:
            errors.append(f"QDesktopServices: {exc}")

        show_error(
            self,
            "Klasör açılamadı",
            f"Klasör açılamadı:\n{target}\n\n" + "\n".join(errors[-4:]),
        )

    def _build_stat_card(self, parent_layout, title_text: str, value_text: str, note_text: str,
                         icon_name: str = "", color: str = "#1768E0", tile_bg: str = "#E3EEFC"):
        card = QFrame()
        card.setObjectName("dmStatCard")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(18, 14, 18, 14)
        card_layout.setSpacing(14)
        if icon_name:
            card_layout.addWidget(self._dm_tile(icon_name, color, tile_bg, 54, 28), 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        title = QLabel(title_text)
        title.setObjectName("dmStatTitle")
        value = QLabel(value_text)
        value.setObjectName("dmStatValue")
        note = QLabel(note_text)
        note.setObjectName("dmStatNote")
        text_col.addWidget(title)
        text_col.addWidget(value)
        text_col.addWidget(note)
        card_layout.addLayout(text_col, 1)
        parent_layout.addWidget(card, 1)
        return value

    # ── Görünüm yardımcıları (mantıktan bağımsız) ──
    @staticmethod
    def _dm_glyph(kind: str, color: str, size: int = 36) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(raw_qcolor()(color))
        u = size / 36.0
        if kind == "pause":
            p.drawRoundedRect(QRectF(10 * u, 8 * u, 6 * u, 20 * u), 1.5 * u, 1.5 * u)
            p.drawRoundedRect(QRectF(20 * u, 8 * u, 6 * u, 20 * u), 1.5 * u, 1.5 * u)
        else:
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            p.drawPolygon(QPolygonF([QPointF(12 * u, 7 * u), QPointF(28 * u, 18 * u), QPointF(12 * u, 29 * u)]))
        p.end()
        return pm

    def _dm_icon(self, name: str, color: str) -> QIcon:
        def make(c):
            if name in ("pause", "play"):
                return self._dm_glyph(name, c)
            return icons.pixmap(name, c, 36, stroke=2.0)
        icon = QIcon()
        icon.addPixmap(make(color), QIcon.Normal)
        icon.addPixmap(make("#9AA8BF"), QIcon.Disabled)
        return icon

    def _dm_tile(self, name: str, color: str, bg: str, size: int = 48, glyph: int = 26) -> QLabel:
        tile = QLabel()
        tile.setFixedSize(size, size)
        tile.setAlignment(Qt.AlignCenter)
        tile.setStyleSheet(f"background: {bg}; border-radius: {size // 2 - 2}px;")
        tile.setPixmap(icons.pixmap(name, color, glyph, stroke=1.9))
        return tile

    def _sync_empty_state(self, *args):
        try:
            empty = self.table.rowCount() == 0
            self.table_stack.setCurrentWidget(self.empty_state if empty else self.table)
            if empty:
                has_jobs = bool(self.manager.status_counts().get("total", 0))
                self.empty_title.setText("Bu filtrede indirme yok" if has_jobs else "Henüz indirme yok")
                self.empty_text.setVisible(not has_jobs)
            total = self.manager.status_counts().get("total", 0)
            idle_text = "İndirme kuyruğu boş. Herhangi bir indirme başlatılmadı."
            running_text = "İndirme kuyruğu çalışıyor."
            schedule = self.manager.schedule_text()
            if schedule and total and not self.manager.schedule_open():
                self.global_queue_status.setText(schedule)
                return
            current = self.global_queue_status.text()
            if total and current in (idle_text, self.manager.schedule_text()):
                self.global_queue_status.setText(running_text)
            elif not total and current == running_text:
                self.global_queue_status.setText(idle_text)
        except RuntimeError:
            pass

    def _apply_dm_styles(self):
        self.setStyleSheet(styles.qss("""
            QWidget#dmPage { background: #F3F7FC; }
            QLabel { background: transparent; }
            QLabel#dmTitle { font-size: 30px; font-weight: 700; color: #0A1F44; }
            QFrame#dmStatCard, QFrame#dmCard {
                background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px;
            }
            QLabel#dmStatTitle { color: #3A4D70; font-size: 13px; font-weight: 600; }
            QLabel#dmStatValue { color: #0A1F44; font-size: 28px; font-weight: 700; }
            QLabel#dmStatNote { color: #6B7C99; font-size: 12px; }
            QLabel#dmCardTitle { color: #0A1F44; font-size: 17px; font-weight: 700; }
            QLabel#dmCardDesc { color: #5F7090; font-size: 12px; }
            QLabel#dmSection { color: #3A4D70; font-size: 13px; font-weight: 700; }
            QFrame#dmInfoStrip { background: #EAF2FE; border: 1px solid #D5E3F8; border-radius: 10px; }
            QLabel#subtleInfoBox { color: #1F4F9E; font-size: 13px; background: transparent; border: none; padding: 0; }
            QLabel#infoBox { color: #5F7090; font-size: 12px; background: transparent; border: none; padding: 0; }
            QPushButton#filterChip {
                background: #FFFFFF; color: #3A4D70; border: 1px solid #D0DCEC; border-radius: 17px;
                padding: 0 16px; font-size: 13px; font-weight: 600; min-height: 34px; max-height: 34px;
            }
            QPushButton#filterChip:hover { background: #F1F6FD; border-color: #9DB9E6; }
            QPushButton#filterChip:checked { background: @BLUE@; color: #FFFFFF; border: 1px solid @BLUE@; }
            QPushButton#dmPrimary {
                background: @BLUE@; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 0 20px; font-size: 13px; font-weight: 700; min-height: 42px; max-height: 42px;
            }
            QPushButton#dmPrimary:hover { background: #135BC4; }
            QPushButton#dmAction, QPushButton#dmDanger {
                background: #FFFFFF; border: 1px solid #CBD9EC; border-radius: 10px;
                padding: 0 8px; font-size: 12px; font-weight: 600; min-height: 40px; max-height: 40px;
            }
            QPushButton#dmAction { color: @BLUE@; }
            QPushButton#dmDanger { color: #D93C3C; border-color: #F0C4C4; }
            QPushButton#dmAction:hover { background: #F1F6FD; border-color: #9DB9E6; }
            QPushButton#dmDanger:hover { background: #FFF4F4; }
            QPushButton#dmAction:disabled, QPushButton#dmDanger:disabled {
                color: #9AA8BF; background: #F4F7FB; border: 1px solid #E5ECF5;
            }
            QComboBox#modernComboBox {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 9px; padding: 0 28px 0 12px;
                font-size: 13px; color: #14213D; min-height: 38px; max-height: 38px;
            }
            QFrame#dmTableBox { background: #FFFFFF; border: 1px solid #E3EAF4; border-radius: 12px; }
            QWidget#dmEmpty { background: #FFFFFF; }
            QLabel#dmEmptyCircle { background: #E3EEFC; border-radius: 46px; }
            QLabel#dmEmptyTitle { color: #0A1F44; font-size: 20px; font-weight: 700; }
            QLabel#dmEmptyText { color: #5F7090; font-size: 13px; }
            QTableWidget#dmTable {
                background: #FFFFFF; alternate-background-color: #FFFFFF; border: none; outline: none;
                gridline-color: transparent; selection-background-color: #EAF2FE; selection-color: #14213D;
            }
            QTableWidget#dmTable::item { border-bottom: 1px solid #EDF1F6; padding: 4px 8px; }
            QTableWidget#dmTable QHeaderView::section {
                background: #F4F8FD; color: #3A4D70; border: none; padding: 0 8px;
                font-size: 12px; font-weight: 700;
            }
            QProgressBar#downloadProgress {
                border: none; background: #E3EBF6; border-radius: 7px; text-align: center;
                color: #14213D; font-size: 11px; font-weight: 700; margin: 9px 6px; min-width: 90px;
            }
            QProgressBar#downloadProgress::chunk { background: #9CC2F7; border-radius: 7px; }
        """))

    def _selected_job_ids(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        result = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                job_id = item.data(Qt.UserRole)
                if job_id:
                    result.append(job_id)
        return result

    def _selected_job_id(self):
        job_ids = self._selected_job_ids()
        return job_ids[0] if job_ids else None

    def _status_display(self, job) -> str:
        if job.status == "İndiriliyor" and job.speed > 0:
            return "İndiriliyor"
        if job.status == "Tamamlandı" and getattr(job, "verification_status", "") == "Doğrulandı":
            return "Tamamlandı ✓ Doğrulandı"
        if job.status == "Tamamlandı" and str(getattr(job, "verification_status", "")) in {"BAŞARISIZ", "Kontrol hatası"}:
            return "Tamamlandı ⚠ Doğrulanamadı"
        if str(getattr(job, "verification_status", "")) == "Doğrulanıyor":
            return "Doğrulanıyor…"
        return job.status

    def _apply_row_style(self, row: int, job):
        if job.status == "Tamamlandı":
            bg = "#EDF9F1"
            fg = "#1B5E20"
        elif job.status in {"İndiriliyor", "Başlatılıyor", "Devam ediyor"}:
            bg = "#EAF2FF"
            fg = "#184D9C"
        elif job.status == "Duraklatıldı":
            bg = "#FFF8E8"
            fg = "#9A6700"
        elif job.status in {"İptal Edildi", "İptal edildi", "Hata"}:
            bg = "#FFF1F1"
            fg = "#B3261E"
        else:
            bg = "#FFFFFF"
            fg = "#243B5A"

        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is None:
                continue
            item.setBackground(QColor(bg))
            item.setForeground(QColor(fg if col == 2 else "#14213D"))

        status_item = self.table.item(row, 2)
        if status_item is not None:
            status_item.setBackground(QColor(bg))
            status_item.setForeground(QColor(fg))
            font = status_item.font()
            font.setBold(True)
            status_item.setFont(font)

    def _job_priority(self, job) -> tuple[int, int, str]:
        status = str(job.status or "").strip()
        queue_map = {jid: index for index, jid in enumerate(getattr(self.manager, "_queue", []))}
        order_map = {jid: index for index, jid in enumerate(self.manager.jobs.keys())}

        # İstenen ana sıralama:
        # 1) İndiriliyor
        # 2) Kuyrukta
        # 3) Tamamlandı
        if status in {"İndiriliyor", "Başlatılıyor", "Devam ediyor"}:
            primary = 0
        elif status in {"Kuyrukta", "Duraklatıldı"} or status.startswith("Devam için yeniden deneniyor"):
            primary = 1
        elif status == "Tamamlandı":
            primary = 2
        elif status in {"İptal edildi", "İptal Edildi"}:
            primary = 3
        elif status == "Hata":
            primary = 4
        else:
            primary = 5

        secondary = queue_map.get(job.id, order_map.get(job.id, 999999))
        return primary, secondary, job.filename.lower()

    def _status_group(self, job) -> str:
        status = str(job.status or "")
        if status in {"İndiriliyor", "Başlatılıyor", "Devam ediyor"}:
            return "running"
        if status == "Kuyrukta" or status == "Duraklatıldı" or status.startswith("Devam için yeniden deneniyor"):
            return "queued"
        if status == "Tamamlandı":
            return "completed"
        if status in {"Hata", "İptal edildi", "İptal Edildi"}:
            return "problem"
        return "other"

    def _set_filter(self, key: str):
        self._current_filter = key
        for name, button in self.filter_buttons.items():
            button.setChecked(name == key)
        self._rebuild_table()

    def _sorted_jobs(self):
        jobs = sorted(self.manager.all_jobs(), key=self._job_priority)
        if self._current_filter == "all":
            return jobs
        return [job for job in jobs if self._status_group(job) == self._current_filter]

    def _create_progress_widget(self):
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(True)
        progress.setFormat("%p%")
        progress.setObjectName("downloadProgress")
        return progress

    def _schedule_rebuild(self, preferred_job_id: str | None = None):
        if preferred_job_id:
            self._pending_preferred_job_id = preferred_job_id
        if self._rebuild_scheduled:
            return
        self._rebuild_scheduled = True
        QTimer.singleShot(60, self._run_scheduled_rebuild)

    def _run_scheduled_rebuild(self):
        self._rebuild_scheduled = False
        preferred_job_id = self._pending_preferred_job_id
        self._pending_preferred_job_id = None
        self._rebuild_table(preferred_job_id=preferred_job_id)

    def _ensure_job(self, job_id: str):
        # UUP grupları onlarca dosyayı aynı anda ekler. Her job_added sinyalinde
        # tabloyu baştan oluşturmak UI thread'ini kilitler. Tüm eklemeleri tek
        # bir event-loop yenilemesinde birleştiriyoruz.
        self._schedule_rebuild(preferred_job_id=job_id)

    def _rebuild_table(self, preferred_job_id: str | None = None):
        selected_job_ids = set(self._selected_job_ids())
        if not selected_job_ids and preferred_job_id:
            selected_job_ids.add(preferred_job_id)
        jobs = self._sorted_jobs()

        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self._row_for_job = {}

        for row, job in enumerate(jobs):
            self.table.insertRow(row)
            self._row_for_job[job.id] = row

            for col in range(self.table.columnCount()):
                if col == 4:
                    continue
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)

            first = self.table.item(row, 0)
            first.setData(Qt.UserRole, job.id)

            progress = self._create_progress_widget()
            self.table.setCellWidget(row, 4, progress)
            self._update_row_contents(row, job)

        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)

        self.table.clearSelection()
        if selected_job_ids:
            selection_model = self.table.selectionModel()
            for job_id in selected_job_ids:
                row = self._row_for_job.get(job_id)
                if row is None:
                    continue
                index = self.table.model().index(row, 0)
                selection_model.select(
                    index,
                    selection_model.SelectionFlag.Select | selection_model.SelectionFlag.Rows,
                )

        self._refresh_summary_only()
        self._update_action_states()
        self._update_global_action_states()
        self.table.viewport().update()

    def _update_row_contents(self, row: int, job):
        queue_position = self.manager.queue_position(job.id)
        values = [
            job.filename,
            job.architecture or "—",
            self._status_display(job),
            str(queue_position) if queue_position else "—",
            None,
            f"{format_bytes(job.downloaded)} / {format_bytes(job.total)}",
            format_speed(job.speed),
            format_eta(job.eta),
            job.target_path,
        ]
        for col, value in enumerate(values):
            if col == 4:
                continue
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(str(value))
            if col == 0:
                item.setData(Qt.UserRole, job.id)
                verification = getattr(job, "verification_status", "")
                if verification and verification != "Bekleniyor":
                    item.setToolTip((job.error or job.filename) + "\n\nGüvenlik: " + verification + ("\nSHA-256: " + job.sha256 if getattr(job, "sha256", "") else ""))
                else:
                    item.setToolTip(job.error or job.filename)
            elif col == 8:
                item.setToolTip(job.target_path)

        progress = self.table.cellWidget(row, 4)
        if job.total > 0:
            percent = min(100, max(0, int(job.downloaded * 100 / job.total)))
            progress.setRange(0, 100)
            progress.setValue(percent)
            progress.setFormat(f"{percent}%")
        elif job.status == "Tamamlandı":
            progress.setRange(0, 100)
            progress.setValue(100)
            progress.setFormat("100%")
        elif job.status == "Kuyrukta":
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setFormat("Bekliyor")
        elif job.status == "Duraklatıldı":
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setFormat("Duraklatıldı")
        else:
            progress.setRange(0, 0)
            progress.setFormat("")

        self._apply_row_style(row, job)

    def _queue_job_refresh(self, job_id: str):
        self._pending_job_updates.add(job_id)
        if not self._ui_refresh_timer.isActive():
            self._ui_refresh_timer.start()

    def _refresh_job(self, job_id: str):
        """Compatibility wrapper: queue a throttled refresh."""
        self._queue_job_refresh(job_id)

    def _flush_job_updates(self):
        pending = set(self._pending_job_updates)
        self._pending_job_updates.clear()
        if not pending:
            return

        # Check ordering once for the whole batch, not once per progress event.
        desired_order = [item.id for item in self._sorted_jobs()]
        current_order = []
        for current_row in range(self.table.rowCount()):
            item = self.table.item(current_row, 0)
            current_order.append(item.data(Qt.UserRole) if item else None)

        if desired_order != current_order:
            preferred = next(iter(pending), None)
            self._schedule_rebuild(preferred_job_id=preferred)
            return

        self.table.setUpdatesEnabled(False)
        try:
            for job_id in pending:
                job = self.manager.get(job_id)
                row = self._row_for_job.get(job_id)
                if job is None or row is None:
                    continue
                self._update_row_contents(row, job)
        finally:
            self.table.setUpdatesEnabled(True)

        self._refresh_summary_only()
        self._update_action_states()
        self._update_global_action_states()
        self.table.viewport().update()

    def _refresh_summary_only(self):
        counts = self.manager.status_counts()
        total = counts["total"]
        running = counts["running"]
        queued = counts["queued"] + counts["paused"]
        done = counts["completed"]
        problem = counts["failed"] + counts["cancelled"]

        if total == 0:
            self.summary.setText("Henüz indirme yok. Bir paket seçildiğinde indirme listesi burada görünecek.")
        else:
            pieces = [
                f"Toplam {total}",
                f"İndiriliyor {running}",
                f"Kuyrukta {queued}",
                f"Tamamlandı {done}",
            ]
            if problem:
                pieces.append(f"Sorunlu {problem}")
            if self.manager.global_paused:
                pieces.append("Kuyruk duraklatıldı")
            self.summary.setText(" • ".join(pieces))

        self.total_value.setText(str(total))
        self.active_value.setText(str(running))
        self.waiting_value.setText(str(queued))
        self.completed_value.setText(str(done))

        if hasattr(self, "filter_buttons"):
            self.filter_buttons["all"].setText(f"Tümü ({total})")
            self.filter_buttons["running"].setText(f"İndiriliyor ({running})")
            self.filter_buttons["queued"].setText(f"Kuyrukta ({queued})")
            self.filter_buttons["completed"].setText(f"Tamamlandı ({done})")
            self.filter_buttons["problem"].setText(f"Sorunlu ({problem})")

    def _update_action_states(self):
        job_ids = self._selected_job_ids()
        jobs = [self.manager.get(jid) for jid in job_ids]
        jobs = [job for job in jobs if job is not None]

        self.pause_button.setEnabled(any(
            job.status in {"Kuyrukta", "Başlatılıyor", "İndiriliyor", "Devam ediyor"}
            or job.status.startswith("Devam için yeniden deneniyor")
            for job in jobs
        ))
        self.resume_button.setEnabled(any(
            job.status in {"Duraklatıldı", "Hata", "İptal Edildi", "İptal edildi"}
            for job in jobs
        ))
        self.cancel_button.setEnabled(any(
            job.status not in {"Tamamlandı", "İptal Edildi", "İptal edildi"}
            for job in jobs
        ))
        self.retry_button.setEnabled(any(
            job.status in {"Hata", "İptal Edildi", "İptal edildi"}
            for job in jobs
        ))
        self.open_folder_button.setEnabled(bool(jobs))
        self.delete_selected_button.setEnabled(bool(jobs))
        self.clear_completed_button.setEnabled(bool(self.manager.completed_job_ids()))

    def _show_table_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if index.isValid() and index.row() not in {i.row() for i in self.table.selectionModel().selectedRows()}:
            self.table.clearSelection()
            self.table.selectRow(index.row())

        selected_ids = self._selected_job_ids()
        menu = QMenu(self)

        remove_history = menu.addAction("Seçilenleri Listeden Kaldır")
        delete_files = menu.addAction("Seçilen Dosyaları Diskten Sil")
        menu.addSeparator()
        clear_completed = menu.addAction("Tamamlananları Temizle")

        remove_history.setEnabled(bool(selected_ids))
        delete_files.setEnabled(bool(selected_ids))
        clear_completed.setEnabled(bool(self.manager.completed_job_ids()))

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == remove_history:
            self._remove_selected_jobs(delete_files=False)
        elif action == delete_files:
            self._remove_selected_jobs(delete_files=True)
        elif action == clear_completed:
            self._clear_completed_jobs()

    def _delete_selected_files(self):
        self._remove_selected_jobs(delete_files=True)

    def _remove_selected_jobs(self, delete_files: bool):
        job_ids = self._selected_job_ids()
        if not job_ids:
            show_information(self, "Seçim yok", "Önce silmek istediğiniz kayıtları seçin.")
            return

        action_text = "dosyaları diskten silmek" if delete_files else "kayıtları listeden kaldırmak"
        if not ask_confirmation(
            self,
            "Silme onayı",
            f"Seçilen {len(job_ids)} kayıt için {action_text} istediğinize emin misiniz?\n\n"
            "Aktif, kuyruktaki veya duraklatılmış indirmeler güvenlik nedeniyle silinmez.",
            confirm_text="Sil",
            cancel_text="Vazgeç",
            destructive=True,
        ):
            return

        result = self.manager.remove_jobs(job_ids, delete_files=delete_files)
        self._rebuild_table()
        self._show_cleanup_result(result, delete_files)

    def _clear_completed_jobs(self):
        job_ids = self.manager.completed_job_ids()
        if not job_ids:
            show_information(self, "Temizlenecek kayıt yok", "Tamamlanmış indirme kaydı bulunmuyor.")
            return

        choice = ask_choice(
            self,
            "Tamamlananları temizle",
            "Tamamlanan indirmeleri temizle",
            f"{len(job_ids)} tamamlanmış indirme kaydı bulundu.\n\n"
            "Yalnızca geçmiş kayıtlarını kaldırabilir veya indirilen dosyaları da diskten silebilirsiniz.",
            [
                DialogAction("history", "Yalnızca Listeden Kaldır", "primary"),
                DialogAction("files", "Dosyaları da Sil", "danger"),
                DialogAction("cancel", "Vazgeç", "secondary"),
            ],
        )
        if choice not in {"history", "files"}:
            return

        delete_files = choice == "files"
        result = self.manager.remove_jobs(job_ids, delete_files=delete_files)
        self._rebuild_table()
        self._show_cleanup_result(result, delete_files)

    def _show_cleanup_result(self, result, delete_files: bool):
        removed = len(result.get("removed", []))
        skipped = result.get("skipped", [])
        errors = result.get("errors", [])

        details = [f"{removed} kayıt temizlendi."]
        if delete_files and removed:
            details.append("İlgili yerel dosyalar da silinmeye çalışıldı.")
        if skipped:
            details.append(f"{len(skipped)} aktif/korumalı kayıt atlandı.")
        if errors:
            details.append(f"{len(errors)} dosya silinemedi; dosya kullanımda veya erişim izni olmayabilir.")

        show_information(self, "Temizleme tamamlandı", "\n".join(details))

    def _pause_all(self):
        result = self.manager.pause_all()
        self.global_queue_status.setText(
            f"Tüm indirmeler duraklatıldı. {result['paused']} aktif indirme bekletiliyor; "
            f"{result['queued']} dosya kuyrukta."
        )
        self._refresh_summary_only()
        self._update_global_action_states()

    def _resume_all(self):
        result = self.manager.resume_all()
        self.global_queue_status.setText(
            f"İndirme kuyruğu yeniden başlatıldı. {result['resumed']} indirme devam ediyor."
        )
        self._refresh_summary_only()
        self._update_global_action_states()

    def _cancel_all(self):
        unfinished = [
            job for job in self.manager.all_jobs()
            if job.status not in {"Tamamlandı", "İptal edildi", "İptal Edildi"}
        ]
        if not unfinished:
            show_information(self, "Tümünü iptal et", "İptal edilecek aktif veya bekleyen indirme yok.")
            return

        if not ask_confirmation(
            self,
            "Tüm indirmeleri iptal et",
            f"{len(unfinished)} tamamlanmamış indirme iptal edilecek. "
            "Yarım kalan .part dosyaları silinmeyecek ve daha sonra yeniden denenebilecek.\n\n"
            "Devam etmek istiyor musunuz?",
            confirm_text="Tümünü İptal Et",
            cancel_text="Vazgeç",
            destructive=True,
        ):
            return

        result = self.manager.cancel_all()
        self.global_queue_status.setText(
            f"{result['total']} indirme için iptal komutu gönderildi."
        )
        self._refresh_summary_only()
        self._update_global_action_states()

    def _change_concurrency(self, index: int):
        value = self.concurrent_combo.itemData(index)
        if value is None:
            return
        self.manager.set_max_concurrent(int(value))
        self.global_queue_status.setText(
            f"Eşzamanlı indirme sınırı {int(value)} olarak ayarlandı."
        )

    def _update_global_action_states(self):
        counts = self.manager.status_counts()
        unfinished = (counts["running"] + counts["queued"] + counts["paused"]) > 0
        self.pause_all_button.setEnabled(unfinished and not self.manager.global_paused)
        self.resume_all_button.setEnabled(unfinished and self.manager.global_paused)
        self.cancel_all_button.setEnabled(unfinished)

    def _pause(self):
        job_ids = self._selected_job_ids()
        if job_ids:
            self.manager.pause_many(job_ids)

    def _resume(self):
        job_ids = self._selected_job_ids()
        if job_ids:
            self.manager.resume_many(job_ids)

    def _cancel(self):
        job_ids = self._selected_job_ids()
        if job_ids:
            self.manager.cancel_many(job_ids)

    def _retry(self):
        job_ids = self._selected_job_ids()
        if job_ids:
            self.manager.retry_many(job_ids)

    def _open_folder(self):
        jid = self._selected_job_id()
        if not jid:
            return
        job = self.manager.get(jid)
        if not job:
            return
        folder = str(Path(job.target_path).parent)
        try:
            import os
            os.startfile(folder)
        except Exception as exc:
            show_warning(self, "Klasör açılamadı", str(exc))
