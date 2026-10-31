from __future__ import annotations

from pathlib import Path

import tempfile

from PySide6.QtCore import QObject, QRectF, QSize, QThread, Signal, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel,
    QLineEdit, QPushButton, QFileDialog, QCheckBox, QProgressBar,
    QPlainTextEdit, QSizePolicy, QScrollArea,
)

from ui import icons
from ui.theme import raw_qcolor

from services.usb_media_service import InstallCustomization, UsbDrive, UsbMediaService, normalize_sha256
from ui.widgets.modern_combo_box import ModernComboBox
from ui.widgets.message_dialog import ask_confirmation, show_error, show_information, show_success


class UsbCreateWorker(QObject):
    stage_changed = Signal(int, str)
    log_changed = Signal(str)
    progress_changed = Signal(int, str)
    completed = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        iso_path: Path,
        drive: UsbDrive,
        partition_scheme: str,
        file_system: str,
        label: str,
        bypass_hardware_checks: bool,
        customization: InstallCustomization | None = None,
        verify_sha256: bool = False,
        expected_sha256: str = "",
    ):
        super().__init__()
        self.iso_path = iso_path
        self.drive = drive
        self.partition_scheme = partition_scheme
        self.file_system = file_system
        self.label = label
        self.bypass_hardware_checks = bypass_hardware_checks
        self.customization = customization
        self.verify_sha256 = verify_sha256
        self.expected_sha256 = expected_sha256
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            target = UsbMediaService.create_media(
                self.iso_path,
                self.drive,
                self.partition_scheme,
                self.file_system,
                self.label,
                self.bypass_hardware_checks,
                customization=self.customization,
                verify_sha256=self.verify_sha256,
                expected_sha256=self.expected_sha256,
                on_stage=lambda stage, text: self.stage_changed.emit(stage, text),
                on_log=self.log_changed.emit,
                on_progress=lambda percent, text: self.progress_changed.emit(percent, text),
                cancelled=lambda: self._cancelled,
            )
            self.completed.emit(target)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class StageChip(QFrame):
    def __init__(self, number: int, text: str, description: str = ""):
        super().__init__()
        self.setObjectName("usbStageChip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)
        self.number = QLabel(str(number))
        self.number.setObjectName("usbStageNumber")
        self.number.setAlignment(Qt.AlignCenter)
        self.number.setFixedSize(32, 32)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.text = QLabel(text)
        self.text.setObjectName("usbStageText")
        self.text.setWordWrap(True)
        self.desc = QLabel(description)
        self.desc.setObjectName("usbStageDesc")
        self.desc.setWordWrap(True)
        if not description:
            self.desc.hide()  # bilerek hide(): üst öğesi yokken setVisible(True) ayrı pencere açar
        col.addWidget(self.text)
        col.addWidget(self.desc)
        layout.addWidget(self.number, 0, Qt.AlignVCenter)
        layout.addLayout(col, 1)

    def set_state(self, state: str):
        self.setProperty("state", state)
        for w in (self, self.number, self.text, self.desc):
            w.style().unpolish(w)
            w.style().polish(w)
        self.update()


class _StatusLabel(QLabel):
    """Durum metni değişince başlığı (Hazır / Durum) da günceller; sadece görünüm."""
    IDLE = "ISO ve USB seçimini tamamlayın."

    def __init__(self, text, title_label):
        super().__init__(text)
        self._title_label = title_label

    def setText(self, text):
        super().setText(text)
        try:
            self._title_label.setText("Hazır" if text == self.IDLE else "Durum")
        except RuntimeError:
            pass


class _LabeledProgress(QProgressBar):
    """İlerleme çubuğu: metin çubuğun içine sıkışmaz; yüzde ve aşama bilgisi çubuğun yanındaki/altındaki
    okunaklı etiketlerde gösterilir. setValue/setFormat/setVisible çağrıları aynen çalışır."""

    def __init__(self, percent_label: QLabel, detail_label: QLabel, parent=None):
        super().__init__(parent)
        self._percent_label = percent_label
        self._detail_label = detail_label
        self.setTextVisible(False)

    def setValue(self, value: int) -> None:
        super().setValue(value)
        self._percent_label.setText(f"%{int(value)}")

    def setFormat(self, text: str) -> None:
        super().setFormat(text)
        self._detail_label.setText(text)

    def setVisible(self, visible: bool) -> None:
        super().setVisible(visible)
        self._percent_label.setVisible(visible)
        self._detail_label.setVisible(visible)


class _UsbScanWorker(QThread):
    """USB disk taramasını (PowerShell, 1-3 sn) arayüzü dondurmadan arka planda yapar."""

    done = Signal(object)

    def run(self):
        try:
            self.done.emit(UsbMediaService.list_usb_drives())
        except Exception:
            self.done.emit([])


class UsbInstallPage(QWidget):
    STAGES = [
        "Doğrulama",
        "Bölümlendirme",
        "Windows Dosyaları",
        "Önyükleme Yapısı",
        "Kurulum Seçenekleri",
        "Doğrulama",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drives: list[UsbDrive] = []
        self._thread: QThread | None = None
        self._worker: UsbCreateWorker | None = None
        self._active_stage = 0
        self._build_ui()
        self.refresh_usb_drives()

    @staticmethod
    def _toggle_images():
        """Anahtar (switch) görünümü için geçici PNG'ler üretir; sadece görünüm."""
        out = {}
        base = Path(tempfile.gettempdir())
        for name, on in (("off", False), ("on", True)):
            pm = QPixmap(88, 48)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(Qt.NoPen)
            p.setBrush(raw_qcolor()("#1768E0") if on else QColor("#D5DEEA"))
            p.drawRoundedRect(QRectF(0, 0, 88, 48), 24, 24)
            p.setBrush(raw_qcolor()("#FFFFFF"))
            p.drawEllipse(QRectF(48 if on else 6, 6, 36, 36))
            p.end()
            path = base / f"wubc_usb_toggle_{name}.png"
            pm.save(str(path), "PNG")
            out[name] = path.as_posix()
        return out

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("usbCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        return card, lay

    def _step_head(self, number: int, title: str, note: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        badge = QLabel(str(number))
        badge.setObjectName("usbStepBadge")
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignCenter)
        row.addWidget(badge, 0, Qt.AlignTop)
        row.addWidget(self._section_title(title, note), 1)
        return box

    def _hint_row(self, name: str, color: str, label: QLabel, object_name: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(name, color, 20, stroke=1.9))
        ic.setFixedSize(22, 22)
        row.addWidget(ic, 0, Qt.AlignTop)
        row.addWidget(label, 1)
        return frame

    @staticmethod
    def _btn_icon(name: str, color: str, disabled: str = "#9AA8BF") -> QIcon:
        icon = QIcon()
        icon.addPixmap(icons.pixmap(name, color, 36, stroke=2.0), QIcon.Normal)
        icon.addPixmap(icons.pixmap(name, disabled, 36, stroke=2.0), QIcon.Disabled)
        return icon

    def _build_ui(self):
        self.setObjectName("usbPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("usbScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("usbBody")
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ── Başlık ──
        head = QHBoxLayout()
        head.setSpacing(14)
        head_icon = QLabel()
        head_icon.setObjectName("usbHeadIcon")
        head_icon.setFixedSize(64, 64)
        head_icon.setAlignment(Qt.AlignCenter)
        head_icon.setPixmap(icons.pixmap("usb", "#1768E0", 34, stroke=1.9))
        head.addWidget(head_icon, 0, Qt.AlignTop)
        head_text = QVBoxLayout()
        head_text.setSpacing(2)
        title = QLabel("USB Kurulum Aracı")
        title.setObjectName("usbTitle")
        subtitle = QLabel("Windows ISO dosyanızı önyüklenebilir USB kurulum belleğine dönüştürün.")
        subtitle.setObjectName("usbSubtitle")
        subtitle.setWordWrap(True)
        head_text.addWidget(title)
        head_text.addWidget(subtitle)
        head.addLayout(head_text, 1)
        badge_frame = QFrame()
        badge_frame.setObjectName("usbBadgeFrame")
        badge_row = QHBoxLayout(badge_frame)
        badge_row.setContentsMargins(12, 6, 14, 6)
        badge_row.setSpacing(8)
        badge_icon = QLabel()
        badge_icon.setPixmap(icons.pixmap("check-circle", "#1C8B56", 18, stroke=2.0))
        badge_icon.setFixedSize(20, 20)
        badge_row.addWidget(badge_icon)
        self.platform_badge = QLabel("Windows hazır" if UsbMediaService.is_supported_platform() else "Yalnızca Windows")
        self.platform_badge.setObjectName("usbBadge")
        badge_row.addWidget(self.platform_badge)
        head.addWidget(badge_frame, 0, Qt.AlignTop)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(16)

        # ── Sol sütun: 4 adım kartı ──
        left_col = QVBoxLayout()
        left_col.setSpacing(14)

        # 1. ISO
        c1, l1 = self._card()
        l1.addWidget(self._step_head(1, "ISO Kaynağı", "Önyüklenebilir USB oluşturmak için geçerli bir Windows ISO dosyası seçin."))
        iso_row = QHBoxLayout()
        iso_row.setSpacing(12)
        self.iso_path = QLineEdit()
        self.iso_path.setPlaceholderText("Bir Windows ISO dosyası seçin...")
        self.iso_path.setReadOnly(True)
        self.iso_path.addAction(QIcon(icons.pixmap("folder", "#5F7090", 36, stroke=1.9)), QLineEdit.LeadingPosition)
        self.choose_iso_button = QPushButton("ISO Seç")
        self.choose_iso_button.setObjectName("usbPrimary")
        self.choose_iso_button.setIcon(self._btn_icon("folder", "#FFFFFF"))
        self.choose_iso_button.setIconSize(QSize(18, 18))
        self.choose_iso_button.setCursor(Qt.PointingHandCursor)
        self.choose_iso_button.clicked.connect(self.choose_iso)
        iso_row.addWidget(self.iso_path, 1)
        iso_row.addWidget(self.choose_iso_button)
        l1.addLayout(iso_row)
        self.iso_info = QLabel("ISO seçilmedi.")
        self.iso_info.setObjectName("usbHintBox")
        self.iso_info.setWordWrap(True)
        l1.addWidget(self._hint_row("info-fill", "#1768E0", self.iso_info, "usbHintFrame"))
        self.verify_sha256 = QCheckBox("ISO'nun SHA-256 değerini doğrula")
        self.verify_sha256.setObjectName("usbMainCheck")
        self.verify_sha256.setCursor(Qt.PointingHandCursor)
        self.verify_sha256.setToolTip("ISO dosyasının SHA-256 değeri USB'ye dokunulmadan önce hesaplanır. İsterseniz kaynaktan aldığınız değerle karşılaştırılır; eşleşmezse USB silinmez.")
        l1.addWidget(self.verify_sha256)
        self.expected_sha256 = QLineEdit()
        self.expected_sha256.setPlaceholderText("Beklenen SHA-256 (isteğe bağlı) — kaynaktan kopyalayıp yapıştırın")
        self.expected_sha256.setEnabled(False)
        self.verify_sha256.toggled.connect(self.expected_sha256.setEnabled)
        l1.addWidget(self.expected_sha256)
        left_col.addWidget(c1)

        # 2. USB
        c2, l2 = self._card()
        l2.addWidget(self._step_head(2, "Hedef USB", "Windows kurulum dosyalarını yazmak için bir USB bellek seçin."))
        usb_row = QHBoxLayout()
        usb_row.setSpacing(12)
        self.usb_combo = ModernComboBox()
        self.usb_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_button = QPushButton("Yenile")
        self.refresh_button.setObjectName("usbOutline")
        self.refresh_button.setIcon(self._btn_icon("refresh", "#1768E0"))
        self.refresh_button.setIconSize(QSize(18, 18))
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_usb_drives)
        usb_row.addWidget(self.usb_combo, 1)
        usb_row.addWidget(self.refresh_button)
        l2.addLayout(usb_row)
        self.usb_warning = QLabel("USB bellekteki tüm veriler işlem başlamadan önce silinir.")
        self.usb_warning.setObjectName("usbWarningBox")
        self.usb_warning.setWordWrap(True)
        l2.addWidget(self._hint_row("warning", "#E8A100", self.usb_warning, "usbWarnFrame"))
        left_col.addWidget(c2)

        # 3. Önyükleme yapısı
        c3, l3 = self._card()
        l3.addWidget(self._step_head(3, "Önyükleme Yapısı", "Kullanılacak bölüm düzeni ve dosya sistemi yapılandırmalarını seçin."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        grid.addWidget(self._field_label("Bölüm Düzeni"), 0, 0)
        grid.addWidget(self._field_label("Dosya Sistemi"), 0, 1)
        self.scheme_combo = ModernComboBox()
        self.scheme_combo.addItems(["GPT / UEFI", "MBR / BIOS-UEFI CSM"])
        self.fs_combo = ModernComboBox()
        self.fs_combo.addItems(["Otomatik", "FAT32", "NTFS"])
        self.scheme_combo.currentIndexChanged.connect(self._update_profile_hint)
        self.fs_combo.currentIndexChanged.connect(self._update_profile_hint)
        grid.addWidget(self.scheme_combo, 1, 0)
        grid.addWidget(self.fs_combo, 1, 1)
        grid.addWidget(self._field_label("USB etiketi"), 2, 0, 1, 2)
        self.volume_label = QLineEdit("WINDOWS_USB")
        self.volume_label.setMaxLength(32)
        self.volume_label.addAction(QIcon(icons.pixmap("list", "#5F7090", 36, stroke=1.9)), QLineEdit.LeadingPosition)
        grid.addWidget(self.volume_label, 3, 0, 1, 2)
        l3.addLayout(grid)
        self.profile_hint = QLabel("")
        self.profile_hint.setObjectName("usbInfoBox")
        self.profile_hint.setWordWrap(True)
        l3.addWidget(self._hint_row("info-outline", "#1768E0", self.profile_hint, "usbHintFrame"))
        self._update_profile_hint()
        left_col.addWidget(c3)

        # 4. Windows 11 uyumluluğu
        c4, l4 = self._card()
        l4.addWidget(self._step_head(4, "Windows 11 Uyumluluğu", "Windows 11 donanım gereksinimlerini kontrol etmek için bu seçeneği kullanabilirsiniz."))
        sw_row = QHBoxLayout()
        sw_row.setSpacing(8)
        self.bypass_checks = QCheckBox("Windows 11 donanım gereksinimlerini kaldır")
        self.bypass_checks.setObjectName("usbMainCheck")
        self.bypass_checks.setCursor(Qt.PointingHandCursor)
        self.bypass_checks.setToolTip("TPM 2.0, Secure Boot ve minimum RAM denetimlerini Windows Kurulumu sırasında atlamaya çalışır.")
        sw_row.addWidget(self.bypass_checks)
        sw_info = QLabel()
        sw_info.setPixmap(icons.pixmap("info-outline", "#5F7090", 18, stroke=1.9))
        sw_info.setToolTip(self.bypass_checks.toolTip())
        sw_row.addWidget(sw_info)
        sw_row.addStretch(1)
        l4.addLayout(sw_row)
        bypass_note = QLabel("TPM 2.0, Secure Boot ve minimum RAM kontrolleri yapılmaz. Bu seçenek yalnızca ileri düzey kullanıcılar içindir.")
        bypass_note.setObjectName("usbSubtle")
        bypass_note.setWordWrap(True)
        bypass_note.setContentsMargins(56, 0, 0, 0)
        l4.addWidget(bypass_note)
        left_col.addWidget(c4)

        # 5. Kurulum özelleştirme
        c5, l5 = self._card()
        l5.addWidget(self._step_head(5, "Kurulum Özelleştirme", "Windows Kurulumu sırasında sorulan bazı adımları önceden yanıtlayın (isteğe bağlı)."))
        self.use_local_account = QCheckBox("Microsoft hesabı yerine yerel hesap oluştur")
        self.use_local_account.setObjectName("usbMainCheck")
        self.use_local_account.setCursor(Qt.PointingHandCursor)
        self.use_local_account.setToolTip("Kurulumda çevrimiçi hesap ekranı gösterilmez; aşağıdaki adla parolasız bir yönetici hesabı açılır. Parolayı ilk girişte Ayarlar'dan belirleyebilirsiniz.")
        l5.addWidget(self.use_local_account)
        self.local_account_name = QLineEdit()
        self.local_account_name.setPlaceholderText("Hesap adı (en çok 20 karakter)")
        self.local_account_name.setMaxLength(20)
        self.local_account_name.setEnabled(False)
        self.use_local_account.toggled.connect(self.local_account_name.setEnabled)
        l5.addWidget(self.local_account_name)
        self.use_computer_name = QCheckBox("Bilgisayar adını ayarla")
        self.use_computer_name.setObjectName("usbMainCheck")
        self.use_computer_name.setCursor(Qt.PointingHandCursor)
        l5.addWidget(self.use_computer_name)
        self.computer_name = QLineEdit()
        self.computer_name.setPlaceholderText("Bilgisayar adı (harf, rakam, tire; en çok 15 karakter)")
        self.computer_name.setMaxLength(15)
        self.computer_name.setEnabled(False)
        self.use_computer_name.toggled.connect(self.computer_name.setEnabled)
        l5.addWidget(self.computer_name)
        self.skip_privacy = QCheckBox("Gizlilik ve ekspres ayar sayfalarını atla")
        self.skip_privacy.setObjectName("usbMainCheck")
        self.skip_privacy.setCursor(Qt.PointingHandCursor)
        self.skip_privacy.setToolTip("İlk açılışta çıkan gizlilik/ekspres ayar sorularını göstermez. Lisans sözleşmesi sayfası gizlenmez.")
        l5.addWidget(self.skip_privacy)
        custom_note = QLabel("Bu seçenekler USB'ye bir autounattend.xml dosyası olarak yazılır. Disk seçimi gibi sorulara dokunulmaz.")
        custom_note.setObjectName("usbSubtle")
        custom_note.setWordWrap(True)
        l5.addWidget(custom_note)
        left_col.addWidget(c5)
        left_col.addStretch(1)

        # ── Sağ sütun: İşlem durumu ──
        right, right_layout = self._card()
        right.setMinimumWidth(420)
        right_layout.setSpacing(12)

        rhead = QHBoxLayout()
        rhead.setSpacing(12)
        rtile = QLabel()
        rtile.setObjectName("usbRoundTile")
        rtile.setFixedSize(44, 44)
        rtile.setAlignment(Qt.AlignCenter)
        rtile.setPixmap(icons.pixmap("gear", "#1768E0", 26, stroke=1.9))
        rhead.addWidget(rtile, 0, Qt.AlignTop)
        rhead.addWidget(self._section_title("İşlem Durumu", "Seçeneklerinize göre adımlar sırasıyla gerçekleştirilecek."), 1)
        right_layout.addLayout(rhead)

        stage_descs = [
            ("Doğrulama", "ISO (ve seçiliyse SHA-256) ve USB kontrol edilecek."),
            ("Bölümlendirme", "Disk yapısı hazırlanacak."),
            ("Windows Dosyaları", "Kurulum dosyaları kopyalanacak."),
            ("Önyükleme Yapısı", "Önyükleme dosyaları yapılandırılacak."),
            ("Kurulum Seçenekleri", "Uyumluluk ve özelleştirme dosyası yazılacak."),
            ("Son Kontrol", "İşlem tamamlanmadan önce son kontrol yapılacak."),
        ]
        stages_col = QVBoxLayout()
        stages_col.setSpacing(8)
        self.stage_chips: list[StageChip] = []
        for idx, (text, desc) in enumerate(stage_descs, start=1):
            chip = StageChip(idx, text, desc)
            chip.set_state("waiting")
            self.stage_chips.append(chip)
            stages_col.addWidget(chip)
        right_layout.addLayout(stages_col)

        # Durum kartı (Hazır) + ilerleme çubuğu
        status_card = QFrame()
        status_card.setObjectName("usbStatusCard")
        sc = QHBoxLayout(status_card)
        sc.setContentsMargins(16, 12, 16, 12)
        sc.setSpacing(12)
        sc_icon = QLabel()
        sc_icon.setObjectName("usbStatusIcon")
        sc_icon.setFixedSize(34, 34)
        sc_icon.setAlignment(Qt.AlignCenter)
        sc_icon.setPixmap(icons.pixmap("info-fill", "#FFFFFF", 22, stroke=1.9))
        sc.addWidget(sc_icon, 0, Qt.AlignTop)
        sc_col = QVBoxLayout()
        sc_col.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.status_title = QLabel("Hazır")
        self.status_title.setObjectName("usbStatusTitle")
        self.progress_percent = QLabel("%0")
        self.progress_percent.setObjectName("usbProgressPercent")
        self.progress_percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.progress_detail = QLabel("")
        self.progress_detail.setObjectName("usbProgressDetail")
        self.progress_detail.setWordWrap(True)
        title_row.addWidget(self.status_title, 1)
        title_row.addWidget(self.progress_percent, 0)
        self.status = _StatusLabel("ISO ve USB seçimini tamamlayın.", self.status_title)
        self.status.setObjectName("usbStatus")
        self.status.setWordWrap(True)
        self.progress = _LabeledProgress(self.progress_percent, self.progress_detail)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Hazır")
        self.progress.setVisible(False)
        sc_col.addLayout(title_row)
        sc_col.addWidget(self.status)
        sc_col.addWidget(self.progress)
        sc_col.addWidget(self.progress_detail)
        sc_col.addStretch(1)
        sc.addLayout(sc_col, 1)
        status_card.setMinimumHeight(170)
        right_layout.addWidget(status_card, 0)

        # Günlük kartı
        log_card = QFrame()
        log_card.setObjectName("usbLogCard")
        lc = QVBoxLayout(log_card)
        lc.setContentsMargins(14, 12, 14, 14)
        lc.setSpacing(8)
        log_head = QHBoxLayout()
        log_icon = QLabel()
        log_icon.setPixmap(icons.pixmap("doc", "#DDE9F7", 18, stroke=1.9))
        log_icon.setFixedSize(20, 20)
        log_head.addWidget(log_icon)
        log_title = QLabel("İşlem Günlüğü")
        log_title.setObjectName("usbLogTitle")
        log_head.addWidget(log_title)
        log_head.addStretch(1)
        self.clear_log_button = QPushButton("Temizle")
        self.clear_log_button.setObjectName("usbLogClear")
        self.clear_log_button.setIcon(self._btn_icon("trash", "#8EC1FF"))
        self.clear_log_button.setIconSize(QSize(14, 14))
        self.clear_log_button.setCursor(Qt.PointingHandCursor)
        log_head.addWidget(self.clear_log_button)
        lc.addLayout(log_head)
        self.log = QPlainTextEdit()
        self.log.setObjectName("usbLog")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("İşlem günlüğü seçiminizden sonra burada görüntülenir.")
        self.log.setMinimumHeight(70)
        lc.addWidget(self.log, 1)
        self.clear_log_button.clicked.connect(self.log.clear)
        log_card.setMinimumHeight(130)
        right_layout.addWidget(log_card, 1)   # günlük kalan boşluğu doldurur; düğmelere kadar uzanır

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.cancel_button = QPushButton("İşlemi Durdur")
        self.cancel_button.setObjectName("usbStop")
        self.cancel_button.setIcon(self._btn_icon("x", "#D93C3C", "#E6A9A9"))
        self.cancel_button.setIconSize(QSize(18, 18))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_creation)
        self.start_button = QPushButton("Önyüklenebilir USB Oluştur")
        self.start_button.setObjectName("usbStart")
        self.start_button.setIcon(self._btn_icon("usb", "#FFFFFF", "#FFFFFF"))
        self.start_button.setIconSize(QSize(18, 18))
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.clicked.connect(self.start_creation)
        buttons.addWidget(self.cancel_button, 2)
        buttons.addWidget(self.start_button, 3)
        right_layout.addLayout(buttons)

        body.addLayout(left_col, 3)
        body.addWidget(right, 2)
        root.addLayout(body, 1)

        tg = self._toggle_images()
        self.setStyleSheet(r'''
            QWidget#usbPage, QWidget#usbBody, QScrollArea#usbScroll { background: #F3F7FC; }
            QLabel { background: transparent; }
            QLabel#usbTitle { font-size: 30px; font-weight: 700; color: #0A1F44; }
            QLabel#usbSubtitle { color: #5F7090; font-size: 14px; }
            QLabel#usbHeadIcon { background: #E3EEFC; border-radius: 32px; }
            QLabel#usbRoundTile { background: #E3EEFC; border-radius: 22px; }
            QFrame#usbBadgeFrame { background: #EAF8F0; border: 1px solid #CDEDDD; border-radius: 20px; }
            QLabel#usbBadge { color: #176B42; font-size: 13px; font-weight: 700; }
            QFrame#usbCard { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px; }
            QLabel#usbStepBadge { background: #1768E0; color: #FFFFFF; border-radius: 15px; font-size: 14px; font-weight: 700; }
            QLabel#usbSectionTitle { color: #0A1F44; font-size: 17px; font-weight: 700; }
            QLabel#usbSectionNote { color: #5F7090; font-size: 12px; }
            QLabel#usbFieldLabel { color: #3A4D70; font-size: 12px; font-weight: 600; }
            QLabel#usbSubtle { color: #6B7C99; font-size: 12px; }
            QLineEdit {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 10px;
                padding: 0 12px; font-size: 13px; color: #14213D; min-height: 42px; max-height: 42px;
            }
            QLineEdit:focus { border-color: #1768E0; }
            QComboBox#modernComboBox {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 10px; padding: 0 28px 0 12px;
                font-size: 13px; color: #14213D; min-height: 40px; max-height: 40px;
            }
            QFrame#usbHintFrame { background: #EEF4FD; border: 1px solid #DDE8F7; border-radius: 10px; }
            QFrame#usbWarnFrame { background: #FFF6E3; border: 1px solid #F4DFA0; border-radius: 10px; }
            QLabel#usbHintBox, QLabel#usbInfoBox { color: #3A4D70; font-size: 12px; background: transparent; border: none; padding: 0; }
            QLabel#usbWarningBox { color: #8A5B00; font-size: 12px; background: transparent; border: none; padding: 0; }
            QPushButton#usbPrimary {
                background: #1768E0; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 0 22px; font-size: 13px; font-weight: 700; min-height: 42px; max-height: 42px;
            }
            QPushButton#usbPrimary:hover { background: #135BC4; }
            QPushButton#usbPrimary:disabled { background: #A9C4EE; }
            QPushButton#usbOutline {
                background: #FFFFFF; color: #1768E0; border: 1px solid #CBD9EC; border-radius: 10px;
                padding: 0 22px; font-size: 13px; font-weight: 700; min-height: 40px; max-height: 40px;
            }
            QPushButton#usbOutline:hover { background: #F1F6FD; border-color: #9DB9E6; }
            QPushButton#usbOutline:disabled { color: #9AA8BF; background: #F4F7FB; border: 1px solid #E5ECF5; }
            QCheckBox#usbMainCheck { color: #0A1F44; font-size: 13px; font-weight: 600; spacing: 12px; }
            QCheckBox#usbMainCheck::indicator { width: 44px; height: 24px; image: url(__OFF__); }
            QCheckBox#usbMainCheck::indicator:checked { image: url(__ON__); }
            QFrame#usbStageChip { background: #FFFFFF; border: 1px solid #E3EAF4; border-radius: 12px; }
            QFrame#usbStageChip[state="active"] { background: #EAF3FF; border-color: #78A7E8; }
            QFrame#usbStageChip[state="done"] { background: #EAF8F0; border-color: #A7DFC1; }
            QFrame#usbStageChip[state="error"] { background: #FFF0F0; border-color: #F1B0B0; }
            QLabel#usbStageNumber { background: #DCE6F4; color: #3A4D70; border-radius: 16px; font-size: 13px; font-weight: 700; }
            QFrame#usbStageChip[state="active"] QLabel#usbStageNumber { background: #1768E0; color: white; }
            QFrame#usbStageChip[state="done"] QLabel#usbStageNumber { background: #1C8B56; color: white; }
            QFrame#usbStageChip[state="error"] QLabel#usbStageNumber { background: #D93C3C; color: white; }
            QLabel#usbStageText { color: #0A1F44; font-size: 14px; font-weight: 600; }
            QLabel#usbStageDesc { color: #6B7C99; font-size: 12px; font-style: italic; }
            QFrame#usbStatusCard { background: #EAF2FE; border: 1px solid #D5E3F8; border-radius: 12px; }
            QLabel#usbStatusIcon { background: #1768E0; border-radius: 17px; }
            QLabel#usbStatusTitle { color: #0A1F44; font-size: 16px; font-weight: 700; }
            QLabel#usbStatus { color: #1F3354; font-size: 13px; background: transparent; border: none; padding: 0; }
            QLabel#usbProgressPercent { color: #1768E0; font-size: 22px; font-weight: 800; background: transparent; }
            QLabel#usbProgressDetail { color: #0A1F44; font-size: 13px; font-weight: 600; background: transparent; }
            QProgressBar {
                border: none; border-radius: 9px; background: #C9DBF5;
                min-height: 18px; max-height: 18px;
            }
            QProgressBar::chunk { background: #1768E0; border-radius: 9px; }
            QFrame#usbLogCard { background: #0C1A33; border: 1px solid #1E3558; border-radius: 12px; }
            QLabel#usbLogTitle { color: #E8F0FB; font-size: 12px; font-weight: 700; }
            QPushButton#usbLogClear {
                background: transparent; color: #8EC1FF; border: 1px solid #2D5BA0; border-radius: 8px;
                padding: 0 10px; font-size: 11px; font-weight: 600; min-height: 26px; max-height: 26px;
            }
            QPushButton#usbLogClear:hover { background: #14284A; }
            QPlainTextEdit#usbLog {
                background: transparent; color: #DDE9F7; border: none;
                font-family: Consolas, monospace; font-size: 11px;
            }
            QPushButton#usbStop {
                background: #FFF4F4; color: #D93C3C; border: 1px solid #F0C4C4; border-radius: 10px;
                font-size: 13px; font-weight: 700; min-height: 44px; max-height: 44px;
            }
            QPushButton#usbStop:hover { background: #FFE9E9; }
            QPushButton#usbStop:disabled { color: #E6A9A9; background: #FFF6F6; border: 1px solid #F6DADA; }
            QPushButton#usbStart {
                background: #1768E0; color: #FFFFFF; border: none; border-radius: 10px;
                font-size: 13px; font-weight: 700; min-height: 44px; max-height: 44px;
            }
            QPushButton#usbStart:hover { background: #135BC4; }
            QPushButton#usbStart:disabled { background: #A9C4EE; }
        '''.replace("__OFF__", tg["off"]).replace("__ON__", tg["on"]))

    def _section_title(self, title: str, note: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("usbSectionTitle")
        note_label = QLabel(note)
        note_label.setObjectName("usbSectionNote")
        note_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(note_label)
        return box

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("usbFieldLabel")
        return label

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#E3EAF3;")
        return line

    def _combo_value(self, combo: ModernComboBox) -> str:
        text = combo.currentText()
        return text.split(": ", 1)[1] if ": " in text else text

    def choose_iso(self):
        path, _ = QFileDialog.getOpenFileName(self, "Windows ISO Dosyası Seç", "", "ISO Dosyaları (*.iso)")
        if path:
            self.set_iso_path(path)

    def set_iso_path(self, path) -> bool:
        """ISO'yu doğrulayıp seçer (ISO Merkezi'nden de çağrılır). Geçersizse hata gösterip False döner."""
        if self._thread is not None:
            show_information(self, "USB oluşturma sürüyor", "Bir USB oluşturma işlemi sürerken ISO değiştirilemez.")
            return False
        p = Path(path)
        try:
            UsbMediaService.validate_iso(p)
        except Exception as exc:
            show_error(self, "ISO seçilemedi", str(exc))
            return False
        self.iso_path.setText(str(p))
        size_gb = p.stat().st_size / (1024 ** 3)
        self.iso_info.setText(f"Seçili ISO: {p.name} • {size_gb:.2f} GB")
        stem = p.stem.upper().replace(" ", "_")
        self.volume_label.setText(stem[:32] or "WINDOWS_USB")
        return True

    def refresh_usb_drives(self):
        if not UsbMediaService.is_supported_platform():
            self._apply_usb_drives([])  # Windows dışında tarama anlık; arka plana gerek yok
            return
        scan = getattr(self, "_scan", None)
        if scan is not None and scan.isRunning():
            return
        self._drives = []  # tarama sürerken hiçbir disk seçilemesin
        self.usb_combo.blockSignals(True)
        self.usb_combo.clear()
        self.usb_combo.addItem("USB diskler aranıyor...")
        self.usb_combo.blockSignals(False)
        self.refresh_button.setEnabled(False)
        self._scan = _UsbScanWorker(self)
        self._scan.done.connect(self._apply_usb_drives)
        self._scan.start()

    def _apply_usb_drives(self, drives):
        self.refresh_button.setEnabled(True)
        self.usb_combo.blockSignals(True)
        self.usb_combo.clear()
        self._drives = list(drives or [])
        if self._drives:
            for drive in self._drives:
                self.usb_combo.addItem(drive.display_name, drive.disk_number)
            self.usb_warning.setText("USB bellekteki tüm veriler işlem başlamadan önce silinir. Sistem ve önyükleme diskleri listeden otomatik hariç tutulur.")
        else:
            self.usb_combo.addItem("Uygun USB disk seçin...")
            if UsbMediaService.is_supported_platform():
                self.usb_warning.setText("USB disk algılanmadı. Belleği bağlayıp Yenile düğmesine basın.")
            else:
                self.usb_warning.setText("USB oluşturma işlemi yalnızca Windows üzerinde çalışır.")
        self.usb_combo.blockSignals(False)

    def _selected_drive(self) -> UsbDrive | None:
        if not self._drives:
            return None
        index = self.usb_combo.currentIndex()
        if 0 <= index < len(self._drives):
            return self._drives[index]
        return None

    def _update_profile_hint(self):
        scheme_text = self._combo_value(self.scheme_combo)
        scheme = "GPT" if scheme_text.startswith("GPT") else "MBR"
        fs = self._combo_value(self.fs_combo)
        resolved = UsbMediaService.resolve_file_system(scheme, fs)
        if scheme == "GPT" and resolved == "FAT32":
            text = "Önerilen modern profil: GPT + UEFI + FAT32. ISO içindeki install.wim 4 GB'tan büyükse program otomatik olarak install.swm parçalarına böler."
        elif scheme == "MBR":
            text = "Uyumluluk profili: MBR + BIOS/UEFI-CSM. Otomatik seçimde NTFS kullanılır ve önyükleme kodu hazırlanır."
        else:
            text = "GPT + NTFS bazı saf UEFI sistemlerinde ek UEFI:NTFS sürücüsü olmadan önyüklenmeyebilir. GPT için Otomatik veya FAT32 önerilir."
        self.profile_hint.setText(text)

    def start_creation(self):
        if self._thread is not None:
            return
        iso_text = self.iso_path.text().strip()
        drive = self._selected_drive()
        if not iso_text:
            show_information(self, "ISO seçimi", "Önce kullanmak istediğiniz Windows ISO dosyasını seçin.")
            return
        if drive is None:
            show_information(self, "USB seçimi", "Önce hedef USB belleği seçin.")
            return

        scheme_text = self._combo_value(self.scheme_combo)
        scheme = "GPT" if scheme_text.startswith("GPT") else "MBR"
        fs = self._combo_value(self.fs_combo)
        label = self.volume_label.text().strip() or "WINDOWS_USB"
        resolved_fs = UsbMediaService.resolve_file_system(scheme, fs)
        effective_label = UsbMediaService.sanitize_volume_label(label, resolved_fs)

        customization = InstallCustomization(
            bypass_hardware=self.bypass_checks.isChecked(),
            local_account=self.local_account_name.text() if self.use_local_account.isChecked() else "",
            skip_privacy=self.skip_privacy.isChecked(),
            computer_name=self.computer_name.text() if self.use_computer_name.isChecked() else "",
        )
        if self.use_local_account.isChecked() and not customization.local_account.strip():
            show_information(self, "Yerel hesap", "Yerel hesap için bir ad yazın ya da seçeneği kapatın.")
            return
        if self.use_computer_name.isChecked() and not customization.computer_name.strip():
            show_information(self, "Bilgisayar adı", "Bilgisayar adı yazın ya da seçeneği kapatın.")
            return
        try:
            customization = InstallCustomization(
                customization.bypass_hardware, customization.local_account.strip(),
                customization.skip_privacy, customization.computer_name.strip(),
            )
            customization.validate()
        except ValueError as exc:
            show_information(self, "Kurulum özelleştirme", str(exc))
            return
        verify_hash = self.verify_sha256.isChecked()
        expected_hash = ""
        if verify_hash:
            try:
                expected_hash = normalize_sha256(self.expected_sha256.text())
            except ValueError as exc:
                show_information(self, "SHA-256 değeri", str(exc))
                return
        extra = ""
        if verify_hash:
            extra += "\nISO SHA-256 doğrulaması: " + ("beklenen değerle karşılaştırılacak" if expected_hash else "hesaplanıp gösterilecek")
        for line in customization.summary_lines():
            extra += "\nKurulum seçeneği: " + line

        warning = (
            f"Seçilen USB bellekteki TÜM veriler silinecek.\n\n"
            f"HEDEF DİSK: Disk {drive.disk_number} — {drive.friendly_name}\n"
            f"BOYUT: {drive.size_text}"
            + (f"    SÜRÜCÜ: {drive.drive_letter}:" if drive.drive_letter else "")
            + "\n\n"
            f"Bölüm düzeni: {scheme}\n"
            f"Dosya sistemi: {resolved_fs}\n"
            f"USB etiketi: {effective_label}\n"
            + (extra.lstrip("\n") + "\n" if extra else "")
            + "\nBu işlem geri alınamaz."
        )
        if not ask_confirmation(
            self,
            "USB belleği hazırlama",
            warning,
            heading=f"Silinecek disk: {drive.friendly_name} ({drive.size_text})",
            confirm_text="USB'yi Sil ve Devam Et",
            cancel_text="Vazgeç",
            destructive=True,
        ):
            return

        self._reset_progress()
        self.log.clear()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.choose_iso_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.usb_combo.setEnabled(False)
        self.scheme_combo.setEnabled(False)
        self.fs_combo.setEnabled(False)
        self._set_options_enabled(False)

        self._thread = QThread(self)
        self._worker = UsbCreateWorker(
            Path(iso_text),
            drive,
            scheme,
            fs,
            label,
            self.bypass_checks.isChecked(),
            customization,
            verify_hash,
            expected_hash,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.stage_changed.connect(self._on_stage)
        self._worker.log_changed.connect(self._append_log)
        self._worker.progress_changed.connect(self._on_copy_progress)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._cleanup_worker)
        self._thread.start()

    def _set_options_enabled(self, enabled: bool) -> None:
        """İşlem sürerken seçenek kutularını kilitler; bitince açık/kapalı durumlarına göre geri açar."""
        for box in (self.bypass_checks, self.verify_sha256, self.use_local_account,
                    self.use_computer_name, self.skip_privacy):
            box.setEnabled(enabled)
        self.expected_sha256.setEnabled(enabled and self.verify_sha256.isChecked())
        self.local_account_name.setEnabled(enabled and self.use_local_account.isChecked())
        self.computer_name.setEnabled(enabled and self.use_computer_name.isChecked())

    def cancel_creation(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("İptal isteği gönderildi. Aktif sistem işlemi tamamlandığında durdurulacak.")

    def _reset_progress(self):
        self.progress.setVisible(True)
        self._active_stage = 0
        self.progress.setValue(0)
        self.progress.setFormat("Hazırlanıyor")
        for chip in self.stage_chips:
            chip.set_state("waiting")

    STAGE_NAMES = ("Doğrulama", "Bölümlendirme", "Windows Dosyaları", "Önyükleme Yapısı", "Kurulum Seçenekleri", "Son Kontrol")

    def _stage_caption(self, stage: int) -> str:
        """Çubuğun altındaki kısa aşama başlığı; ayrıntı metni üstteki durum satırında zaten var, tekrarlanmaz."""
        index = max(1, min(len(self.STAGE_NAMES), stage))
        return f"Aşama {index}/{len(self.STAGE_NAMES)} — {self.STAGE_NAMES[index - 1]}"

    def _on_stage(self, stage: int, text: str):
        self._active_stage = stage
        for idx, chip in enumerate(self.stage_chips, start=1):
            if idx < stage:
                chip.set_state("done")
            elif idx == stage:
                chip.set_state("active")
            else:
                chip.set_state("waiting")
        percent = max(3, min(96, int((stage - 1) / len(self.STAGES) * 100) + 8))
        self.progress.setValue(percent)
        self.progress.setFormat(self._stage_caption(stage))
        self.status.setText(text)
        self._append_log(text)

    def _on_copy_progress(self, percent: int, text: str):
        if self._active_stage == 1:
            # SHA-256 hesabı: genel çubuğun ilk %3-%10 aralığına eşlenir
            self.progress.setValue(max(3, min(10, 3 + int(max(0, min(100, percent)) * 0.07))))
            self.progress.setFormat(self._stage_caption(1))
            self.status.setText(text)
            return
        if self._active_stage != 3:
            return
        # Stage 3 occupies the largest real workload. Map its live 0-100 progress
        # into the overall bar while keeping the six-stage visual flow intact.
        overall = 32 + int(max(0, min(100, percent)) * 0.48)
        self.progress.setValue(max(32, min(80, overall)))
        self.progress.setFormat(self._stage_caption(3))
        self.status.setText(text)

    def _append_log(self, text: str):
        if text:
            self.log.appendPlainText(text)

    def _on_completed(self, target: str):
        for chip in self.stage_chips:
            chip.set_state("done")
        self.progress.setValue(100)
        self.progress.setFormat("100% — Önyüklenebilir USB hazır ✓")
        self.status.setText(f"USB kurulum medyası başarıyla oluşturuldu: {target}")
        show_success(self, "USB hazır", f"Önyüklenebilir Windows kurulum medyası başarıyla oluşturuldu.\n\nHedef: {target}")

    def _on_failed(self, message: str):
        if 1 <= self._active_stage <= len(self.stage_chips):
            self.stage_chips[self._active_stage - 1].set_state("error")
        self.progress.setFormat("İşlem tamamlanamadı")
        self.status.setText(message)
        self._append_log("HATA: " + message)
        show_error(self, "USB oluşturma başarısız", message)

    def _cleanup_worker(self):
        thread = self._thread
        worker = self._worker
        self._thread = None
        self._worker = None
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.choose_iso_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.usb_combo.setEnabled(True)
        self.scheme_combo.setEnabled(True)
        self.fs_combo.setEnabled(True)
        self._set_options_enabled(True)
        if thread is not None:
            thread.quit()
            thread.wait(3000)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
