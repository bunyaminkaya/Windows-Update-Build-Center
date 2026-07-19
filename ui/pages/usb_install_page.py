from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel,
    QLineEdit, QPushButton, QFileDialog, QCheckBox, QProgressBar,
    QPlainTextEdit, QSizePolicy,
)

from services.usb_media_service import UsbDrive, UsbMediaService
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
    ):
        super().__init__()
        self.iso_path = iso_path
        self.drive = drive
        self.partition_scheme = partition_scheme
        self.file_system = file_system
        self.label = label
        self.bypass_hardware_checks = bypass_hardware_checks
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
    def __init__(self, number: int, text: str):
        super().__init__()
        self.setObjectName("usbStageChip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        self.number = QLabel(str(number))
        self.number.setObjectName("usbStageNumber")
        self.number.setAlignment(Qt.AlignCenter)
        self.number.setFixedSize(24, 24)
        self.text = QLabel(text)
        self.text.setObjectName("usbStageText")
        self.text.setWordWrap(True)
        layout.addWidget(self.number)
        layout.addWidget(self.text, 1)

    def set_state(self, state: str):
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class UsbInstallPage(QWidget):
    STAGES = [
        "Doğrulama",
        "Bölümlendirme",
        "Windows Dosyaları",
        "Önyükleme Yapısı",
        "Windows 11 Uyumluluğu",
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

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("usbHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(14)
        intro = QVBoxLayout()
        intro.setSpacing(4)
        title = QLabel("Windows ISO dosyanızı güvenli biçimde önyüklenebilir USB kurulum medyasına dönüştürün.")
        title.setObjectName("usbHeroTitle")
        title.setWordWrap(True)
        subtitle = QLabel("ISO seçin, yalnızca USB hedefini belirleyin ve uygun önyükleme profilini kullanın. Sistem diskleri hedef listesine alınmaz.")
        subtitle.setObjectName("usbHeroSubtitle")
        subtitle.setWordWrap(True)
        intro.addWidget(title)
        intro.addWidget(subtitle)
        hero_layout.addLayout(intro, 1)
        self.platform_badge = QLabel("Windows hazır" if UsbMediaService.is_supported_platform() else "Yalnızca Windows")
        self.platform_badge.setObjectName("usbBadge")
        hero_layout.addWidget(self.platform_badge, 0, Qt.AlignTop)
        root.addWidget(hero)

        body = QHBoxLayout()
        body.setSpacing(14)

        left = QFrame()
        left.setObjectName("usbCard")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(14)

        left_layout.addWidget(self._section_title("1. ISO Kaynağı", "İndirdiğiniz veya programın oluşturduğu Windows ISO dosyasını seçin."))
        iso_row = QHBoxLayout()
        self.iso_path = QLineEdit()
        self.iso_path.setPlaceholderText("Bir Windows ISO dosyası seçin...")
        self.iso_path.setReadOnly(True)
        self.choose_iso_button = QPushButton("ISO Seç")
        self.choose_iso_button.clicked.connect(self.choose_iso)
        iso_row.addWidget(self.iso_path, 1)
        iso_row.addWidget(self.choose_iso_button)
        left_layout.addLayout(iso_row)

        self.iso_info = QLabel("ISO seçilmedi.")
        self.iso_info.setObjectName("usbHintBox")
        self.iso_info.setWordWrap(True)
        left_layout.addWidget(self.iso_info)

        left_layout.addWidget(self._separator())
        left_layout.addWidget(self._section_title("2. Hedef USB", "Yalnızca Windows'un USB disk olarak algıladığı çıkarılabilir hedefler gösterilir."))
        usb_row = QHBoxLayout()
        self.usb_combo = ModernComboBox()
        self.usb_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_button = QPushButton("Yenile")
        self.refresh_button.clicked.connect(self.refresh_usb_drives)
        usb_row.addWidget(self.usb_combo, 1)
        usb_row.addWidget(self.refresh_button)
        left_layout.addLayout(usb_row)

        self.usb_warning = QLabel("USB bellekteki tüm veriler işlem başlamadan önce silinir.")
        self.usb_warning.setObjectName("usbWarningBox")
        self.usb_warning.setWordWrap(True)
        left_layout.addWidget(self.usb_warning)

        left_layout.addWidget(self._separator())
        left_layout.addWidget(self._section_title("3. Önyükleme Yapısı", "Modern sistemler için GPT / UEFI önerilir."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(self._field_label("Bölüm düzeni"), 0, 0)
        grid.addWidget(self._field_label("Dosya sistemi"), 0, 1)
        self.scheme_combo = ModernComboBox()
        self.scheme_combo.addItems(["Bölüm Düzeni: GPT / UEFI", "Bölüm Düzeni: MBR / BIOS-UEFI CSM"])
        self.fs_combo = ModernComboBox()
        self.fs_combo.addItems(["Dosya Sistemi: Otomatik", "Dosya Sistemi: FAT32", "Dosya Sistemi: NTFS"])
        self.scheme_combo.currentIndexChanged.connect(self._update_profile_hint)
        self.fs_combo.currentIndexChanged.connect(self._update_profile_hint)
        grid.addWidget(self.scheme_combo, 1, 0)
        grid.addWidget(self.fs_combo, 1, 1)
        grid.addWidget(self._field_label("USB etiketi"), 2, 0, 1, 2)
        self.volume_label = QLineEdit("WINDOWS_USB")
        self.volume_label.setMaxLength(32)
        grid.addWidget(self.volume_label, 3, 0, 1, 2)
        left_layout.addLayout(grid)

        self.profile_hint = QLabel("")
        self.profile_hint.setObjectName("usbInfoBox")
        self.profile_hint.setWordWrap(True)
        left_layout.addWidget(self.profile_hint)
        self._update_profile_hint()

        left_layout.addWidget(self._separator())
        left_layout.addWidget(self._section_title("4. Windows 11 Uyumluluğu", "Desteklenmeyen bilgisayarlar için isteğe bağlı kurulum profili."))
        self.bypass_checks = QCheckBox("Windows 11 donanım gereksinimlerini kaldır")
        self.bypass_checks.setObjectName("usbMainCheck")
        self.bypass_checks.setToolTip("TPM 2.0, Secure Boot ve minimum RAM denetimlerini Windows Kurulumu sırasında atlamaya çalışır.")
        left_layout.addWidget(self.bypass_checks)
        bypass_note = QLabel("Etkinleştirildiğinde TPM 2.0, Secure Boot ve minimum RAM kontrolleri için otomatik LabConfig profili USB belleğe eklenir.")
        bypass_note.setObjectName("usbSubtle")
        bypass_note.setWordWrap(True)
        left_layout.addWidget(bypass_note)
        left_layout.addStretch()

        right = QFrame()
        right.setObjectName("usbCard")
        right.setMinimumWidth(420)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        right_layout.addWidget(self._section_title("İşlem Durumu", "Rufus benzeri sade akış; gerekli teknik işlemler arka planda otomatik yürütülür."))

        stages_grid = QGridLayout()
        stages_grid.setSpacing(8)
        self.stage_chips: list[StageChip] = []
        for idx, text in enumerate(self.STAGES, start=1):
            chip = StageChip(idx, text)
            chip.set_state("waiting")
            self.stage_chips.append(chip)
            stages_grid.addWidget(chip, (idx - 1) // 2, (idx - 1) % 2)
        right_layout.addLayout(stages_grid)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Hazır")
        right_layout.addWidget(self.progress)

        self.status = QLabel("ISO ve USB seçimini tamamlayın.")
        self.status.setObjectName("usbStatus")
        self.status.setWordWrap(True)
        right_layout.addWidget(self.status)

        self.log = QPlainTextEdit()
        self.log.setObjectName("usbLog")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("İşlem günlüğü burada gösterilecek...")
        self.log.setMinimumHeight(150)
        right_layout.addWidget(self.log, 1)

        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("İşlemi Durdur")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_creation)
        self.start_button = QPushButton("Önyüklenebilir USB Oluştur")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_creation)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.start_button, 1)
        right_layout.addLayout(buttons)

        body.addWidget(left, 3)
        body.addWidget(right, 2)
        root.addLayout(body, 1)

        self.setStyleSheet(r'''
            QFrame#usbHero, QFrame#usbCard {
                background: #FFFFFF;
                border: 1px solid #D9E4F2;
                border-radius: 12px;
            }
            QFrame#usbHero { background: #F8FBFF; }
            QLabel#usbHeroTitle { color: #0B1736; font-size: 18px; font-weight: 700; }
            QLabel#usbHeroSubtitle, QLabel#usbSubtle { color: #6D7F96; font-size: 12px; }
            QLabel#usbBadge {
                color: #176B42; background: #EAF8F0; border: 1px solid #CDEDDD;
                border-radius: 10px; padding: 5px 10px; font-weight: 700;
            }
            QLabel#usbSectionTitle { color: #10264A; font-size: 15px; font-weight: 700; }
            QLabel#usbSectionNote, QLabel#usbFieldLabel { color: #74869C; font-size: 11px; }
            QLabel#usbHintBox, QLabel#usbInfoBox, QLabel#usbWarningBox, QLabel#usbStatus {
                border-radius: 8px; padding: 10px 12px;
            }
            QLabel#usbHintBox, QLabel#usbInfoBox, QLabel#usbStatus {
                color: #536781; background: #F4F8FD; border: 1px solid #D9E6F5;
            }
            QLabel#usbWarningBox {
                color: #8A5B00; background: #FFF9E8; border: 1px solid #F4DFA0;
            }
            QCheckBox#usbMainCheck { color: #10264A; font-weight: 700; spacing: 8px; }
            QFrame#usbStageChip {
                background: #F7F9FC; border: 1px solid #DCE5F0; border-radius: 9px;
            }
            QFrame#usbStageChip[state="active"] { background: #EAF3FF; border-color: #78A7E8; }
            QFrame#usbStageChip[state="done"] { background: #EAF8F0; border-color: #A7DFC1; }
            QFrame#usbStageChip[state="error"] { background: #FFF0F0; border-color: #F1B0B0; }
            QLabel#usbStageNumber {
                background: #E5ECF5; color: #51657D; border-radius: 12px; font-weight: 800;
            }
            QFrame#usbStageChip[state="active"] QLabel#usbStageNumber { background: #246BD8; color: white; }
            QFrame#usbStageChip[state="done"] QLabel#usbStageNumber { background: #1C8B56; color: white; }
            QLabel#usbStageText { color: #253957; font-size: 12px; font-weight: 600; }
            QProgressBar {
                border: 1px solid #D1DEEC; border-radius: 8px; background: #EAF0F7;
                min-height: 24px; text-align: center; color: #17345C; font-weight: 700;
            }
            QProgressBar::chunk { background: #246BD8; border-radius: 7px; }
            QPlainTextEdit#usbLog {
                background: #0F1D31; color: #DDE9F7; border: 1px solid #243D5B;
                border-radius: 8px; padding: 8px; font-family: Consolas; font-size: 11px;
            }
        ''')

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
        if not path:
            return
        p = Path(path)
        try:
            UsbMediaService.validate_iso(p)
        except Exception as exc:
            show_error(self, "ISO seçilemedi", str(exc))
            return
        self.iso_path.setText(str(p))
        size_gb = p.stat().st_size / (1024 ** 3)
        self.iso_info.setText(f"Seçili ISO: {p.name} • {size_gb:.2f} GB")
        stem = p.stem.upper().replace(" ", "_")
        self.volume_label.setText(stem[:32] or "WINDOWS_USB")

    def refresh_usb_drives(self):
        self.usb_combo.blockSignals(True)
        self.usb_combo.clear()
        self._drives = UsbMediaService.list_usb_drives()
        if self._drives:
            for drive in self._drives:
                self.usb_combo.addItem(f"Hedef USB: {drive.display_name}", drive.disk_number)
            self.usb_warning.setText("USB bellekteki tüm veriler işlem başlamadan önce silinir. Sistem ve önyükleme diskleri listeden otomatik hariç tutulur.")
        else:
            self.usb_combo.addItem("Hedef USB: Uygun USB disk bulunamadı")
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

        warning = (
            f"Seçilen USB bellekteki TÜM veriler silinecek.\n\n"
            f"Hedef: {drive.display_name}\n"
            f"Bölüm düzeni: {scheme}\n"
            f"Dosya sistemi: {resolved_fs}\n"
            f"USB etiketi: {effective_label}\n\n"
            "Bu işlem geri alınamaz."
        )
        if not ask_confirmation(
            self,
            "USB belleği hazırlama",
            warning,
            heading="Seçilen USB tamamen silinecek",
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

        self._thread = QThread(self)
        self._worker = UsbCreateWorker(
            Path(iso_text),
            drive,
            scheme,
            fs,
            label,
            self.bypass_checks.isChecked(),
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

    def cancel_creation(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("İptal isteği gönderildi. Aktif sistem işlemi tamamlandığında durdurulacak.")

    def _reset_progress(self):
        self._active_stage = 0
        self.progress.setValue(0)
        self.progress.setFormat("Hazırlanıyor")
        for chip in self.stage_chips:
            chip.set_state("waiting")

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
        self.progress.setFormat(f"Aşama {stage}/6 — {text}")
        self.status.setText(text)
        self._append_log(text)

    def _on_copy_progress(self, percent: int, text: str):
        if self._active_stage != 3:
            return
        # Stage 3 occupies the largest real workload. Map its live 0-100 progress
        # into the overall bar while keeping the six-stage visual flow intact.
        overall = 32 + int(max(0, min(100, percent)) * 0.48)
        self.progress.setValue(max(32, min(80, overall)))
        self.progress.setFormat(f"Windows Dosyaları • {text}")
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
        if thread is not None:
            thread.quit()
            thread.wait(3000)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
