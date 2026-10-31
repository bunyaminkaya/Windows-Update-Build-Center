from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from services.driver_backup_service import (
    BackupResult, DriverBackupService, DriverInfo, ProblemDevice, format_size,
)
from app import i18n
from ui import icons, styles
from ui.widgets.empty_state import attach_empty_state
from ui.widgets.message_dialog import (
    ask_confirmation, show_error, show_information, show_success, show_warning,
)
from ui.widgets.modern_combo_box import ModernComboBox
from ui.widgets.table_export import export_table_csv, make_export_button


class _ScanWorker(QThread):
    """Sürücü ve sorunlu aygıt listesini (PowerShell, birkaç sn) arka planda okur."""

    done = Signal(object, object)
    failed = Signal(str)

    def run(self):
        try:
            drivers = DriverBackupService.list_drivers()
        except Exception as exc:
            self.failed.emit(f"Sürücü listesi okunamadı: {exc}")
            return
        try:
            problems = DriverBackupService.list_problem_devices()
        except Exception:
            problems = []
        try:  # boyut tahmini yardımcı bilgidir; okunamazsa liste yine de gelir
            sizes = DriverBackupService.estimate_sizes(drivers)
            for d in drivers:
                d.size_bytes = sizes.get(d.inf_name.lower(), 0)
        except Exception:
            pass
        self.done.emit(drivers, problems)


class _UsbTargetWorker(QThread):
    done = Signal(object)

    def run(self):
        try:
            self.done.emit(DriverBackupService.usb_targets())
        except Exception:
            self.done.emit([])


class _BackupWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, drivers, dest, parent=None):
        super().__init__(parent)
        self._drivers = drivers
        self._dest = dest
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = DriverBackupService.backup(
                self._drivers,
                self._dest,
                on_progress=lambda i, n, inf: self.progress.emit(i, n, inf),
                cancelled=lambda: self._cancel,
            )
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class _RestoreWorker(QThread):
    done = Signal(bool, bool, str, str)
    failed = Signal(str)

    def __init__(self, source, restore_point, parent=None):
        super().__init__(parent)
        self._source = source
        self._restore_point = restore_point

    def run(self):
        try:
            ok, reboot, summary, detail = DriverBackupService.restore(
                self._source, restore_point=self._restore_point
            )
            self.done.emit(ok, reboot, summary, detail)
        except Exception as exc:
            self.failed.emit(str(exc))


