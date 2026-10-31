from datetime import datetime
from pathlib import Path
import re
import webbrowser

from PySide6.QtCore import QSize, QThread, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QTransform
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
)

from ui import icons, styles
from ui.widgets.message_dialog import ask_confirmation, show_message
from ui.widgets.modern_combo_box import ModernComboBox
from workers.uup_search_worker import UupSearchWorker
from workers.uup_prepare_worker import UupPrepareWorker
from services.download_manager import DownloadManager
from services.system_profile import SystemProfileService
from services.settings_service import SettingsService


class _ElidedLabel(QLabel):
    """Uzun metni tek satırda keser, tam metni ipucunda gösterir (yalnızca görünüm)."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setText(text)

    def setText(self, text):
        self._full = str(text or "")
        self.setToolTip(self._full if len(self._full) > 18 else "")
        super().setText(self._full)
        self.update()

    def text(self):
        return self._full

    def minimumSizeHint(self):
        return QSize(20, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        elided = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(1, self.width()))
        painter.drawText(self.rect(), int(self.alignment()) | Qt.AlignVCenter, elided)


EDITION_OPTIONS = ["Windows 11", "Windows 11 Pro"]


class UupCenterPage(QWidget):
    # ISO Merkezi'nden başlatılan otomatik indirme bittiğinde: (başarılı mı, kullanıcıya mesaj)
    auto_finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_pending = False

        self.current_build = ""
        self.current_title = ""
        self.current_channel = ""
        self.current_source = ""
        self._thread = None
        self._worker = None
        self._results = []
        self._prepare_thread = None
        self._prepare_worker = None

        self.setObjectName("uupPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 20, 26, 22)
        layout.setSpacing(14)

        def ico(name, color, size=36, stroke=2.0):
            return QIcon(icons.pixmap(name, color, size, stroke=stroke))

        # ── Başlık ──
        header = QHBoxLayout()
        header.setSpacing(14)
        head_icon = QLabel()
        head_icon.setPixmap(icons.pixmap("cloud-down", "#1768E0", 46, stroke=1.9))
        head_icon.setFixedSize(58, 58)
        head_icon.setAlignment(Qt.AlignCenter)
        header.addWidget(head_icon, 0, Qt.AlignTop)
        head_text = QVBoxLayout()
        head_text.setSpacing(2)
        page_title = QLabel("UUP ISO Oluşturucu")
        page_title.setObjectName("uupTitle")
        subtitle = QLabel(
            "UUP kaynaklarından Windows ISO'su oluşturun, paketleri indirin."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        head_text.addWidget(page_title)
        head_text.addWidget(subtitle)
        header.addLayout(head_text, 1)
        layout.addLayout(header)

        # ── Seçili build kartı ──
        card = QFrame()
        card.setObjectName("searchCard")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(16)

        sel_tile = QLabel()
        sel_tile.setObjectName("uupRoundTile")
        sel_tile.setFixedSize(82, 82)
        sel_tile.setAlignment(Qt.AlignCenter)
        sel_tile.setPixmap(icons.pixmap("cloud-down", "#1768E0", 44, stroke=1.9))
        card_layout.addWidget(sel_tile)

        sel_text = QVBoxLayout()
        sel_text.setSpacing(3)
        sel_caption = QLabel("Seçili Build")
        sel_caption.setObjectName("uupCaption")
        self.selected_headline = QLabel("Henüz build seçilmedi")
        self.selected_headline.setObjectName("uupHeadline")
        self.selected_description = QLabel(
            "Lütfen önce Windows Sürüm Takibi bölümünden bir Insider build seçin veya build kaydı belirleyin."
        )
        self.selected_description.setObjectName("uupDesc")
        self.selected_description.setWordWrap(True)
        sel_text.addStretch()
        sel_text.addWidget(sel_caption)
        sel_text.addWidget(self.selected_headline)
        sel_text.addWidget(self.selected_description)
        sel_text.addStretch()
        card_layout.addLayout(sel_text, 3)

        self.build_label = _ElidedLabel("—")
        self.build_label.setObjectName("detailName")
        self.title_label = _ElidedLabel("—")
        self.title_label.setObjectName("detailName")
        self.channel_label = _ElidedLabel("—")
        self.channel_label.setObjectName("detailName")
        self.source_label = _ElidedLabel("—")
        self.source_label.setObjectName("detailName")
        for caption, icon_name, value_label in (
            ("Build", "windows-color", self.build_label),
            ("Kayıt", "list", self.title_label),
            ("Kanal", "user", self.channel_label),
            ("Kaynak", "external", self.source_label),
        ):
            mini = QFrame()
            mini.setObjectName("uupMini")
            mini.setMinimumWidth(150)
            ml = QHBoxLayout(mini)
            ml.setContentsMargins(14, 10, 12, 10)
            ml.setSpacing(12)
            mic = QLabel()
            mic.setFixedSize(34, 34)
            mic.setAlignment(Qt.AlignCenter)
            mic.setPixmap(icons.pixmap(icon_name, "#1768E0", 26, stroke=2.0))
            ml.addWidget(mic)
            mc = QVBoxLayout()
            mc.setSpacing(2)
            cap = QLabel(caption)
            cap.setObjectName("uupMiniCaption")
            mc.addWidget(cap)
            mc.addWidget(value_label)
            ml.addLayout(mc, 1)
            card_layout.addWidget(mini, 2)
        layout.addWidget(card)

        # ── Seçenekler kartı ──
        options = QFrame()
        options.setObjectName("searchCard")
        options_outer = QVBoxLayout(options)
        options_outer.setContentsMargins(14, 12, 14, 12)
        options_outer.setSpacing(8)
        options_layout = QHBoxLayout()
        options_layout.setSpacing(14)
        options_outer.addLayout(options_layout)

        self.system_profile = SystemProfileService.current()

        self.arch_combo = ModernComboBox()
        self.arch_combo.addItems(["x64", "ARM64", "x86"])
        preferred_arch_index = self.arch_combo.findText(
            f"{self.system_profile.architecture}"
        )
        if preferred_arch_index >= 0:
            self.arch_combo.setCurrentIndex(preferred_arch_index)
        self.arch_combo.setToolTip(
            f"Windows sistem mimarisi otomatik seçildi: {self.system_profile.architecture}. "
            "Farklı bir mimari indirmek için listeden değiştirebilirsiniz."
        )

        self.language_combo = ModernComboBox()
        self.language_combo.addItems(
            [f"{name}" for name in SystemProfileService.language_options()]
        )
        preferred_language_index = self.language_combo.findText(
            f"{self.system_profile.language_name}"
        )
        if preferred_language_index >= 0:
            self.language_combo.setCurrentIndex(preferred_language_index)
        self.language_combo.setToolTip(
            f"Windows arayüz dili otomatik seçildi: {self.system_profile.language_name}. "
            "Farklı bir dil indirmek için listeden değiştirebilirsiniz."
        )

        self.edition_combo = ModernComboBox()
        self.edition_combo.addItems(EDITION_OPTIONS)
        self.apply_settings(SettingsService.load())

        for caption, icon_name, combo in (
            ("Mimari", "cpu", self.arch_combo),
            ("Dil", "globe", self.language_combo),
            ("Edition", "boxes", self.edition_combo),
        ):
            box = QFrame()
            box.setObjectName("uupField")
            bl = QHBoxLayout(box)
            bl.setContentsMargins(14, 8, 12, 8)
            bl.setSpacing(12)
            fic = QLabel()
            fic.setFixedSize(30, 30)
            fic.setAlignment(Qt.AlignCenter)
            fic.setPixmap(icons.pixmap(icon_name, "#1768E0", 24, stroke=1.9))
            bl.addWidget(fic)
            bc = QVBoxLayout()
            bc.setSpacing(0)
            cap = QLabel(caption)
            cap.setObjectName("uupFieldCaption")
            bc.addWidget(cap)
            bc.addWidget(combo)
            bl.addLayout(bc, 1)
            options_layout.addWidget(box, 1)

        info_row = QFrame()
        info_row.setObjectName("uupInfoRow")
        ir = QHBoxLayout(info_row)
        ir.setContentsMargins(12, 7, 12, 7)
        ir.setSpacing(10)
        iic = QLabel()
        iic.setPixmap(icons.pixmap("info-fill", "#1768E0", 16))
        ir.addWidget(iic)
        self.detected_profile_label = QLabel(
            f"Sistem varsayılanları: {self.system_profile.architecture} • "
            f"{self.system_profile.language_name} • {self._combo_value(self.edition_combo.currentText())}"
        )
        self.detected_profile_label.setObjectName("subtleInfoBox")
        self.detected_profile_label.setWordWrap(True)
        ir.addWidget(self.detected_profile_label, 1)
        options_outer.addWidget(info_row)
        layout.addWidget(options)

        # ── Build Seçin kartı (durum metni + arama düğmeleri) ──
        center = QFrame()
        center.setObjectName("searchCard")
        cl = QVBoxLayout(center)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(12)

        top = QFrame()
        top.setObjectName("uupSelectBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 12, 14, 12)
        tl.setSpacing(14)
        ttile = QLabel()
        ttile.setObjectName("uupRoundTile64")
        ttile.setFixedSize(64, 64)
        ttile.setAlignment(Qt.AlignCenter)
        ttile.setPixmap(icons.pixmap("search", "#1768E0", 32, stroke=2.0))
        tl.addWidget(ttile)
        tt = QVBoxLayout()
        tt.setSpacing(3)
        tt_title = QLabel("Build Seçin")
        tt_title.setObjectName("uupSelectTitle")
        self.status = QLabel(
            "Önce Windows Sürüm Takibi bölümünden bir Insider build seçin veya build kaydı belirleyin."
        )
        self.status.setObjectName("infoBox")
        self.status.setWordWrap(True)
        tt.addStretch()
        tt.addWidget(tt_title)
        tt.addWidget(self.status)
        tt.addStretch()
        tl.addLayout(tt, 1)

        self.find_button = QPushButton("  UUP / ISO Seçeneklerini Bul")
        self.find_button.setObjectName("uupPrimary")
        self.find_button.setIcon(ico("cloud-down", "#FFFFFF"))
        self.find_button.setIconSize(QSize(20, 20))
        self.find_button.setEnabled(False)
        self.find_button.setCursor(Qt.PointingHandCursor)
        self.find_button.clicked.connect(
            self.start_search
        )

        self.stop_button = QPushButton("  Aramayı Durdur")
        self.stop_button.setObjectName("uupStop")
        self.stop_button.setIcon(ico("x", "#8A98B0"))
        self.stop_button.setIconSize(QSize(18, 18))
        self.stop_button.setEnabled(False)
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.clicked.connect(
            self.stop_search
        )

        tl.addWidget(self.find_button)
        tl.addWidget(self.stop_button)
        cl.addWidget(top)

        self.result_table = QTableWidget(0, 9)
        self.result_table.setObjectName("uupTable")
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
        self.result_table.setAlternatingRowColors(False)
        self.result_table.setSelectionMode(QTableWidget.SingleSelection)
        self.result_table.setShowGrid(False)
        self.result_table.setFocusPolicy(Qt.NoFocus)
        self.result_table.setFrameShape(QFrame.NoFrame)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.verticalHeader().setDefaultSectionSize(44)

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

        # Boş durum: sonuç yokken tablo yerine açıklayıcı görünüm.
        empty = QWidget()
        empty.setObjectName("uupEmpty")
        el = QVBoxLayout(empty)
        el.setAlignment(Qt.AlignCenter)
        el.setSpacing(8)
        circle = QLabel()
        circle.setObjectName("uupEmptyCircle")
        circle.setFixedSize(104, 104)
        circle.setAlignment(Qt.AlignCenter)
        circle.setPixmap(icons.pixmap("cloud-down", "#1768E0", 62, stroke=2.0))
        el.addWidget(circle, 0, Qt.AlignHCenter)
        et = QLabel("Henüz sonuç yok")
        et.setObjectName("uupEmptyTitle")
        et.setAlignment(Qt.AlignCenter)
        ed = QLabel("Lütfen önce bir build seçin ve arama işlemini başlatın.")
        ed.setObjectName("uupEmptyText")
        ed.setAlignment(Qt.AlignCenter)
        el.addWidget(et)
        el.addWidget(ed)

        table_box = QFrame()
        table_box.setObjectName("uupTableBox")
        tbl = QVBoxLayout(table_box)
        tbl.setContentsMargins(0, 0, 0, 0)
        tbl.setSpacing(0)
        self.result_stack = QStackedWidget()
        self.result_stack.addWidget(empty)
        self.result_stack.addWidget(self.result_table)
        tbl.addWidget(self.result_stack, 1)
        cl.addWidget(table_box, 1)

        def _sync_empty(*_):
            try:
                self.result_stack.setCurrentIndex(1 if self.result_table.rowCount() else 0)
            except RuntimeError:
                pass

        model = self.result_table.model()
        model.rowsInserted.connect(_sync_empty)
        model.rowsRemoved.connect(_sync_empty)
        model.modelReset.connect(_sync_empty)
        _sync_empty()
        layout.addWidget(center, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(14)

        self.open_button = QPushButton(
            "  UUP Sayfasını Aç"
        )
        self.open_button.setIcon(ico("external", "#1768E0"))
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(
            self.open_selected_result
        )

        self.prepare_button = QPushButton(
            "  UUP Dosyalarını İndir"
        )
        self.prepare_button.setIcon(ico("download", "#1768E0"))
        self.prepare_button.setEnabled(False)
        self.prepare_button.clicked.connect(
            self.prepare_selected_result
        )

        self.download_manager_button = QPushButton(
            "  İndirme Yöneticisini Aç"
        )
        self.download_manager_button.setIcon(ico("download-tray", "#1768E0"))
        self.download_manager_button.setEnabled(False)
        self.download_manager_button.clicked.connect(
            self._open_download_manager
        )

        for b in (self.open_button, self.prepare_button, self.download_manager_button):
            b.setObjectName("uupAction")
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.PointingHandCursor)
            action_row.addWidget(b, 1)
        layout.addLayout(action_row)

        self.result_table.itemSelectionChanged.connect(
            self._on_selection_changed
        )
        self._apply_uup_styles()

    def _apply_uup_styles(self):
        self.setStyleSheet(styles.qss("""
            QWidget#uupPage { background: #F3F7FC; }
            QLabel { background: transparent; }
            QLabel#uupTitle { font-size: 30px; font-weight: 700; color: #0A1F44; }
            QFrame#searchCard { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px; }
            QLabel#uupRoundTile, QLabel#uupEmptyCircle { background: #E3EEFC; border-radius: 41px; }
            QLabel#uupEmptyCircle { border-radius: 52px; }
            QLabel#uupRoundTile64 { background: #E3EEFC; border-radius: 32px; }
            QLabel#uupCaption { color: #3A4D70; font-size: 13px; font-weight: 600; }
            QLabel#uupHeadline { color: @BLUE@; font-size: 17px; font-weight: 700; }
            QLabel#uupDesc { color: #5F7090; font-size: 12px; }
            QFrame#uupMini { background: #F6F9FE; border: 1px solid #E3EAF4; border-radius: 12px; }
            QLabel#uupMiniCaption { color: #3A4D70; font-size: 12px; font-weight: 600; }
            QLabel#detailName { color: #14213D; font-size: 14px; font-weight: 700; }
            QFrame#uupField { background: #F6F9FE; border: 1px solid #E3EAF4; border-radius: 12px; }
            QLabel#uupFieldCaption { color: #3A4D70; font-size: 12px; font-weight: 600; }
            QFrame#uupField QComboBox#modernComboBox {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 9px; padding: 0 28px 0 12px;
                font-size: 13px; color: #14213D; min-height: 34px; max-height: 34px;
            }
            QFrame#uupField QComboBox#modernComboBox:hover { border-color: #9DB9E6; }
            QFrame#uupInfoRow { background: #F6F9FE; border: none; border-radius: 8px; }
            QLabel#subtleInfoBox { color: #4A5B7A; font-size: 12px; background: transparent; border: none; padding: 0; }
            QFrame#uupSelectBar { background: #EEF4FD; border: 1px solid #E0E9F6; border-radius: 12px; }
            QLabel#uupSelectTitle { color: #14213D; font-size: 17px; font-weight: 700; }
            QLabel#infoBox { color: #5F7090; font-size: 12px; background: transparent; border: none; padding: 0; }
            QPushButton#uupPrimary {
                background: @BLUE@; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 0 20px; font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
            }
            QPushButton#uupPrimary:hover { background: #135BC4; }
            QPushButton#uupPrimary:disabled { background: #A9C4EE; }
            QPushButton#uupStop {
                background: #FFFFFF; color: #D93C3C; border: 1px solid #F0C4C4; border-radius: 10px;
                padding: 0 20px; font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
            }
            QPushButton#uupStop:hover { background: #FFF4F4; }
            QPushButton#uupStop:disabled { color: #8A98B0; background: #F4F7FB; border: 1px solid #E1E8F2; }
            QFrame#uupTableBox { background: #FFFFFF; border: 1px solid #E3EAF4; border-radius: 12px; }
            QWidget#uupEmpty { background: #FFFFFF; }
            QLabel#uupEmptyTitle { color: #0A1F44; font-size: 20px; font-weight: 700; }
            QLabel#uupEmptyText { color: #5F7090; font-size: 13px; }
            QTableWidget#uupTable { background: #FFFFFF; border: none; outline: none; gridline-color: transparent;
                selection-background-color: #EAF2FE; selection-color: #14213D; }
            QTableWidget#uupTable::item { border-bottom: 1px solid #EDF1F6; padding: 4px 8px; }
            QTableWidget#uupTable QHeaderView::section {
                background: #F4F8FD; color: #3A4D70; border: none; padding: 12px 8px;
                font-size: 12px; font-weight: 700;
            }
            QPushButton#uupAction {
                background: #FFFFFF; color: @BLUE@; border: 1px solid #CBD9EC; border-radius: 12px;
                font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
            }
            QPushButton#uupAction:hover { background: #F1F6FD; border-color: #9DB9E6; }
            QPushButton#uupAction:disabled { color: #9AA8BF; background: #F4F7FB; border: 1px solid #E5ECF5; }
        """))

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
            f"{self.current_build or '—'}"
        )
        self.title_label.setText(
            f"{self.current_title or '—'}"
        )
        self.channel_label.setText(
            f"{self.current_channel or '—'}"
        )
        self.source_label.setText(
            f"{self.current_source or 'Microsoft'}"
        )
        self.selected_headline.setText(
            self.current_build or "Henüz build seçilmedi"
        )
        self.selected_description.setText(
            self.current_title
            or "Lütfen önce Windows Sürüm Takibi bölümünden bir Insider build seçin veya build kaydı belirleyin."
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

    def request_auto_download(self, build, title, channel, source, architecture, language, edition) -> None:
        """ISO Merkezi'nden gelen istek: UUP'de ara, uygun kaydı seç ve dosyaları indirmeye gönder."""
        if self._auto_pending or (self._thread and self._thread.isRunning()) or (
            self._prepare_thread and self._prepare_thread.isRunning()
        ):
            self.auto_finished.emit(False, "UUP işlemi zaten çalışıyor; bitmesini bekleyin.")
            return
        self.set_build_context(build, title, channel, source)
        for combo, text in ((self.arch_combo, architecture), (self.language_combo, language), (self.edition_combo, edition)):
            index = combo.findText(text) if text else -1
            if index >= 0:
                combo.setCurrentIndex(index)
        self._auto_pending = True
        self.start_search()
        if not (self._thread and self._thread.isRunning()):  # arama başlatılamadı
            self._auto_done(False, "UUP araması başlatılamadı.")

    def _auto_done(self, ok: bool, message: str) -> None:
        if self._auto_pending:
            self._auto_pending = False
            self.auto_finished.emit(ok, message)

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
            (self.arch_combo, f"{arch}"),
            (self.language_combo, f"{language}"),
            (self.edition_combo, f"{edition}"),
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
        self._auto_done(False, "UUP araması durduruldu.")

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
            self._auto_done(False, "Seçilen build ve mimari için UUP kaydı bulunamadı.")
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

        if self._auto_pending:
            usable = next(
                (i for i, r in enumerate(self._results) if r.language_available and r.edition_available), None
            )
            if usable is None:
                self._auto_done(False, "Bu build için seçtiğiniz dil veya edition UUP'de bulunamadı. Başka bir dil/edition deneyin.")
            else:
                self.result_table.selectRow(usable)
                self.prepare_selected_result()

    def _on_search_failed(self, message):
        self.find_button.setEnabled(
            bool(self.current_build)
        )
        self.stop_button.setEnabled(False)
        self.status.setText(
            "UUP araması tamamlanamadı."
        )

        if self._auto_pending:
            self._auto_done(False, f"UUP kayıtları alınamadı: {message}")
            return

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
            self._auto_done(False, "UUP dosya bağlantısı bulunamadı.")
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
            self._auto_done(False, "İndirme klasörü seçilmedi; işlem iptal edildi.")
            return

        if not self._space_preflight(Path(base_folder), int(getattr(result, "total_size", 0) or 0)):
            self.status.setText("UUP indirme işlemi iptal edildi (yetersiz disk alanı).")
            self.prepare_button.setEnabled(True)
            self.find_button.setEnabled(bool(self.current_build))
            self._auto_done(False, "Seçilen diskte yeterli boş alan yok; işlem başlatılmadı.")
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
            self._auto_done(False, "UUP dosyaları indirme kuyruğuna eklenemedi.")
        else:
            self.download_manager_button.setEnabled(True)
            self.status.setText(
                f"{len(job_ids)} UUP dosyası indirme kuyruğuna eklendi. "
                f"Yeni indirme klasörü: {project_dir.name}. "
                "Aynı build ve sürüm tekrar indirilebilir. "
                "UUP / ISO Merkezi açık kalacak. İndirme durumunu görmek için "
                "İndirme Yöneticisini Aç düğmesini kullanabilirsiniz. "
                "İndirme tamamlandığında ISO, ayarınıza göre otomatik oluşturulur ya da İndirme Yöneticisi'ndeki ISO Oluşturma bölümünden başlatılır."
            )
            self._auto_done(True, f"{len(job_ids)} UUP dosyası indirme kuyruğuna eklendi. İndirme bitince ISO otomatik oluşturulur ve ISO Merkezi'nde görünür.")
        self.prepare_button.setEnabled(True)
        self.find_button.setEnabled(bool(self.current_build))

    @staticmethod
    def space_needed(total_size: int) -> int:
        """İndirme (UUP paketleri) + ISO dönüştürme çalışma alanı; ikisi aynı diskte olduğu varsayılır."""
        from services.iso_build_manager import IsoBuildWorker
        return int(total_size) + IsoBuildWorker.required_space_for_size(int(total_size))

    def _space_preflight(self, base_folder: Path, total_size: int) -> bool:
        """İndirme başlamadan önce yer kontrolü: yetmiyorsa kullanıcıya sorar. False = vazgeçildi."""
        if total_size <= 0:
            return True
        import shutil
        try:
            free = shutil.disk_usage(base_folder).free
        except OSError:
            return True
        need = self.space_needed(total_size)
        if free >= need:
            return True
        gib = 1024 ** 3
        return bool(ask_confirmation(
            self, "Disk alanı yetmeyebilir",
            f"Bu ISO için indirme ve dönüştürme birlikte yaklaşık {need / gib:.0f} GB yer ister; seçtiğiniz diskte "
            f"{free / gib:.0f} GB boş alan var. İndirme bitince ISO oluşturma yer yetmediği için durabilir.\n\n"
            "Yine de devam etmek ister misiniz? Başka bir disk seçmek için İptal'e basıp işlemi yeniden başlatın.",
            heading="Seçilen diskte yeterli yer yok", confirm_text="Yine de Devam Et", cancel_text="İptal",
        ))

    def _on_uup_prepare_failed(self, message):
        self.status.setText("UUP indirme bağlantıları alınamadı.")
        self.prepare_button.setEnabled(True)
        self.find_button.setEnabled(bool(self.current_build))
        if self._auto_pending:
            self._auto_done(False, f"UUP indirme bağlantıları alınamadı: {message}")
            return
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
