from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QAbstractItemView,
    QLineEdit, QGridLayout
)

from services.build_tracker_service import BuildTrackerService
from services.download_manager import DownloadManager
from services.iso_version_service import latest_build_for_version, parse_version_query
from services.package_result import PackageResult
from services.system_profile import SystemProfileService
from services.iso_build_manager import IsoBuildManager
from services.settings_service import SettingsService
from services.usb_media_service import UsbMediaService
from ui import styles
from ui.widgets.empty_state import attach_empty_state
from ui.widgets.modern_combo_box import ModernComboBox
from ui.widgets.message_dialog import show_error, show_information, show_success, show_warning, ask_confirmation
from ui.pages.uup_center_page import EDITION_OPTIONS
from services.ms_iso_service import MicrosoftIsoService
from workers.ms_iso_worker import MsIsoLinkWorker


@dataclass
class IsoRecord:
    path: Path
    build: str = "—"
    architecture: str = "—"
    language: str = "—"
    edition: str = "—"
    product: str = "Windows"

    @property
    def size_text(self) -> str:
        try:
            size = self.path.stat().st_size
        except OSError:
            return "—"
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        unit = units[0]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                break
            value /= 1024
        return f"{value:.2f} {unit}" if unit in {"GB", "TB"} else f"{value:.1f} {unit}"

    @property
    def modified_text(self) -> str:
        try:
            return datetime.fromtimestamp(self.path.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
        except OSError:
            return "—"


class HashWorker(QThread):
    """ISO'nun SHA-256 değerini arka planda hesaplar (ilerleme bildirir, iptal edilebilir)."""

    completed = Signal(str, str)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            digest = UsbMediaService.compute_sha256(
                self.path, lambda percent, _text: self.progress.emit(percent), lambda: self._cancelled
            )
            self.completed.emit(str(self.path), digest)
        except Exception as exc:
            self.failed.emit(str(exc))


class ScanWorker(QThread):
    """Klasörleri arka planda tarar; büyük klasörlerde arayüz donmaz."""

    found = Signal(list)

    def __init__(self, roots: list[Path]):
        super().__init__()
        self.roots = roots
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        paths: dict[str, Path] = {}
        for root in self.roots:
            if self._cancelled:
                return
            try:
                for path in root.rglob("*"):
                    if self._cancelled:
                        return
                    if path.suffix.lower() != ".iso" or not path.is_file():
                        continue
                    paths[str(path.resolve()).lower()] = path
            except (OSError, PermissionError):
                continue
        self.found.emit(list(paths.values()))


class IsoCenterPage(QWidget):
    send_to_usb = Signal(str)  # seçili ISO'nun yolu; ana pencere USB sayfasını açar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[IsoRecord] = []
        self.filtered_records: list[IsoRecord] = []
        self.selected_record: IsoRecord | None = None
        self._hash_worker: HashWorker | None = None
        self._scan_worker: ScanWorker | None = None
        self._scanned_once = False
        self._hash_cache: dict[str, str] = {}
        self._ms_thread = None
        self._ms_worker = None
        self._dl_busy = False
        self._ctx_version = ""
        self._ctx_build = ""
        self._uup_signal_connected = False
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._scanned_once:  # ilk açılışta tara; program başlarken disk gezilmez
            self.refresh_scan()

    def shutdown(self) -> None:
        """Kapanışta çalışan arka plan işlerini durdurur."""
        if self._ms_thread is not None:
            try:
                self._ms_thread.quit()
                self._ms_thread.wait(1500)
            except RuntimeError:
                pass
        for worker in (self._scan_worker, self._hash_worker):
            if worker is not None:
                try:
                    worker.cancel()
                    worker.wait(1500)
                except RuntimeError:
                    pass

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(14)

        title = QLabel("Windows ISO Merkezi")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        subtitle = QLabel("Oluşturduğunuz ve bilgisayarınızdaki Windows ISO dosyalarını tek merkezden yönetin.")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(subtitle)

        root.addWidget(self._build_download_card())

        controls = QFrame(); controls.setObjectName("isoCard")
        cl = QVBoxLayout(controls); cl.setContentsMargins(14, 14, 14, 14); cl.setSpacing(10)
        top = QHBoxLayout(); top.setSpacing(8)
        self.search = QLineEdit(); self.search.setPlaceholderText("ISO adı, build veya sürüm ara...")
        self.search.textChanged.connect(self._apply_filters)
        top.addWidget(self.search, 1)
        refresh = QPushButton("Yeniden Tara"); refresh.clicked.connect(self.refresh_scan); top.addWidget(refresh)
        add_folder = QPushButton("ISO Klasörü Ekle"); add_folder.clicked.connect(self._add_folder); top.addWidget(add_folder)
        cl.addLayout(top)

        filters = QHBoxLayout(); filters.setSpacing(8)
        self.build_filter = self._combo("Build: Tüm Build'ler")
        self.arch_filter = self._combo("Mimari: Tüm Mimariler")
        self.lang_filter = self._combo("Dil: Tüm Diller")
        self.edition_filter = self._combo("Edition: Tüm Edition'lar")
        for combo in (self.build_filter, self.arch_filter, self.lang_filter, self.edition_filter):
            combo.currentIndexChanged.connect(self._apply_filters)
            filters.addWidget(combo, 1)
        cl.addLayout(filters)
        root.addWidget(controls)

        body = QHBoxLayout(); body.setSpacing(12)
        table_card = QFrame(); table_card.setObjectName("isoCard")
        tl = QVBoxLayout(table_card); tl.setContentsMargins(10, 10, 10, 10)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["ISO Dosyası", "Build", "Mimari", "Dil", "Edition", "Boyut", "Tarih", "Konum"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 7): self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        tl.addWidget(self.table)
        self._empty = attach_empty_state(self.table, "doc", self._empty_text)
        self._empty.clicked.connect(self._add_folder)
        body.addWidget(table_card, 3)

        detail = QFrame(); detail.setObjectName("isoCard"); detail.setMinimumWidth(330); detail.setMaximumWidth(410)
        dl = QVBoxLayout(detail); dl.setContentsMargins(16, 16, 16, 16); dl.setSpacing(12)
        h = QLabel("Seçili ISO"); h.setObjectName("sectionTitle"); dl.addWidget(h)
        self.detail_title = QLabel("Listeden bir ISO seçin"); self.detail_title.setWordWrap(True); self.detail_title.setObjectName("isoDetailTitle"); dl.addWidget(self.detail_title)
        self.info_labels = {}
        grid = QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)
        for idx, key in enumerate(["Build", "Mimari", "Dil", "Edition", "Boyut", "Tarih", "SHA-256"]):
            box = QFrame(); box.setObjectName("infoTile")
            bl = QVBoxLayout(box); bl.setContentsMargins(9, 7, 9, 7); bl.setSpacing(2)
            k = QLabel(key); k.setObjectName("tileKey"); v = QLabel("—"); v.setObjectName("tileValue"); v.setWordWrap(True)
            bl.addWidget(k); bl.addWidget(v); self.info_labels[key] = v
            if key == "SHA-256": grid.addWidget(box, 3, 0, 1, 2)
            else: grid.addWidget(box, idx // 2, idx % 2)
        dl.addLayout(grid)
        self.path_label = QLabel("Konum: —"); self.path_label.setWordWrap(True); self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse); dl.addWidget(self.path_label)
        dl.addStretch()
        self.open_btn = QPushButton("ISO Klasörünü Aç"); self.open_btn.clicked.connect(self._open_folder)
        self.mount_btn = QPushButton("ISO'yu Bağla"); self.mount_btn.clicked.connect(self._mount_iso)
        self.hash_btn = QPushButton("SHA-256 Doğrula"); self.hash_btn.clicked.connect(self._hash_iso)
        self.usb_btn = QPushButton("USB Hazırlamaya Gönder"); self.usb_btn.clicked.connect(self._send_to_usb)
        self.delete_btn = QPushButton("ISO'yu Sil"); self.delete_btn.setProperty("danger", True); self.delete_btn.clicked.connect(self._delete_iso)
        for b in (self.open_btn, self.mount_btn, self.hash_btn, self.usb_btn, self.delete_btn):
            b.setEnabled(False); b.setMinimumHeight(38); dl.addWidget(b)
        body.addWidget(detail, 1)
        root.addLayout(body, 1)

        self.setStyleSheet(styles.qss("""
            QFrame#isoCard { background:#FFFFFF; border:1px solid #D9E4F2; border-radius:10px; }
            QLineEdit, QComboBox { background:#FFFFFF; border:1px solid #C9D7E8; border-radius:8px; padding:8px 10px; min-height:22px; }
            QPushButton { background:@BLUE@; color:white; border:none; border-radius:7px; padding:8px 14px; font-weight:600; }
            QPushButton:hover { background:#1D5FC5; }
            QPushButton:disabled { background:#D7DEE8; color:#8C9AAF; }
            QPushButton[danger="true"] { background:#FFFFFF; color:#D63A3A; border:1px solid #F1A8A8; }
            QPushButton[danger="true"]:hover { background:#FFF0F0; }
            QTableWidget { background:#FFFFFF; border:none; gridline-color:#E7EDF5; selection-background-color:#D9E9FF; selection-color:#0B1736; }
            QHeaderView::section { background:#EAF2FD; color:#17345C; padding:8px; border:none; border-right:1px solid #D6E1F0; font-weight:600; }
            QLabel#sectionTitle, QLabel#isoDetailTitle { color:#0B1736; font-size:16px; font-weight:700; }
            QFrame#infoTile { background:#F5F8FC; border:1px solid #D9E4F2; border-radius:8px; }
            QLabel#tileKey { color:#7B8DA5; font-size:11px; }
            QLabel#tileValue { color:#10264A; font-size:13px; font-weight:600; }
        """))

    # ------------------------------------------------------------------
    # ISO İndir: Microsoft (resmi ISO) veya UUP (build ile) kaynağından
    # ------------------------------------------------------------------
    SOURCE_AUTO = 0
    SOURCE_MS = 1
    SOURCE_UUP = 2

    def _build_download_card(self) -> QFrame:
        card = QFrame(); card.setObjectName("isoCard")
        lay = QVBoxLayout(card); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(10)
        head = QLabel("ISO İndir"); head.setObjectName("sectionTitle"); lay.addWidget(head)
        self.dl_hint = QLabel(
            "Otomatik kaynakta program önce Microsoft'un resmi ISO'sunu dener; aradığınız sürümü Microsoft sunmuyorsa "
            "ya da isteği reddederse UUP ile ISO'yu kendisi hazırlar. Dil ve mimariyi seçip indirmeyi başlatın."
        )
        self.dl_hint.setWordWrap(True); lay.addWidget(self.dl_hint)

        row = QHBoxLayout(); row.setSpacing(8)
        self.dl_source = ModernComboBox(); self.dl_source.addItems(["Kaynak: Otomatik (Microsoft, yoksa UUP)", "Kaynak: Yalnızca Microsoft", "Kaynak: Yalnızca UUP"])
        self.dl_target = QLineEdit()
        self.dl_arch = ModernComboBox(); self.dl_arch.addItems(["x64", "ARM64"])
        self.dl_lang = ModernComboBox(); self.dl_lang.addItems(SystemProfileService.language_options())
        self.dl_edition = ModernComboBox(); self.dl_edition.addItems(EDITION_OPTIONS)
        try:
            profile = SystemProfileService.current()
            for combo, text in ((self.dl_arch, profile.architecture), (self.dl_lang, profile.language_name)):
                index = combo.findText(text)
                if index >= 0:
                    combo.setCurrentIndex(index)
        except Exception:
            pass
        row.addWidget(self.dl_source, 3)
        row.addWidget(self.dl_target, 3)
        row.addWidget(self.dl_arch, 1)
        row.addWidget(self.dl_lang, 2)
        row.addWidget(self.dl_edition, 2)
        self.dl_button = QPushButton("İndirmeyi Başlat"); self.dl_button.setMinimumHeight(38)
        self.dl_button.clicked.connect(self._start_download)
        row.addWidget(self.dl_button)
        lay.addLayout(row)
        self.dl_status = QLabel(""); self.dl_status.setWordWrap(True); self.dl_status.setVisible(False)
        lay.addWidget(self.dl_status)

        self.dl_source.currentIndexChanged.connect(self._on_dl_source_changed)
        self._on_dl_source_changed()
        return card

    def _dl_say(self, text: str) -> None:
        self.dl_status.setText(text)
        self.dl_status.setVisible(bool(text))

    def _on_dl_source_changed(self, *_args) -> None:
        uup = self.dl_source.currentIndex() == self.SOURCE_UUP
        auto = self.dl_source.currentIndex() == self.SOURCE_AUTO
        self.dl_edition.setEnabled(uup or auto)
        self.dl_edition.setToolTip(
            "UUP'de ISO'nun sürümü (Home/Pro vb.). Otomatik kaynakta yalnızca UUP'ye düşülürse kullanılır." if (uup or auto) else
            "Microsoft'un resmi ISO'su tek dosyada tüm sürümleri içerir; sürüm kurulumda seçilir."
        )
        self.dl_target.setPlaceholderText("Build numarası (ör. 26300.9818) ya da sürüm adı (26H2)" if (uup or auto) else "Sürüm adı (ör. 26H2)")
        # Bağlamdan gelen değeri kaynağa uygun olanla değiştir; kullanıcının elle yazdığına dokunma.
        current = self.dl_target.text().strip()
        wanted = (self._ctx_build or self._ctx_version) if uup else self._ctx_version
        if wanted and current in ("", self._ctx_build, self._ctx_version):
            self.dl_target.setText(wanted)
        self.dl_hint.setToolTip("")

    def set_download_context(self, source: str, version: str = "", build: str = "", architecture: str = "x64", language: str | None = None) -> None:
        """Güncelleme Merkezi'nden gelen seçimi panele yerleştirir (source: 'auto', 'microsoft' veya 'uup')."""
        self._ctx_version = (version or "").upper()
        self._ctx_build = build or ""
        self.dl_target.clear()
        index = {"uup": self.SOURCE_UUP, "microsoft": self.SOURCE_MS}.get(source, self.SOURCE_AUTO)
        self.dl_source.setCurrentIndex(index)
        self._on_dl_source_changed()
        if architecture in ("x64", "ARM64"):
            self.dl_arch.setCurrentIndex(max(0, self.dl_arch.findText(architecture)))
        if language:
            lang_index = self.dl_lang.findText(language)
            if lang_index >= 0:
                self.dl_lang.setCurrentIndex(lang_index)
        self._dl_say("Dil ve mimariyi kontrol edip İndirmeyi Başlat'a basın.")
        self.dl_button.setEnabled(True)
        self._dl_busy = False

    def _dl_finish(self, message: str) -> None:
        self._dl_busy = False
        self.dl_button.setEnabled(True)
        self._dl_say(message)

    def _start_download(self) -> None:
        if self._dl_busy:
            return
        text = self.dl_target.text().strip()
        index = self.dl_source.currentIndex()
        self._auto = index == self.SOURCE_AUTO
        if index == self.SOURCE_UUP:
            self._start_uup(text)
        elif self._auto and (not parse_version_query(text) or MicrosoftIsoService.rejected_recently()):
            # Build numarası ya da yakın zamanda reddedilen Microsoft: doğrudan UUP.
            self._fallback_uup("Microsoft resmi ISO'su bu istek için kullanılamıyor; UUP ile devam ediliyor.")
        else:
            self._start_microsoft(text)

    def _fallback_uup(self, reason: str) -> None:
        """Otomatik kaynakta Microsoft olmazsa aynı seçimlerle UUP'ye geçer ve indirmeyi başlatır."""
        self._auto = False
        self.dl_source.setCurrentIndex(self.SOURCE_UUP)  # hedef alanı UUP'ye uygun (build) değere döner
        self._dl_say(reason)
        self._start_uup(self.dl_target.text().strip())

    # ---- Microsoft ----
    def _start_microsoft(self, text: str) -> None:
        version = parse_version_query(text)
        if not version:
            show_warning(self, "ISO İndir", "Microsoft için sürüm adı yazın (ör. 26H2). Build numarasıyla ISO için UUP kaynağını seçin.")
            return
        self._wanted_version = version
        self._dl_busy = True
        self.dl_button.setEnabled(False)
        self._dl_say("Microsoft'un resmi sitesinden ISO bağlantısı isteniyor…")
        self._ms_thread = QThread(self)
        self._ms_worker = MsIsoLinkWorker(self.dl_lang.currentText(), self.dl_arch.currentText())
        self._ms_worker.moveToThread(self._ms_thread)
        self._ms_thread.started.connect(self._ms_worker.run)
        self._ms_worker.finished.connect(self._ms_finished)
        self._ms_worker.failed.connect(self._ms_failed)
        self._ms_worker.finished.connect(self._ms_thread.quit)
        self._ms_worker.failed.connect(self._ms_thread.quit)
        self._ms_thread.finished.connect(self._ms_cleanup)
        self._ms_thread.start()

    def _ms_cleanup(self) -> None:
        if self._ms_worker is not None:
            self._ms_worker.deleteLater()
        if self._ms_thread is not None:
            self._ms_thread.deleteLater()
        self._ms_worker = None
        self._ms_thread = None

    def _ms_finished(self, offer) -> None:
        wanted = getattr(self, "_wanted_version", "")
        if offer.version and wanted and offer.version != wanted and getattr(self, "_auto", False):
            self._dl_finish("")
            self._fallback_uup(f"Microsoft şu an yalnızca {offer.version} sunuyor; {wanted} için UUP ile ISO hazırlanıyor.")
            return
        if offer.version and wanted and offer.version != wanted:
            if not ask_confirmation(
                self, "ISO İndir",
                f"Microsoft şu anda {offer.version} ISO'sunu sunuyor; {wanted} için resmi bir ISO yok.\n\n"
                f"{offer.version} ISO'sunu indirmek ister misiniz? {wanted} için UUP kaynağını da seçebilirsiniz.",
                heading=f"{wanted} Microsoft'un sitesinde yok",
                confirm_text=f"{offer.version} ISO'sunu indir", cancel_text="Vazgeç",
            ):
                self._dl_finish(f"Vazgeçildi. Microsoft şu an {offer.version} sunuyor; {wanted} için Kaynak: UUP'yi deneyebilirsiniz.")
                return
        settings = SettingsService.load()
        base = str(settings.get("downloads", {}).get("default_folder", "") or "").strip()
        initial = str(Path(base) / offer.filename) if base and Path(base).exists() else offer.filename
        target, _ = QFileDialog.getSaveFileName(self, "Microsoft ISO'sunu kaydet", initial, "ISO dosyası (*.iso)")
        if not target:
            self._dl_finish("Kayıt konumu seçilmedi; indirme başlatılmadı.")
            return
        package = PackageResult(
            update_id=f"ms-iso:{offer.version}:{offer.architecture}",
            update_title=f"Windows 11 {offer.version} ISO ({offer.language}, {offer.architecture})",
            filename=offer.filename, architecture=offer.architecture, file_type="ISO", size="—",
            direct_url=offer.url, source="Microsoft ISO", product="Windows 11", version=offer.version,
        )
        DownloadManager.instance().add_download(package, target)
        self._dl_finish(f"{offer.filename} indirme kuyruğuna eklendi. İlerlemeyi İndirme Yöneticisi'nde izleyebilirsiniz; bitince burada listelenir.")

    def _ms_failed(self, message: str, rejected: bool) -> None:
        if rejected:
            reason = (
                "Microsoft, programdan gelen otomatik isteği reddetti. Bu genellikle kısa sürede çok deneme (IP geçici engellenir), "
                "VPN/proxy kullanımı ya da Microsoft'un bot denetimi yüzünden olur."
            )
        else:
            reason = "Microsoft'tan ISO bağlantısı alınamadı."
        if getattr(self, "_auto", False):
            self._dl_finish("")
            self._fallback_uup(
                "Microsoft resmi sitesi isteği reddetti (IP/VPN ya da bot denetimi); UUP ile devam ediliyor." if rejected
                else "Microsoft'tan bağlantı alınamadı; UUP ile devam ediliyor."
            )
            return
        if rejected:
            # Microsoft kapıyı kapattı: kullanıcıyı bekletmeden UUP kaynağına geçip aynı seçimlerle devam ederiz.
            self.dl_source.setCurrentIndex(self.SOURCE_UUP)
            self._dl_finish(
                "Microsoft resmi sitesi programdan gelen isteği reddetti (IP/VPN ya da bot denetimi). "
                "UUP kaynağına geçildi ve indirme aynı seçimlerle başlatılıyor."
            )
            self._start_download()
            return
        self._dl_finish(f"{reason} Ayrıntı: {message}")
        if ask_confirmation(
            self, "ISO İndir", f"{reason}\n\nAyrıntı: {message}\n\nUUP kaynağından devam etmek ister misiniz?",
            heading="Microsoft ISO bağlantısı alınamadı", confirm_text="UUP'ye geç", cancel_text="Şimdilik vazgeç",
        ):
            self.dl_source.setCurrentIndex(self.SOURCE_UUP)
            self._dl_say("Kaynak UUP olarak değiştirildi. Build/sürümü, dili ve edition'ı kontrol edip İndirmeyi Başlat'a basın.")

    # ---- UUP ----
    def _resolve_build(self, text: str) -> tuple[str, str]:
        """Metinden (build, başlık) üretir: build numarası doğrudan, sürüm adı en son yayın build'ine çevrilir."""
        if re.fullmatch(r"\d{4,5}\.\d{1,5}", text):
            return text, f"Windows 11 build {text}"
        version = parse_version_query(text)
        if not version:
            return "", ""
        records, _updated, _fetched = BuildTrackerService.load_cache()
        record = latest_build_for_version(records, version)
        if record is None:
            try:
                records, _updated = BuildTrackerService().fetch()
            except Exception:
                records = []
            record = latest_build_for_version(records, version)
        if record is None:
            return "", ""
        return record.build_number, f"Windows 11, version {version} ISO - en son yayın {record.build_number}"

    def _start_uup(self, text: str) -> None:
        build, title = self._resolve_build(text)
        if not build:
            show_warning(
                self, "ISO İndir",
                "UUP için bir build numarası (ör. 26300.9818) ya da sürüm adı (26H2) yazın. Sürüm adı için Windows Sürüm Takibi "
                "listesi gerekir; boşsa orada Şimdi Güncelle'ye basın.",
            )
            return
        window = self.window()
        uup_page = window.page_by_name("UUP ISO Oluşturucu") if hasattr(window, "page_by_name") else None
        if uup_page is None or not hasattr(uup_page, "request_auto_download"):
            show_error(self, "ISO İndir", "UUP ISO Oluşturucu sayfası bulunamadı.")
            return
        if not self._uup_signal_connected:
            uup_page.auto_finished.connect(self._uup_done)
            self._uup_signal_connected = True
        self._dl_busy = True
        self.dl_button.setEnabled(False)
        self._dl_say(f"{build} için UUP kayıtları aranıyor…")
        uup_page.request_auto_download(
            build, title, "", "Microsoft UUP",
            self.dl_arch.currentText(), self.dl_lang.currentText(), self.dl_edition.currentText(),
        )

    def _uup_done(self, ok: bool, message: str) -> None:
        if not self._dl_busy:
            return
        self._dl_finish(message)
        if ok:
            window = self.window()
            if hasattr(window, "show_page_by_name"):
                window.show_page_by_name("İndirme Yöneticisi")

    def _combo(self, first: str):
        combo = ModernComboBox()
        combo.addItem(first)
        return combo

    def _combo_value(self, text: str) -> str:
        return text.split(": ", 1)[1] if ": " in text else text

    def _scan_folders(self) -> list[str]:
        data = SettingsService.load()
        folders = [str(x) for x in data.get("iso_center", {}).get("scan_folders", [])]
        legacy = [str(x) for x in data.get("iso_scan_folders", [])]  # eski sürümde üst düzey anahtardı
        merged = folders + [x for x in legacy if x not in folders]
        if legacy and merged != folders:
            SettingsService.update_value("iso_center", "scan_folders", merged)
        return merged

    def _empty_text(self):
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return ("ISO dosyaları aranıyor…", "Klasörler taranıyor, birkaç saniye sürebilir.", None)
        if self.records:
            return ("Bu aramada sonuç yok", "Arama ya da süzgeçleri değiştirmeyi deneyin.", None)
        return ("Henüz ISO bulunamadı",
                "UUP ISO Oluşturucu ile oluşturduğunuz ISO'lar burada görünür. Başka bir klasördeki ISO'ları görmek için klasör ekleyin.",
                "ISO Klasörü Ekle")

    def _scan_roots(self) -> list[Path]:
        roots: list[Path] = []
        for raw in self._scan_folders():
            p = Path(raw)
            if p.exists(): roots.append(p)
        for state in IsoBuildManager.instance().all_states().values():
            iso = state.get("iso_path", "")
            if iso:
                p = Path(iso)
                if p.exists(): roots.append(p.parent)
            meta = state.get("metadata", {}) or {}
            project = meta.get("project_dir", "")
            if project:
                p = Path(project)
                if p.exists(): roots.append(p)
        for job in DownloadManager.instance().all_jobs():
            try:
                p = Path(job.target_path)
                if p.exists(): roots.append(p.parent)
            except Exception: pass
        # Deduplicate and prefer shallow roots only once.
        out = []
        seen = set()
        for root in roots:
            key = str(root.resolve()).lower()
            if key not in seen:
                seen.add(key); out.append(root)
        return out

    def refresh_scan(self):
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        self._scanned_once = True
        self._scan_worker = ScanWorker(self._scan_roots())
        self._scan_worker.found.connect(self._scan_done)
        self._scan_worker.finished.connect(self._scan_finished)
        self._empty._sync()
        self._scan_worker.start()

    def _scan_finished(self):
        worker, self._scan_worker = self._scan_worker, None
        if worker is not None:
            worker.deleteLater()
        self._empty._sync()

    def _scan_done(self, paths: list):
        state_by_iso = {}
        for state in IsoBuildManager.instance().all_states().values():
            p = state.get("iso_path", "")
            if p: state_by_iso[str(Path(p).resolve()).lower()] = state
        found: dict[str, IsoRecord] = {}
        for path in paths:
            key = str(Path(path).resolve()).lower()
            meta = (state_by_iso.get(key, {}).get("metadata", {}) or {})
            found[key] = self._record_from_path(Path(path), meta)
        self.records = sorted(found.values(), key=lambda r: r.path.stat().st_mtime if r.path.exists() else 0, reverse=True)
        self._populate_filters(); self._apply_filters()

    def _record_from_path(self, path: Path, meta: dict) -> IsoRecord:
        name = path.stem
        build = str(meta.get("build", meta.get("build_number", "")) or "")
        if not build:
            m = re.search(r"(?<!\d)(\d{5}\.\d+)(?!\d)", name); build = m.group(1) if m else "—"
        arch = str(meta.get("architecture", "") or "")
        if not arch:
            for token in ("ARM64", "x64", "x86"):
                if token.lower() in name.lower(): arch = token; break
        lang = str(meta.get("language", meta.get("lang", "")) or "—")
        edition = str(meta.get("edition", "") or "")
        if not edition:
            lower = name.lower()
            edition = "Windows 11 Pro" if "professional" in lower or "_pro" in lower else "—"
        product = str(meta.get("product", "Windows") or "Windows")
        return IsoRecord(path=path, build=build or "—", architecture=arch or "—", language=lang, edition=edition, product=product)

    def _populate_filters(self):
        specs = [
            (self.build_filter, "Build: Tüm Build'ler", [f"Build: {v}" for v in sorted({r.build for r in self.records if r.build != "—"})]),
            (self.arch_filter, "Mimari: Tüm Mimariler", [f"Mimari: {v}" for v in sorted({r.architecture for r in self.records if r.architecture != "—"})]),
            (self.lang_filter, "Dil: Tüm Diller", [f"Dil: {v}" for v in sorted({r.language for r in self.records if r.language != "—"})]),
            (self.edition_filter, "Edition: Tüm Edition'lar", [f"Edition: {v}" for v in sorted({r.edition for r in self.records if r.edition != "—"})]),
        ]
        for combo, first, values in specs:
            old = combo.currentText(); combo.blockSignals(True); combo.clear(); combo.addItem(first); combo.addItems(values)
            idx = combo.findText(old); combo.setCurrentIndex(idx if idx >= 0 else 0); combo.blockSignals(False)

    def _apply_filters(self):
        query = self.search.text().strip().lower()
        values = [self._combo_value(self.build_filter.currentText()), self._combo_value(self.arch_filter.currentText()), self._combo_value(self.lang_filter.currentText()), self._combo_value(self.edition_filter.currentText())]
        firsts = ["Tüm Build'ler", "Tüm Mimariler", "Tüm Diller", "Tüm Edition'lar"]
        out = []
        for r in self.records:
            hay = f"{r.path.name} {r.build} {r.architecture} {r.language} {r.edition}".lower()
            if query and query not in hay: continue
            attrs = [r.build, r.architecture, r.language, r.edition]
            if any(v != f and v != a for v, f, a in zip(values, firsts, attrs)): continue
            out.append(r)
        self.filtered_records = out
        self.table.setRowCount(len(out))
        for row, r in enumerate(out):
            vals = [r.path.name, r.build, r.architecture, r.language, r.edition, r.size_text, r.modified_text, str(r.path.parent)]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val); item.setToolTip(str(r.path) if col in {0,7} else val); self.table.setItem(row, col, item)
        self.selected_record = None; self._render_detail()

    def _selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        self.selected_record = self.filtered_records[rows[0].row()] if rows else None
        self._render_detail()

    def _render_detail(self):
        r = self.selected_record; enabled = r is not None
        for b in (self.open_btn, self.mount_btn, self.hash_btn, self.usb_btn, self.delete_btn): b.setEnabled(enabled)
        if not r:
            self.detail_title.setText("Listeden bir ISO seçin")
            for label in self.info_labels.values(): label.setText("—")
            self.path_label.setText("Konum: —"); return
        self.detail_title.setText(r.path.name)
        data = {"Build":r.build,"Mimari":r.architecture,"Dil":r.language,"Edition":r.edition,"Boyut":r.size_text,"Tarih":r.modified_text,"SHA-256":self._hash_cache.get(str(r.path), "Henüz doğrulanmadı")}
        for k,v in data.items(): self.info_labels[k].setText(v)
        self.path_label.setText(f"Konum: {r.path}")

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "ISO klasörü seç")
        if not folder: return
        folders = self._scan_folders()
        if folder not in folders: folders.append(folder)
        SettingsService.update_value("iso_center", "scan_folders", folders)
        self.refresh_scan()

    def _open_folder(self):
        r = self.selected_record
        if not r: return
        try:
            if os.name == "nt": subprocess.Popen(["explorer.exe", "/select,", str(r.path)])
            else: subprocess.Popen(["xdg-open", str(r.path.parent)])
        except Exception as exc: show_error(self, "ISO Klasörü", str(exc), "Klasör açılamadı")

    def _mount_iso(self):
        r = self.selected_record
        if not r: return
        try:
            if os.name == "nt": os.startfile(str(r.path))
            else: show_information(self, "ISO Bağlama", "Otomatik ISO bağlama şu anda Windows üzerinde destekleniyor.")
        except Exception as exc: show_error(self, "ISO Bağlama", str(exc), "ISO bağlanamadı")

    def _hash_iso(self):
        r = self.selected_record
        if not r or self._hash_worker is not None: return
        self.hash_btn.setEnabled(False); self.hash_btn.setText("SHA-256 hesaplanıyor...")
        worker = HashWorker(r.path)
        worker.progress.connect(lambda p: self.hash_btn.setText(f"SHA-256 hesaplanıyor… %{p}"))
        worker.completed.connect(self._hash_done); worker.failed.connect(self._hash_failed)
        worker.finished.connect(self._hash_finished)
        self._hash_worker = worker
        worker.start()

    def _hash_finished(self):
        worker, self._hash_worker = self._hash_worker, None
        if worker is not None:
            worker.deleteLater()

    def _hash_done(self, path: str, digest: str):
        self._hash_cache[path] = digest; self.hash_btn.setText("SHA-256 Doğrula"); self._render_detail()
        show_success(self, "SHA-256", digest, "Doğrulama tamamlandı")

    def _hash_failed(self, error: str):
        self.hash_btn.setText("SHA-256 Doğrula"); self._render_detail(); show_error(self, "SHA-256", error, "Doğrulama başarısız")

    def _delete_iso(self):
        r = self.selected_record
        if not r: return
        if not ask_confirmation(self, "ISO'yu Sil", f"{r.path.name}\n\nBu dosya diskten kalıcı olarak silinecek.", destructive=True, confirm_text="ISO'yu Sil"):
            return
        try: r.path.unlink(); self.refresh_scan(); show_success(self, "ISO Silindi", "ISO dosyası diskten silindi.")
        except Exception as exc: show_error(self, "ISO Silme", str(exc), "Dosya silinemedi")

    def _send_to_usb(self):
        r = self.selected_record
        if r is not None:
            self.send_to_usb.emit(str(r.path))