class DriverBackupPage(QWidget):
    COLUMNS = ["", "Aygıt", "Sağlayıcı", "Sınıf", "Sürüm", "Tarih", "INF"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drivers: list[DriverInfo] = []
        self._problems: list[ProblemDevice] = []
        self._usb_targets: list = []
        self._scan: _ScanWorker | None = None
        self._backup: _BackupWorker | None = None
        self._restore: _RestoreWorker | None = None
        self._usb_worker: _UsbTargetWorker | None = None
        self._loading = False
        self._busy = False
        self._empty_text = ("Sürücüler henüz okunmadı", "Yenile düğmesine basarak üçüncü taraf sürücüleri listeleyin.")
        self.setObjectName("driverPage")
        self._build_ui()
        self._apply_styles()
        self.refresh()

    # ------------------------------------------------------------------ yardımcılar
    @staticmethod
    def _ico(name, color, size=36, stroke=2.0):
        return QIcon(icons.pixmap(name, color, size, stroke=stroke))

    def _card(self, name="drvCard"):
        card = QFrame()
        card.setObjectName(name)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        return card, lay

    @staticmethod
    def _title(text, note=""):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        t = QLabel(text)
        t.setObjectName("drvCardTitle")
        v.addWidget(t)
        if note:
            n = QLabel(note)
            n.setObjectName("drvNote")
            n.setWordWrap(True)
            v.addWidget(n)
        return box

    # ------------------------------------------------------------------ arayüz
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("drvScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("drvBody")
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(26, 20, 26, 20)
        root.setSpacing(14)

        # Başlık
        head = QHBoxLayout()
        head.setSpacing(14)
        tile = QLabel()
        tile.setObjectName("drvHeadIcon")
        tile.setFixedSize(64, 64)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap("cpu", "#1768E0", 34, stroke=1.9))
        head.addWidget(tile, 0, Qt.AlignTop)
        tb = QVBoxLayout()
        tb.setSpacing(2)
        title = QLabel("Sürücü Yedekleme")
        title.setObjectName("pageTitle")
        sub = QLabel("Format atmadan önce üçüncü taraf sürücüleri yedekleyin; kurulumdan sonra tek tıkla geri yükleyin.")
        sub.setObjectName("pageSubtitle")
        sub.setWordWrap(True)
        tb.addWidget(title)
        tb.addWidget(sub)
        head.addLayout(tb, 1)
        self.export_button = make_export_button()
        self.export_button.clicked.connect(
            lambda: export_table_csv(self, self.table, "suruculer", skip_columns=(0,))
        )
        head.addWidget(self.export_button, 0, Qt.AlignTop)
        self.refresh_button = QPushButton("  Yenile")
        self.refresh_button.setObjectName("drvPrimary")
        self.refresh_button.setIcon(self._ico("refresh", "#FFFFFF"))
        self.refresh_button.setIconSize(QSize(18, 18))
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)
        head.addWidget(self.refresh_button, 0, Qt.AlignTop)
        root.addLayout(head)

        # Bilgi şeridi (kullanıcıya açıkça yazılması gereken sınırlar)
        info = QFrame()
        info.setObjectName("drvInfo")
        il = QHBoxLayout(info)
        il.setContentsMargins(14, 10, 14, 10)
        il.setSpacing(10)
        ii = QLabel()
        ii.setPixmap(icons.pixmap("info-fill", "#1768E0", 20))
        il.addWidget(ii, 0, Qt.AlignTop)
        il.addWidget(self._info_label(
            "Yalnızca üçüncü taraf (OEM) sürücüler yedeklenir: ekran kartı, Wi-Fi, ses, yonga seti gibi "
            "üreticinin kendi sürücüleri. Windows'un kendi sürücüleri yedeklenmez; Windows zaten kendi kurulumunda getirir. "
            "Yedekleme ve geri yükleme yönetici izni (UAC penceresi) ister. Yedek, aynı bilgisayara geri yüklenmek içindir."
        ), 1)
        root.addWidget(info)

        cols = QHBoxLayout()
        cols.setSpacing(14)

        # Sol: liste
        left, lv = self._card()
        lv.setContentsMargins(14, 14, 14, 14)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("drvSearch")
        self.filter_edit.setPlaceholderText("Aygıt, sağlayıcı veya sınıf ara...")
        self.filter_edit.addAction(self._ico("search", "#4B5E7C"), QLineEdit.LeadingPosition)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.select_all_btn = QPushButton("Tümünü Seç")
        self.select_none_btn = QPushButton("Seçimi Kaldır")
        for b in (self.select_all_btn, self.select_none_btn):
            b.setObjectName("drvSecondary")
            b.setCursor(Qt.PointingHandCursor)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        controls.addWidget(self.filter_edit, 1)
        controls.addWidget(self.select_all_btn)
        controls.addWidget(self.select_none_btn)
        lv.addLayout(controls)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("drvTable")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setMinimumHeight(360)
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setDefaultAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        for col, width in ((0, 44), (2, 104), (3, 96), (4, 104), (5, 104), (6, 84)):
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemChanged.connect(lambda _item: self._update_summary())
        self._empty = attach_empty_state(self.table, "cpu", self._empty_resolver)
        self._empty.clicked.connect(self.refresh)
        lv.addWidget(self.table, 1)
        self.summary = QLabel("")
        self.summary.setObjectName("drvSummary")
        lv.addWidget(self.summary)
        cols.addWidget(left, 1)

        # Sağ: işlemler
        right = QVBoxLayout()
        right.setSpacing(14)
        right.addWidget(self._build_backup_card())
        right.addWidget(self._build_restore_card())
        right.addWidget(self._build_problem_card())
        right.addStretch(1)
        side = QWidget()
        side.setObjectName("drvSide")
        side.setFixedWidth(360)
        side.setLayout(right)
        cols.addWidget(side, 0)
        root.addLayout(cols, 1)

    @staticmethod
    def _info_label(text):
        label = QLabel(text)
        label.setObjectName("drvInfoText")
        label.setWordWrap(True)
        return label

    def _build_backup_card(self):
        card, v = self._card()
        v.addWidget(self._title("1 · Yedekle", "Seçili sürücüleri bir klasöre ya da USB belleğe kaydeder."))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.dest_edit = QLineEdit(str(DriverBackupService.default_backup_root()))
        self.dest_edit.setObjectName("drvPath")
        self.dest_edit.setToolTip("Yedek bu klasörün içinde 'Surucu_Yedegi_…' adlı yeni bir klasöre yazılır.")
        browse = QPushButton("Seç")
        browse.setObjectName("drvSecondary")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse_dest)
        row.addWidget(self.dest_edit, 1)
        row.addWidget(browse)
        v.addLayout(row)

        self.backup_button = QPushButton("  Seçili Sürücüleri Yedekle")
        self.backup_button.setObjectName("drvPrimary")
        self.backup_button.setIcon(self._ico("download", "#FFFFFF"))
        self.backup_button.setIconSize(QSize(18, 18))
        self.backup_button.setCursor(Qt.PointingHandCursor)
        self.backup_button.clicked.connect(self.start_backup)
        v.addWidget(self.backup_button)

        sep = QFrame()
        sep.setObjectName("drvSep")
        sep.setFixedHeight(1)
        v.addWidget(sep)

        usb_label = QLabel("Kurulum USB'sine ekle")
        usb_label.setObjectName("drvSection")
        v.addWidget(usb_label)
        usb_note = QLabel(
            "Önce USB Kurulum Aracı ile kurulum belleğini oluşturun, sonra buradan ekleyin. "
            "Kurulum belleğini yeniden oluşturursanız içindeki yedek silinir."
        )
        usb_note.setObjectName("drvNote")
        usb_note.setWordWrap(True)
        v.addWidget(usb_note)
        urow = QHBoxLayout()
        urow.setSpacing(8)
        self.usb_combo = ModernComboBox()
        self.usb_combo.addItem("USB bellek aranıyor...")
        self.usb_refresh = QPushButton()
        self.usb_refresh.setObjectName("drvSecondary")
        self.usb_refresh.setIcon(self._ico("refresh", "#1768E0"))
        self.usb_refresh.setIconSize(QSize(16, 16))
        self.usb_refresh.setToolTip("USB bellekleri yeniden ara")
        self.usb_refresh.setCursor(Qt.PointingHandCursor)
        self.usb_refresh.clicked.connect(self.refresh_usb_targets)
        urow.addWidget(self.usb_combo, 1)
        urow.addWidget(self.usb_refresh)
        v.addLayout(urow)
        self.usb_info = QLabel("")
        self.usb_info.setObjectName("drvNote")
        self.usb_info.setWordWrap(True)
        v.addWidget(self.usb_info)
        self.usb_combo.currentIndexChanged.connect(lambda _i: self._update_usb_info())
        self.usb_button = QPushButton("  USB'ye Yedekle")
        self.usb_button.setObjectName("drvSecondary")
        self.usb_button.setIcon(self._ico("usb", "#1768E0"))
        self.usb_button.setIconSize(QSize(18, 18))
        self.usb_button.setCursor(Qt.PointingHandCursor)
        self.usb_button.clicked.connect(self.start_usb_backup)
        v.addWidget(self.usb_button)

        self.progress = QProgressBar()
        self.progress.setObjectName("drvProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setRange(0, 100)
        self.progress.hide()
        v.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("drvNote")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.cancel_button = QPushButton("İptal")
        self.cancel_button.setObjectName("drvSecondary")
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(self._cancel_backup)
        self.cancel_button.hide()
        v.addWidget(self.cancel_button)
        return card

    def _build_restore_card(self):
        card, v = self._card()
        v.addWidget(self._title("2 · Geri yükle", "Yedek klasöründeki tüm sürücüleri yükler (yeni kurulumdan sonra)."))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.restore_edit = QLineEdit()
        self.restore_edit.setObjectName("drvPath")
        self.restore_edit.setPlaceholderText("Yedek klasörünü seçin...")
        browse = QPushButton("Seç")
        browse.setObjectName("drvSecondary")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse_restore)
        row.addWidget(self.restore_edit, 1)
        row.addWidget(browse)
        v.addLayout(row)
        self.restore_point_check = QCheckBox("Önce geri yükleme noktası oluştur")
        self.restore_point_check.setObjectName("drvCheck")
        self.restore_point_check.setChecked(True)
        v.addWidget(self.restore_point_check)
        self.restore_button = QPushButton("  Sürücüleri Geri Yükle")
        self.restore_button.setObjectName("drvSecondary")
        self.restore_button.setIcon(self._ico("undo", "#1768E0"))
        self.restore_button.setIconSize(QSize(18, 18))
        self.restore_button.setCursor(Qt.PointingHandCursor)
        self.restore_button.clicked.connect(self.start_restore)
        v.addWidget(self.restore_button)
        self.restore_log = QPlainTextEdit()
        self.restore_log.setObjectName("drvLog")
        self.restore_log.setReadOnly(True)
        self.restore_log.setFixedHeight(110)
        self.restore_log.hide()
        v.addWidget(self.restore_log)
        warn = QLabel("Sürücüyü farklı donanımlı bir bilgisayara yüklemek sorun çıkarabilir. Yalnızca aynı bilgisayar için kullanın.")
        warn.setObjectName("drvWarn")
        warn.setWordWrap(True)
        v.addWidget(warn)
        return card

    def _build_problem_card(self):
        card, v = self._card()
        v.addWidget(self._title("Sorunlu aygıtlar", "Aygıt Yöneticisi'nde hata gösteren (sarı ünlemli) aygıtlar."))
        self.problem_label = QLabel("Henüz taranmadı.")
        self.problem_label.setObjectName("drvProblemText")
        self.problem_label.setWordWrap(True)
        self.problem_label.setTextFormat(Qt.RichText)
        v.addWidget(self.problem_label)
        return card

    # ------------------------------------------------------------------ stil
    def _apply_styles(self):
        self.setStyleSheet(styles.qss("""
        QWidget#driverPage, QWidget#drvBody, QScrollArea#drvScroll { background: #F3F7FC; }
        QWidget#drvSide { background: transparent; }
        QLabel { background: transparent; }
        QLabel#drvHeadIcon { background: #DCEAFD; border-radius: 18px; }
        QFrame#drvCard { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px; }
        QFrame#drvInfo { background: #EAF2FE; border: 1px solid #CFE0FA; border-radius: 12px; }
        QLabel#drvInfoText { color: #1B3D73; font-size: 13px; }
        QLabel#drvCardTitle { color: #14213D; font-size: 16px; font-weight: 700; }
        QLabel#drvSection { color: #14213D; font-size: 13px; font-weight: 700; }
        QLabel#drvNote { color: #5F7090; font-size: 12px; }
        QLabel#drvSummary { color: #5F7090; font-size: 12px; }
        QLabel#drvWarn { color: #8A5A00; background: #FFF4DC; border: 1px solid #F3D9A0; border-radius: 10px; padding: 8px 10px; font-size: 12px; }
        QLabel#drvProblemText { color: #2A3A5C; font-size: 12px; }
        QFrame#drvSep { background: #E3EAF4; border: none; }
        QPushButton#drvPrimary {
            background: @BLUE@; color: #FFFFFF; border: none; border-radius: 10px;
            padding: 0 14px; font-size: 13px; font-weight: 700; min-height: 44px; max-height: 44px;
        }
        QPushButton#drvPrimary:hover { background: #135BC4; }
        QPushButton#drvPrimary:disabled { background: #A9C4EE; }
        QPushButton#drvSecondary {
            background: #FFFFFF; color: @BLUE@; border: 1px solid #CBD9EC; border-radius: 10px;
            padding: 0 14px; font-size: 13px; font-weight: 700; min-height: 40px; max-height: 40px;
        }
        QPushButton#drvSecondary:hover { background: #F1F6FD; border-color: #9DB9E6; }
        QPushButton#drvSecondary:disabled { color: #8A98B0; background: #F6F9FE; border: 1px solid #E1E8F2; }
        QLineEdit#drvSearch, QLineEdit#drvPath {
            background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 10px;
            padding: 0 12px 0 6px; font-size: 13px; color: #14213D; min-height: 40px; max-height: 40px;
            selection-background-color: @BLUE@;
        }
        QCheckBox#drvCheck { color: #2A3A5C; font-size: 12px; spacing: 8px; }
        QPlainTextEdit#drvLog { background: #F7F9FD; border: 1px solid #DCE5F1; border-radius: 10px; color: #2A3A5C; font-size: 11px; }
        QProgressBar#drvProgress { background: #E3EAF4; border: none; border-radius: 4px; }
        QProgressBar#drvProgress::chunk { background: @BLUE@; border-radius: 4px; }
        QTableWidget#drvTable { background: #FFFFFF; border: none; color: #2A3A5C; font-size: 13px; outline: 0; }
        QTableWidget#drvTable::item { border-bottom: 1px solid #EDF1F6; padding-left: 6px; }
        QTableWidget#drvTable::item:selected { background: #EAF2FE; color: #1B3D73; }
        QHeaderView::section {
            background: #F3F7FC; color: #4B5E7C; border: none; border-bottom: 1px solid #DCE5F1;
            padding: 8px 8px; font-size: 12px; font-weight: 700;
        }
        """))

    # ------------------------------------------------------------------ liste
    def _empty_resolver(self):
        title, text = self._empty_text
        can_retry = (
            DriverBackupService.is_supported_platform() and not self._loading and not self._busy
        )
        return (title, text, "Yenile" if can_retry else None)

    def refresh(self):
        if self._loading or self._busy:
            return
        if not DriverBackupService.is_supported_platform():
            self._empty_text = ("Yalnızca Windows'ta çalışır", "Sürücü yedekleme Windows'un kendi komutlarını kullanır.")
            self._fill_table([])
            self._set_controls_enabled(False)
            self.problem_label.setText("Bu özellik yalnızca Windows'ta kullanılabilir.")
            self.status.setText("")
            return
        self._loading = True
        self._empty_text = ("Sürücüler okunuyor…", "Bu birkaç saniye sürebilir.")
        self._fill_table([])
        self.problem_label.setText("Taranıyor…")
        self.refresh_button.setEnabled(False)
        self._scan = _ScanWorker(self)
        self._scan.done.connect(self._on_scanned)
        self._scan.failed.connect(self._on_scan_failed)
        self._scan.start()
        self.refresh_usb_targets()

    def _on_scanned(self, drivers, problems):
        self._loading = False
        self._drivers = list(drivers or [])
        self._problems = list(problems or [])
        self._empty_text = (
            "Üçüncü taraf sürücü bulunamadı",
            "Bu bilgisayarda yedeklenecek OEM sürücü yok ya da liste okunamadı.",
        )
        self._fill_table(self._drivers)
        self._show_problems()
        self._set_controls_enabled(True)

    def _on_scan_failed(self, message):
        self._loading = False
        self._empty_text = ("Liste okunamadı", message)
        self._fill_table([])
        self.problem_label.setText("Taranamadı.")
        self._set_controls_enabled(True)

    def _fill_table(self, drivers):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(drivers))
        for row, d in enumerate(drivers):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Checked if d.selected else Qt.Unchecked)
            check.setData(Qt.UserRole, d.inf_name)
            self.table.setItem(row, 0, check)
            values = [d.display_name, d.provider, i18n.tr(d.class_name), d.version, d.date, d.inf_name]
            for col, text in enumerate(values, start=1):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self._apply_filter()
        self._update_summary()
        # tablo boşalıp dolunca boş durum yazısı güncellensin
        try:
            self._empty._sync()
        except Exception:
            pass

    def _apply_filter(self):
        needle = self.filter_edit.text().strip().lower()
        for row in range(self.table.rowCount()):
            haystack = " ".join(
                (self.table.item(row, c).text() if self.table.item(row, c) else "") for c in range(1, 7)
            ).lower()
            self.table.setRowHidden(row, bool(needle) and needle not in haystack)

    def _set_all_checked(self, checked: bool):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_summary()

    def _checked_infs(self) -> list[str]:
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                result.append(str(item.data(Qt.UserRole)))
        return result

    def selected_drivers(self) -> list[DriverInfo]:
        wanted = {inf.lower() for inf in self._checked_infs()}
        return [d for d in self._drivers if d.inf_name.lower() in wanted]

    def _update_summary(self):
        total = len(self._drivers)
        chosen = len(self._checked_infs())
        if total == 0:
            self.summary.setText("")
        else:
            text = f"{total} üçüncü taraf sürücü paketi bulundu · {chosen} seçili"
            need = self.estimated_need()
            if need > 0:
                text += f" · tahmini yedek boyutu ≈ {format_size(need)}"
            self.summary.setText(text)
        can = total > 0 and chosen > 0 and not self._busy
        self.backup_button.setEnabled(can)
        self.usb_button.setEnabled(can and bool(self._usb_targets) and self._usb_has_room())
        self.export_button.setEnabled(total > 0)
        self._update_usb_info()

    # Yedeğin kaplayacağı yer, boyutu ölçülen paketlerden tahmin edilir (küçük bir pay eklenir).
    SPACE_MARGIN = 1.1

    def estimated_need(self) -> int:
        total, _known = DriverBackupService.estimate_total(self.selected_drivers())
        return total

    def _usb_free(self) -> int | None:
        root = self.usb_combo.currentData() if self._usb_targets else None
        if not root:
            return None
        try:
            return DriverBackupService.check_free_space(Path(str(root)))[0]
        except OSError:
            return None

    def _usb_has_room(self) -> bool:
        need, free = self.estimated_need(), self._usb_free()
        return not (need > 0 and free is not None and free < need * self.SPACE_MARGIN)

    def _update_usb_info(self):
        need, free = self.estimated_need(), self._usb_free()
        if free is None:
            self.usb_info.setText("")
            return
        if need <= 0:
            self.usb_info.setText(f"USB'de boş alan: {format_size(free)}")
        elif free < need * self.SPACE_MARGIN:
            self.usb_info.setText(
                f"<span style='color:#C0392B'>Yer yetmiyor: yedek için yaklaşık {format_size(need)} gerekir, "
                f"USB'de {format_size(free)} boş alan var. Seçimi azaltın ya da daha büyük bir bellek kullanın.</span>"
            )
        else:
            self.usb_info.setText(f"Tahmini ihtiyaç ≈ {format_size(need)} · USB'de boş alan: {format_size(free)}")

    def _show_problems(self):
        if not self._problems:
            self.problem_label.setText("Sorunlu aygıt bulunmadı. Aygıt Yöneticisi'nde hata gösteren aygıt yok.")
            return
        real = [p for p in self._problems if p.driver_related]
        other = [p for p in self._problems if not p.driver_related]
        lines = []
        if real:
            lines.append(f"<b>{len(real)} aygıtta sürücü sorunu var:</b>")
            for p in real[:8]:
                lines.append(f"• {p.name} <span style='color:#8A98B0'>({p.class_name} · kod {p.code}: {p.reason})</span>")
            if len(real) > 8:
                lines.append(f"… ve {len(real) - 8} aygıt daha")
        if other:
            lines.append(f"<br>{len(other)} aygıt devre dışı ya da bağlı değil (sürücü sorunu sayılmaz).")
        self.problem_label.setText("<br>".join(lines))

    def _set_controls_enabled(self, enabled: bool):
        self.refresh_button.setEnabled(enabled and not self._busy)
        self.restore_button.setEnabled(enabled and not self._busy)
        self.select_all_btn.setEnabled(enabled)
        self.select_none_btn.setEnabled(enabled)
        self._update_summary()

    # ------------------------------------------------------------------ USB hedefleri
    def refresh_usb_targets(self):
        if not DriverBackupService.is_supported_platform():
            return
        worker = self._usb_worker
        if worker is not None and worker.isRunning():
            return
        self._usb_targets = []
        self.usb_combo.clear()
        self.usb_combo.addItem("USB bellek aranıyor...")
        self.usb_button.setEnabled(False)
        self._usb_worker = _UsbTargetWorker(self)
        self._usb_worker.done.connect(self._on_usb_targets)
        self._usb_worker.start()

    def _on_usb_targets(self, targets):
        self._usb_targets = list(targets or [])
        self.usb_combo.clear()
        if self._usb_targets:
            for label, root in self._usb_targets:
                self.usb_combo.addItem(label, str(root))
        else:
            self.usb_combo.addItem("USB bellek bulunamadı")
        self._update_summary()

    # ------------------------------------------------------------------ yedekleme
    def _browse_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Yedek nereye kaydedilsin?", self.dest_edit.text())
        if folder:
            self.dest_edit.setText(folder)

    def _browse_restore(self):
        folder = QFileDialog.getExistingDirectory(self, "Yedek klasörünü seçin", self.restore_edit.text() or self.dest_edit.text())
        if folder:
            self.restore_edit.setText(folder)

    def start_usb_backup(self):
        if not self._usb_targets:
            show_information(self, "USB bellek yok", "Önce kurulum USB belleğini takın ve USB aramasını yenileyin.")
            return
        root = self.usb_combo.currentData()
        if not root:
            return
        self._run_backup(Path(str(root)), to_usb=True)

    def start_backup(self):
        text = self.dest_edit.text().strip()
        if not text:
            show_information(self, "Hedef klasör", "Yedeğin kaydedileceği klasörü seçin.")
            return
        self._run_backup(Path(text), to_usb=False)

    def _run_backup(self, dest: Path, *, to_usb: bool):
        if self._busy:
            return
        drivers = self.selected_drivers()
        if not drivers:
            show_information(self, "Sürücü seçin", "Yedeklenecek en az bir sürücü işaretleyin.")
            return
        if not dest.exists():
            show_error(self, "Hedef bulunamadı", f"Hedef klasör yok:\n{dest}")
            return
        try:
            free, warning = DriverBackupService.check_free_space(dest)
        except OSError as exc:
            show_error(self, "Hedef okunamadı", str(exc))
            return
        need, _known = DriverBackupService.estimate_total(drivers)
        if need > 0 and free < need * self.SPACE_MARGIN:
            show_error(
                self, "Yeterli yer yok",
                f"Seçili sürücülerin yedeği yaklaşık {format_size(need)} tutar, hedefte yalnızca {format_size(free)} boş alan var.\n"
                "Seçimi azaltın ya da başka bir hedef seçin.",
            )
            return
        message = (
            f"{len(drivers)} sürücü paketi şuraya yedeklenecek:\n{dest}\n\n"
            + (f"Tahmini boyut: ≈ {format_size(need)} · hedefte boş alan: {format_size(free)}\n\n" if need > 0 else "")
            + "Yönetici izni penceresi (UAC) açılacak. İzin vermezseniz işlem yapılmaz."
        )
        if need > 0:
            warning = None  # ölçülmüş tahmin varken genel uyarıya gerek yok
        if warning:
            message += f"\n\nDikkat: {warning}"
        if not ask_confirmation(self, "Sürücüleri yedekle", message, confirm_text="Yedeklemeyi Başlat"):
            return
        self._set_busy(True, "Yönetici izni bekleniyor…")
        self.progress.setRange(0, len(drivers))
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self._backup = _BackupWorker(drivers, dest, self)
        self._backup.progress.connect(self._on_backup_progress)
        self._backup.done.connect(self._on_backup_done)
        self._backup.failed.connect(self._on_backup_failed)
        self._backup.start()

    def _on_backup_progress(self, index, total, inf):
        self.progress.setRange(0, total)
        self.progress.setValue(index)
        self.status.setText(f"Yedekleniyor… {index}/{total}  ({inf})")

    def _cancel_backup(self):
        if self._backup is not None and self._backup.isRunning():
            self._backup.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("İptal ediliyor… geçerli sürücü bitince durur.")

    def _on_backup_done(self, result: BackupResult):
        self._set_busy(False, "")
        self.progress.hide()
        self.cancel_button.hide()
        self.cancel_button.setEnabled(True)
        size = format_size(result.size_bytes)
        if result.cancelled:
            self.status.setText(f"İptal edildi. {result.ok} sürücü yedeklendi.")
            show_warning(self, "Yedekleme iptal edildi", f"{result.ok}/{result.total} sürücü yedeklendi.\n\n{result.folder}")
            return
        if result.ok == 0:
            self.status.setText("Hiçbir sürücü yedeklenemedi.")
            show_error(
                self, "Yedekleme başarısız",
                "Hiçbir sürücü yedeklenemedi. Yönetici izni verdiğinizden ve hedefte boş alan olduğundan emin olun.",
            )
            return
        self.status.setText(f"Tamamlandı: {result.ok} sürücü · {size}")
        text = f"{result.ok}/{result.total} sürücü yedeklendi ({size}).\n\n{result.folder}"
        if result.failed:
            text += f"\n\nYedeklenemeyen {len(result.failed)} paket: " + ", ".join(result.failed[:10])
            show_warning(self, "Yedekleme tamamlandı (uyarılarla)", text)
        else:
            text += "\n\nYeni kurulumdan sonra klasördeki 'Suruculeri_Geri_Yukle.bat' dosyasına çift tıklayın ya da bu sayfadan geri yükleyin."
            show_success(self, "Yedekleme tamamlandı", text)

    def _on_backup_failed(self, message):
        self._set_busy(False, "")
        self.progress.hide()
        self.cancel_button.hide()
        self.cancel_button.setEnabled(True)
        self.status.setText("Yedekleme başarısız.")
        show_error(self, "Yedekleme başarısız", message)

    # ------------------------------------------------------------------ geri yükleme
    def start_restore(self):
        if self._busy:
            return
        text = self.restore_edit.text().strip()
        if not text or not Path(text).is_dir():
            show_information(self, "Yedek klasörü", "Geri yüklenecek yedek klasörünü seçin.")
            return
        source = Path(text)
        from services.driver_backup_service import count_inf_files
        drivers_dir = source / "Drivers" if (source / "Drivers").is_dir() else source
        count = count_inf_files(drivers_dir)
        if count == 0:
            show_error(self, "Sürücü bulunamadı", "Seçilen klasörde .inf sürücü dosyası yok.")
            return
        message = (
            f"{count} sürücü bilgi dosyası (.inf) bu klasörden yüklenecek:\n{source}\n\n"
            "Yanlış sürücü yüklemek sistemi etkileyebilir. Yedek bu bilgisayardan alınmadıysa devam etmeyin.\n"
            "Yönetici izni penceresi (UAC) açılacak."
        )
        if not self.restore_point_check.isChecked():
            message += "\n\nGeri yükleme noktası oluşturma kapalı."
        if not ask_confirmation(self, "Sürücüleri geri yükle", message, confirm_text="Geri Yükle"):
            return
        self._set_busy(True, "Sürücüler yükleniyor… (birkaç dakika sürebilir)")
        self.progress.setRange(0, 0)  # belirsiz ilerleme
        self.progress.show()
        self.restore_log.clear()
        self.restore_log.hide()
        self._restore = _RestoreWorker(source, self.restore_point_check.isChecked(), self)
        self._restore.done.connect(self._on_restore_done)
        self._restore.failed.connect(self._on_restore_failed)
        self._restore.start()

    def _on_restore_done(self, ok, reboot, summary, detail):
        self._set_busy(False, "")
        self.progress.hide()
        self.progress.setRange(0, 100)
        self.status.setText(summary)
        if detail:
            self.restore_log.setPlainText(detail)
            self.restore_log.show()
        point_failed = "olusturulamadi" in (detail or "")
        text = summary
        if point_failed and self.restore_point_check.isChecked():
            text += "\n\nGeri yükleme noktası oluşturulamadı (Sistem Koruması kapalı olabilir). Sürücüler yine de yüklendi."
        if ok:
            show_success(self, "Geri yükleme tamamlandı", text)
        else:
            show_error(self, "Geri yükleme tamamlanamadı", text + "\n\nAyrıntılar sayfadaki günlükte.")
        self.refresh()

    def _on_restore_failed(self, message):
        self._set_busy(False, "")
        self.progress.hide()
        self.progress.setRange(0, 100)
        self.status.setText("Geri yükleme başarısız.")
        show_error(self, "Geri yükleme başarısız", message)

    # ------------------------------------------------------------------ ortak
    def _set_busy(self, busy: bool, status: str):
        self._busy = busy
        self.status.setText(status)
        for w in (self.refresh_button, self.restore_button, self.usb_refresh, self.select_all_btn, self.select_none_btn):
            w.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self._update_summary()

    def shutdown(self):
        """Kapanışta devam eden yedeklemeyi nazikçe iptal eder."""
        worker = self._backup
        if worker is not None and worker.isRunning():
            worker.cancel()
