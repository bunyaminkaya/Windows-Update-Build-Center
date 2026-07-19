from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QSizePolicy, QStyle, QSystemTrayIcon, QMenu, QApplication
)

from app.version import APP_NAME, APP_VERSION
from app.paths import ICON_DIR
from ui.pages.home_page import HomePage
from ui.pages.simple_page import SimplePage
from ui.pages.download_manager_page import DownloadManagerPage
from ui.pages.uup_center_page import UupCenterPage
from ui.pages.kb_updates_page import KbUpdatesPage
from ui.pages.settings_page import SettingsPage
from ui.pages.about_page import AboutPage
from ui.pages.usb_install_page import UsbInstallPage
from services.download_manager import DownloadManager
from services.iso_build_manager import IsoBuildManager
from services.settings_service import SettingsService
import logging
import ctypes
import sys

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1440, 900)
        self.setMinimumSize(1120, 720)

        icon_path = ICON_DIR / "app_logo.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._force_quit = False
        self._tray_notice_shown = False
        self._tray_icon = None
        # Windows API ile yüklenen HICON handle'larını pencere ömrü boyunca
        # sakla; aksi halde görev çubuğu simgesi bazı sistemlerde kaybolabilir.
        self._native_icon_handles = []

        central = QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")

        root.addWidget(self._build_sidebar())
        root.addWidget(self.stack, 1)

        self.settings = SettingsService.load()
        self._setup_tray()
        page_specs = [
            ("Microsoft Güncelleme Merkezi", HomePage()),
            ("Windows Build Tracker", KbUpdatesPage()),
            ("UUP Merkezi", UupCenterPage()),
            ("İndirme Yöneticisi", DownloadManagerPage()),
            ("USB Kurulum Merkezi", UsbInstallPage()),
            ("Ayarlar", SettingsPage()),
            ("Hakkında", AboutPage()),
        ]
        self.page_names = [name for name, _ in page_specs]
        for _, page in page_specs:
            self.stack.addWidget(page)

        self._apply_styles()
        download_manager = DownloadManager.instance()
        download_manager.set_max_concurrent(
            self.settings.get("downloads", {}).get("max_concurrent", 3)
        )
        settings_page = self.page_by_name("Ayarlar")
        if settings_page is not None and hasattr(settings_page, "settings_saved"):
            settings_page.settings_saved.connect(self._apply_runtime_settings)

        start_page = "Microsoft Güncelleme Merkezi"
        general = self.settings.get("general", {})
        if general.get("open_last_page", True):
            candidate = general.get("last_page", start_page)
            if candidate in self.page_names:
                start_page = candidate
        self.show_page_by_name(start_page)
        iso_manager = IsoBuildManager.instance()
        download_manager.request_open_manager.connect(
            lambda: self.show_page_by_name("İndirme Yöneticisi")
        )
        download_manager.batch_completed.connect(
            self._on_download_batch_completed
        )
        QTimer.singleShot(1200, self._resume_completed_iso_batches)

    def apply_native_windows_icon(self) -> None:
        """Force the application icon onto the native Windows window handle.

        QApplication/QMainWindow ikonları çoğu durumda yeterlidir; ancak uygulama
        python.exe üzerinden çalıştırıldığında Windows 10/11 görev çubuğu bazen
        host executable ikonunu veya boş/generic bir ikonu kullanabilir. WM_SETICON
        ve pencere sınıfı ikonlarını birlikte ayarlamak bu durumu giderir.
        """
        if sys.platform != "win32":
            return

        icon_path = ICON_DIR / "app_logo.ico"
        if not icon_path.exists():
            logger.warning("Görev çubuğu ikonu bulunamadı: %s", icon_path)
            return

        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32

            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            GCLP_HICON = -14
            GCLP_HICONSM = -34

            load_image = user32.LoadImageW
            load_image.restype = ctypes.c_void_p

            big_icon = load_image(
                None, str(icon_path), IMAGE_ICON, 256, 256, LR_LOADFROMFILE
            )
            small_icon = load_image(
                None, str(icon_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE
            )
            if not big_icon:
                big_icon = load_image(
                    None, str(icon_path), IMAGE_ICON, 0, 0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE,
                )
            if not small_icon:
                small_icon = big_icon

            if big_icon:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big_icon)
                self._native_icon_handles.append(big_icon)
            if small_icon:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small_icon)
                if small_icon != big_icon:
                    self._native_icon_handles.append(small_icon)

            set_class_long = getattr(user32, "SetClassLongPtrW", None)
            if set_class_long is None:
                set_class_long = user32.SetClassLongW
            if big_icon:
                set_class_long(hwnd, GCLP_HICON, big_icon)
            if small_icon:
                set_class_long(hwnd, GCLP_HICONSM, small_icon)

            # Qt tarafındaki icon özelliğini de tekrar uygula.
            self.setWindowIcon(QIcon(str(icon_path)))
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(QIcon(str(icon_path)))

            logger.info("Windows görev çubuğu ikonu uygulandı: %s", icon_path)
        except Exception:
            logger.exception("Windows görev çubuğu ikonu uygulanamadı")

    def _on_download_batch_completed(self, batch_id: str, metadata):
        """Start ISO conversion when a UUP download batch finishes."""
        meta = dict(metadata or {})
        if meta.get("batch_kind") != "uup_iso":
            return

        project_dir = meta.get("project_dir", "")
        uup_dir = meta.get("uup_dir", "")
        if not project_dir or not uup_dir:
            return

        IsoBuildManager.instance().start_build(batch_id, meta)

    def _resume_completed_iso_batches(self):
        """Resume ISO creation for completed UUP batches after app restart."""
        download_manager = DownloadManager.instance()
        iso_manager = IsoBuildManager.instance()

        for batch_id, metadata in download_manager.completed_batches("uup_iso"):
            meta = dict(metadata or {})
            project_dir = meta.get("project_dir", "")
            uup_dir = meta.get("uup_dir", "")
            if not project_dir or not uup_dir:
                continue
            iso_manager.start_build(batch_id, meta)

    def _build_sidebar(self):
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(286)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(8)

        # Ürün kimliği kartı
        brand_card = QFrame()
        brand_card.setObjectName("brandCard")
        brand_layout = QHBoxLayout(brand_card)
        brand_layout.setContentsMargins(14, 14, 14, 14)
        brand_layout.setSpacing(12)

        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setFixedSize(58, 58)
        logo.setAlignment(Qt.AlignCenter)
        png = ICON_DIR / "app_logo.png"
        if png.exists():
            logo.setPixmap(
                QPixmap(str(png)).scaled(
                    56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 1, 0, 0)
        text_box.setSpacing(3)
        title = QLabel("Windows Update &\nBuild Center")
        title.setObjectName("brandTitle")
        subtitle = QLabel("Microsoft Update • UUP • Build")
        subtitle.setObjectName("brandSubtitle")
        subtitle.setWordWrap(True)
        text_box.addWidget(title)
        text_box.addWidget(subtitle)
        text_box.addStretch()

        brand_layout.addWidget(logo, 0, Qt.AlignTop)
        brand_layout.addLayout(text_box, 1)
        layout.addWidget(brand_card)
        layout.addSpacing(8)

        self.nav_buttons = []

        def add_group_label(text):
            label = QLabel(text)
            label.setObjectName("navGroupLabel")
            layout.addWidget(label)

        def add_nav(name, index, icon):
            btn = QPushButton(icon, name)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(48)
            btn.clicked.connect(lambda checked=False, page_index=index: self._show_page(page_index))
            layout.addWidget(btn)
            self.nav_buttons.append(btn)

        style = self.style()
        add_group_label("ANA MENÜ")
        add_nav("Microsoft Güncelleme Merkezi", 0, style.standardIcon(QStyle.SP_ComputerIcon))
        add_nav("Windows Build Tracker", 1, style.standardIcon(QStyle.SP_FileDialogContentsView))
        add_nav("UUP Merkezi", 2, style.standardIcon(QStyle.SP_DriveHDIcon))
        add_nav("İndirme Yöneticisi", 3, style.standardIcon(QStyle.SP_ArrowDown))
        add_nav("USB Kurulum Merkezi", 4, style.standardIcon(QStyle.SP_DriveFDIcon))

        layout.addSpacing(14)
        add_group_label("SİSTEM")
        add_nav("Ayarlar", 5, style.standardIcon(QStyle.SP_FileDialogDetailedView))
        add_nav("Hakkında", 6, style.standardIcon(QStyle.SP_MessageBoxInformation))

        layout.addStretch(1)

        footer = QFrame()
        footer.setObjectName("sidebarFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 10, 14, 10)
        footer_layout.setSpacing(8)
        status_dot = QLabel("●")
        status_dot.setObjectName("statusDot")
        version = QLabel(APP_VERSION)
        version.setObjectName("versionLabel")
        footer_layout.addWidget(status_dot)
        footer_layout.addWidget(version)
        footer_layout.addStretch()
        layout.addWidget(footer)

        return panel

    def _show_page(self, index):
        if not (0 <= index < self.stack.count()):
            return
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        try:
            settings = SettingsService.load()
            if settings.get("general", {}).get("open_last_page", True):
                settings.setdefault("general", {})["last_page"] = self.page_names[index]
                SettingsService.save(settings)
                self.settings = settings
        except Exception as exc:
            logger.exception("Son kullanılan sayfa kaydedilemedi: %s", exc)

    def _apply_runtime_settings(self, settings):
        self.settings = dict(settings or {})
        DownloadManager.instance().set_max_concurrent(
            self.settings.get("downloads", {}).get("max_concurrent", 3)
        )
        tracker_page = self.page_by_name("Windows Build Tracker")
        if tracker_page is not None and hasattr(tracker_page, "apply_settings"):
            tracker_page.apply_settings(self.settings)
        uup_page = self.page_by_name("UUP Merkezi")
        if uup_page is not None and hasattr(uup_page, "apply_settings"):
            uup_page.apply_settings(self.settings)

    def show_page_by_name(self, page_name: str) -> bool:
        try:
            index = self.page_names.index(page_name)
        except ValueError:
            return False
        self._show_page(index)
        return True

    def page_by_name(self, page_name: str):
        try:
            index = self.page_names.index(page_name)
        except ValueError:
            return None
        return self.stack.widget(index)

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self)
        tray.setIcon(self.windowIcon())
        tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        show_action = QAction("Programı Göster", self)
        quit_action = QAction("Çıkış", self)
        show_action.triggered.connect(self._restore_from_tray)
        quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None
        )
        self._tray_icon = tray
        general = self.settings.get("general", {})
        if general.get("run_in_background", False):
            tray.show()

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._force_quit = True
        if self._tray_icon is not None:
            self._tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event):
        general = self.settings.get("general", {})
        keep_running = bool(
            general.get("run_in_background", False)
            or general.get("minimize_to_tray", False)
        )
        if keep_running and not self._force_quit and self._tray_icon is not None:
            event.ignore()
            self.hide()
            self._tray_icon.show()
            if not self._tray_notice_shown:
                self._tray_icon.showMessage(
                    APP_NAME,
                    "Program arka planda çalışmaya devam ediyor. Çıkmak için tepsi simgesindeki menüyü kullanın.",
                    QSystemTrayIcon.Information,
                    4000,
                )
                self._tray_notice_shown = True
            return
        super().closeEvent(event)

    def _apply_styles(self):
        self.setStyleSheet(
            '''
            QMainWindow#mainWindow {
                background: #F5F8FC;
            }
            QWidget {
                color: #14213D;
                font-family: "Segoe UI";
                font-size: 14px;
                background: transparent;
            }
            QWidget#centralRoot, QStackedWidget#pageStack {
                background: #F5F8FC;
            }
            QLabel {
                background: transparent;
                border: none;
            }

            QFrame#sidebar {
                background: #0E223D;
                border-right: 1px solid #213B5B;
            }
            QFrame#brandCard {
                background: #102A49;
                border: 1px solid #294768;
                border-radius: 12px;
            }
            QLabel#brandLogo {
                background: transparent;
                border: none;
            }
            QLabel#brandTitle {
                color: #FFFFFF;
                font-size: 16px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#brandSubtitle {
                color: #9FB0C5;
                font-size: 11px;
                background: transparent;
            }
            QLabel#navGroupLabel {
                color: #91A9C4;
                font-size: 10px;
                font-weight: 700;
                padding: 4px 10px 2px 10px;
                letter-spacing: 1px;
            }
            QPushButton#navButton {
                text-align: left;
                padding: 10px 14px;
                border: 1px solid #284564;
                border-radius: 9px;
                color: #E5EDF7;
                background: #102945;
                font-size: 13px;
                font-weight: 500;
                icon-size: 22px;
            }
            QPushButton#navButton:hover {
                background: #17385D;
                border-color: #3D6288;
            }
            QPushButton#navButton:checked {
                background: #2167D5;
                border-color: #3A7DE3;
                color: #FFFFFF;
                font-weight: 700;
            }
            QFrame#sidebarFooter {
                background: #102945;
                border: 1px solid #284564;
                border-radius: 8px;
            }
            QLabel#statusDot {
                color: #39C879;
                font-size: 11px;
            }
            QLabel#versionLabel {
                color: #A9B8CA;
                font-size: 12px;
            }

            QLabel#pageTitle {
                font-size: 28px;
                font-weight: 700;
                color: #0B1736;
                background: transparent;
            }
            QLabel#pageSubtitle {
                color: #65728A;
                font-size: 14px;
                background: transparent;
            }

            QFrame#searchCard, QFrame#statCard {
                background: #FFFFFF;
                border: 1px solid #DCE5F0;
                border-radius: 12px;
            }
            QFrame#statCard {
                min-height: 86px;
            }
            QLabel#statTitle {
                color: #65728A;
                font-size: 12px;
                background: transparent;
            }
            QLabel#statValue {
                color: #0B1736;
                font-size: 24px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#statNote {
                color: #8A96A8;
                font-size: 11px;
                background: transparent;
            }

            QLineEdit, QComboBox {
                background: #FFFFFF;
                border: 1px solid #C9D5E4;
                border-radius: 8px;
                padding: 9px 12px;
                min-height: 24px;
                selection-background-color: #2167D5;
                color: #14213D;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #2167D5;
            }
            QComboBox {
                padding: 9px 34px 9px 12px;
            }
            QComboBox::drop-down {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 30px;
                border: 0px;
                background: transparent;
                margin: 0px;
                padding: 0px;
            }
            QComboBox::down-arrow {
                width: 9px;
                height: 9px;
                margin-right: 10px;
            }
            QComboBox:on {
                border: 1px solid #2167D5;
                border-radius: 8px;
                background: #FFFFFF;
            }
            QComboBox[popupOpen="true"] {
                border: 1px solid #2167D5;
                border-radius: 8px;
                background: #FFFFFF;
            }
            QWidget#modernComboPopup {
                background: transparent;
                border: none;
            }
            QListWidget#modernComboPopupList {
                background: transparent;
                border: none;
                outline: none;
                padding: 4px;
                color: #14213D;
            }
            QListWidget#modernComboPopupList::item {
                min-height: 28px;
                padding: 6px 10px;
                margin: 1px 2px;
                border: none;
                border-radius: 7px;
                color: #14213D;
                background: transparent;
            }
            QListWidget#modernComboPopupList::item:hover {
                background: #EEF4FF;
                color: #0B1736;
            }
            QListWidget#modernComboPopupList::item:selected {
                background: #2167D5;
                color: #FFFFFF;
            }
            QListWidget#modernComboPopupList QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 7px 3px 7px 0;
            }
            QListWidget#modernComboPopupList QScrollBar::handle:vertical {
                background: #C3D2E7;
                min-height: 26px;
                border-radius: 4px;
            }
            QListWidget#modernComboPopupList QScrollBar::add-line:vertical,
            QListWidget#modernComboPopupList QScrollBar::sub-line:vertical,
            QListWidget#modernComboPopupList QScrollBar::add-page:vertical,
            QListWidget#modernComboPopupList QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
            }

            QPushButton {
                background: #2167D5;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-weight: 600;
                min-height: 22px;
            }
            QPushButton:hover {
                background: #185ABE;
            }
            QPushButton:disabled {
                background: #D9DEE6;
                color: #8F99A8;
            }
            QPushButton#dangerButton {
                background: #FFFFFF;
                color: #E53935;
                border: 1px solid #EF5350;
            }
            QPushButton#dangerButton:hover {
                background: #FFF4F4;
            }

            QLabel#infoBox {
                background: #EAF2FF;
                border: 1px solid #C8DFFF;
                border-radius: 8px;
                padding: 12px;
                color: #31537B;
            }
            QLabel#subtleInfoBox {
                background: #F7FAFF;
                border: 1px solid #D9E6F7;
                border-radius: 8px;
                padding: 10px 12px;
                color: #5B6E88;
            }
            QTableWidget, QTableView, QListWidget {
                outline: none;
            }
            QTableWidget {
                background: white;
                border: 1px solid #DDE5F0;
                border-radius: 10px;
                gridline-color: #E7EEF7;
                alternate-background-color: #F8FBFF;
                selection-background-color: #DDEBFF;
                selection-color: #0B1736;
                show-decoration-selected: 1;
            }
            QHeaderView::section {
                background: #EDF4FD;
                color: #16345F;
                border: none;
                border-right: 1px solid #D8E4F2;
                border-bottom: 1px solid #D8E4F2;
                padding: 8px;
                font-weight: 600;
            }

            QTableWidget::item {
                padding: 7px 8px;
                border: none;
            }
            QTableWidget::item:hover {
                background: #F4F8FF;
            }
            QTableWidget::item:selected {
                background: #DDEBFF;
                color: #16345F;
                border: none;
            }
            QTableWidget::item:selected:active {
                background: #DDEBFF;
                color: #16345F;
                border: none;
            }
            QTableWidget::item:selected:!active {
                background: #DDEBFF;
                color: #16345F;
                border: none;
            }
            QTableWidget::item:focus,
            QTableView::item:focus,
            QListWidget::item:focus {
                outline: none;
                border: none;
            }
            QTableCornerButton::section {
                background: #EDF4FD;
                border: none;
                border-right: 1px solid #D8E4F2;
                border-bottom: 1px solid #D8E4F2;
            }
            QProgressBar#downloadProgress {
                background: #ECF2FA;
                border: 1px solid #D5E1EF;
                border-radius: 7px;
                text-align: center;
                color: white;
                font-weight: 700;
            }
            QProgressBar#downloadProgress::chunk {
                background-color: #2167D5;
                border-radius: 6px;
            }

            QMenu {
                background-color: #FFFFFF;
                color: #14213D;
                border: 1px solid #C9D5E5;
                border-radius: 6px;
                padding: 5px;
            }
            QMenu::item {
                background-color: transparent;
                color: #14213D;
                padding: 7px 28px 7px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1E67D8;
                color: #FFFFFF;
            }
            QMenu::item:disabled {
                color: #98A4B5;
            }
            QMenu::separator {
                height: 1px;
                background: #E2E9F2;
                margin: 5px 8px;
            }
            
            QFrame#detailPanel {
                background: #FFFFFF;
                border: 1px solid #D8E4F2;
                border-radius: 10px;
            }
            QLabel#detailTitle {
                color: #0B1736;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#detailName {
                color: #16345F;
                font-size: 15px;
                font-weight: 600;
                padding-bottom: 6px;
            }
            QLabel#detailMeta {
                color: #5C6F89;
                font-size: 13px;
                padding: 2px 0;
            }
            QFrame#detailMetadataGrid {
                background: transparent;
                border: none;
            }
            QFrame#detailMetaCard {
                background: #F7FAFF;
                border: 1px solid #DFE8F4;
                border-radius: 8px;
                min-height: 44px;
            }
            QLabel#detailMetaCaption {
                color: #7A899D;
                font-size: 11px;
                font-weight: 500;
                background: transparent;
            }
            QLabel#detailMetaValue {
                color: #17365D;
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }
            QSplitter::handle {
                background: #E5ECF5;
                width: 4px;
            }

            QMessageBox {
                background-color: #FFFFFF;
                color: #14213D;
            }
            QMessageBox QLabel {
                background: transparent;
                color: #14213D;
                min-width: 360px;
            }
            QMessageBox QPushButton {
                background: #1E67D8;
                color: #FFFFFF;
                border: none;
                border-radius: 7px;
                padding: 8px 18px;
                min-width: 90px;
            }
            QMessageBox QPushButton:hover {
                background: #185ABE;
            }

            QLabel#detailSectionTitle {
                color: #0B1736;
                font-size: 15px;
                font-weight: 700;
                margin-top: 8px;
            }
            QListWidget#packageList {
                background: #F8FBFF;
                border: 1px solid #D8E4F2;
                border-radius: 8px;
                color: #14213D;
                outline: none;
            }
            QListWidget#packageList::item {
                background: #FFFFFF;
                border-bottom: 1px solid #E5ECF5;
                padding: 10px;
                color: #14213D;
                border-radius: 6px;
            }
            QListWidget#packageList::item:hover {
                background: #EEF4FF;
            }
            QListWidget#packageList::item:selected {
                background: #DDEBFF;
                color: #16345F;
                border: 1px solid #BFD6F6;
            }

            QFrame#packageInfoCard {
                background: #F8FBFF;
                border: 1px solid #D8E4F2;
                border-radius: 8px;
            }
            QLabel#packageFileLabel {
                color: #243B5A;
                font-size: 12px;
                background: transparent;
            }
            QLabel#packageLinkStatus {
                color: #315F9A;
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }

            QScrollArea#detailScroll {
                background: #FFFFFF;
                border: none;
            }
            QWidget#detailScrollContent {
                background: #FFFFFF;
            }
            QFrame#detailFooter {
                background: #FFFFFF;
                border-top: 1px solid #E0E8F2;
            }
            QLabel#packageInfoTitle {
                color: #0B1736;
                font-size: 12px;
                font-weight: 700;
                background: transparent;
            }
            QFrame#packageInfoCard {
                background: #F6FAFF;
                border: 1px solid #D9E5F3;
                border-radius: 8px;
            }
            QFrame#packageWorkspace {
                background: transparent;
                border: none;
            }
            QFrame#packageQuickCard {
                background: #FFFFFF;
                border: 1px solid #DCE7F4;
                border-radius: 6px;
            }
            QLabel#packageQuickCaption {
                color: #8190A5;
                font-size: 10px;
                background: transparent;
            }
            QLabel#packageQuickValue {
                color: #17365D;
                font-size: 11px;
                font-weight: 600;
                background: transparent;
            }

            QLabel#isoCurrentStatus {
                color: #17365D;
                font-size: 13px;
                font-weight: 600;
                background: #F6F9FE;
                border: 1px solid #D9E6F7;
                border-radius: 7px;
                padding: 8px 10px;
            }
            QLabel#isoInfoLabel {
                color: #60738E;
                font-size: 11px;
            }
            QLabel#isoStagePending {
                color: #7C8CA1;
                background: #F4F7FB;
                border: 1px solid #E0E8F3;
                border-radius: 7px;
                padding: 5px 7px;
                font-size: 10px;
                font-weight: 600;
            }
            QLabel#isoStageActive {
                color: #FFFFFF;
                background: #246BCE;
                border: 1px solid #246BCE;
                border-radius: 7px;
                padding: 5px 7px;
                font-size: 10px;
                font-weight: 700;
            }
            QLabel#isoStageDone {
                color: #176B3A;
                background: #EAF7EF;
                border: 1px solid #BDE3CA;
                border-radius: 7px;
                padding: 5px 7px;
                font-size: 10px;
                font-weight: 700;
            }
            QTextEdit#isoLogView {
                background: #0F172A;
                color: #DCE7F7;
                border: 1px solid #26354C;
                border-radius: 8px;
                padding: 8px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 10px;
                selection-background-color: #246BCE;
            }
'''

        )

