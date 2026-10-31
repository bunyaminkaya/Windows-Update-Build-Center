from PySide6.QtCore import Qt, QTimer, QDateTime, QSize, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap, QAction, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QSizePolicy, QStyle, QSystemTrayIcon, QMenu, QApplication
)

from app import startup_timing
from app.version import APP_NAME, APP_VERSION
from app.paths import ICON_DIR
from ui import icons, styles, theme
from ui.pages.home_page import HomePage
from ui.pages.iso_center_page import IsoCenterPage
from ui.widgets.nav_button import NavButton
from ui.pages.simple_page import SimplePage
from ui.pages.download_manager_page import DownloadManagerPage
from ui.pages.uup_center_page import UupCenterPage
from ui.pages.kb_updates_page import KbUpdatesPage
from ui.pages.compatibility_page import CompatibilityPage
from ui.pages.installed_updates_page import InstalledUpdatesPage
from ui.pages.update_history_page import UpdateHistoryPage
from ui.pages.settings_page import SettingsPage
from ui.pages.about_page import AboutPage
from ui.pages.help_page import HelpPage
from ui.pages.usb_install_page import UsbInstallPage
from ui.pages.driver_backup_page import DriverBackupPage
from ui.pages.favorites_page import FavoritesPage
from services.download_manager import DownloadManager
from services.iso_build_manager import IsoBuildManager
from services.settings_service import SettingsService, auto_create_iso_enabled
from services.build_watch_service import BuildWatchService
import logging
import ctypes
import sys
import time

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    _app_update_ready = Signal(object, bool)

    def __init__(self):
        super().__init__()
        self.skip_update_check = False
        self._app_update_ready.connect(self._on_app_update_ready)
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
        self._pending_notification_record = None
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
        # Bir sayfanın açılış sırasında oluşan istisnası bütün programı
        # görünmez biçimde sonlandırmamalı. Özellikle UUP/ISO ve Windows API
        # sayfaları farklı Windows sürümlerinde ek bağımlılıklarla karşılaşabilir.
        # Sayfalar güvenli biçimde oluşturulur; sorunlu bir sayfa yerine açıklayıcı
        # bir hata sayfası eklenir ve ana pencere yine açılır.
        page_specs = [
            ("Güncelleme Merkezi", HomePage),
            ("Windows Sürüm Takibi", KbUpdatesPage),
            ("Güncelleme Geçmişi", UpdateHistoryPage),
            ("Yüklü Güncellemeler", InstalledUpdatesPage),
            ("Favorilerim", FavoritesPage),
            ("Windows 11 Uyumluluğu", CompatibilityPage),
            ("UUP ISO Oluşturucu", UupCenterPage),
            ("İndirme Yöneticisi", DownloadManagerPage),
            ("ISO Merkezi", IsoCenterPage),
            ("USB Kurulum Aracı", UsbInstallPage),
            ("Sürücü Yedekleme", DriverBackupPage),
            ("Ayarlar", SettingsPage),
            ("Yardım", HelpPage),
            ("Hakkında", AboutPage),
        ]
        self.page_names = [name for name, _ in page_specs]
        self._page_errors = {}
        for name, page_factory in page_specs:
            _page_start = time.perf_counter()
            try:
                page = page_factory()
            except Exception as exc:
                self._page_errors[name] = str(exc)
                logger.exception("Sayfa başlatılamadı: %s", name)
                page = SimplePage(
                    name,
                    "Bu bölüm başlatılırken bir hata oluştu. Ana program çalışmaya devam ediyor.",
                )
                if hasattr(page, "set_error_details"):
                    page.set_error_details(str(exc))
            self.stack.addWidget(page)
            startup_timing.page_built(name, time.perf_counter() - _page_start)

        self._apply_styles()
        self._setup_shortcuts()
        download_manager = DownloadManager.instance()
        download_manager.apply_settings(self.settings.get("downloads", {}))
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown_background_work)
        settings_page = self.page_by_name("Ayarlar")
        if settings_page is not None and hasattr(settings_page, "settings_saved"):
            settings_page.settings_saved.connect(self._apply_runtime_settings)
        tracker_page = self.page_by_name("Windows Sürüm Takibi")
        if tracker_page is not None and hasattr(tracker_page, "new_records_found"):
            tracker_page.new_records_found.connect(self._on_new_tracker_records)
        iso_page = self.page_by_name("ISO Merkezi")
        if iso_page is not None and hasattr(iso_page, "send_to_usb"):
            iso_page.send_to_usb.connect(self._send_iso_to_usb)
        home_page = self.page_by_name("Güncelleme Merkezi")
        if home_page is not None and hasattr(home_page, "search_completed"):
            home_page.search_completed.connect(self._on_home_search_completed)
        self._refresh_download_badge()

        # Program her açılışta kullanıcının ana çalışma ekranına gelsin.
        self.show_page_by_name("Windows Sürüm Takibi")
        iso_manager = IsoBuildManager.instance()
        download_manager.request_open_manager.connect(
            lambda: self.show_page_by_name("İndirme Yöneticisi")
        )
        download_manager.batch_completed.connect(
            self._on_download_batch_completed
        )
        QTimer.singleShot(1200, self._resume_completed_iso_batches)

    def schedule_welcome_guide_on_start(self) -> None:
        """Ayarlarda "Açılışta karşılama rehberini göster" açıksa rehberi pencere oturunca gösterir."""
        try:
            enabled = bool(self.settings.get("general", {}).get("show_welcome_on_start", False))
        except Exception:
            enabled = False
        if enabled and not getattr(self, "_start_minimized", False) and not self.isMinimized():
            QTimer.singleShot(900, lambda: self.show_welcome_guide_if_needed(force=True))

    def show_welcome_guide_if_needed(self, force: bool = False) -> None:
        """İlk çalıştırmada 3 adımlık tanıtımı pencere içinde gösterir (bir kez)."""
        try:
            guide = getattr(self, "_welcome_guide", None)
            if guide is not None:
                try:
                    if guide.isVisible():
                        return
                except RuntimeError:
                    pass
            from services.settings_service import SettingsService
            settings = SettingsService.load()
            if not force and settings.get("onboarding", {}).get("welcome_shown"):
                logger.info("Karşılama rehberi atlandı: daha önce gösterilmiş.")
                return
            from ui.widgets.welcome_guide import show_welcome_guide

            def _mark_shown(_accepted=True):
                try:
                    SettingsService.update_value("onboarding", "welcome_shown", True)
                except Exception:
                    logger.exception("Rehber kaydı yazılamadı")

            self._welcome_guide = show_welcome_guide(self, _mark_shown)
        except Exception:
            logger.exception("Karşılama rehberi gösterilemedi")

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

        if auto_create_iso_enabled():
            IsoBuildManager.instance().start_build(batch_id, meta)
        else:
            # Otomatik oluşturma kapalı: İndirme Yöneticisi'ndeki ISO Oluşturma bölümü düğmeyi aktifleştirir.
            IsoBuildManager.instance().mark_ready(batch_id, meta)

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
            status = iso_manager.state(batch_id).get("status", "")
            if status in ("Hata", "İptal"):
                continue  # başarısız/iptal edilen işler kendiliğinden yeniden başlamaz; kullanıcı Yeniden Dene der
            if status == "Hazır" or auto_create_iso_enabled():
                iso_manager.start_build(batch_id, meta)
            else:
                iso_manager.mark_ready(batch_id, meta)

    def _build_sidebar(self):
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(286)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(3)

        # Ürün kimliği kartı
        brand_card = QFrame()
        brand_card.setObjectName("brandCard")
        brand_layout = QHBoxLayout(brand_card)
        brand_layout.setContentsMargins(13, 14, 12, 14)
        brand_layout.setSpacing(11)

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
        text_box.setContentsMargins(0, 2, 0, 0)
        text_box.setSpacing(3)
        title = QLabel("Windows Update &\nBuild Center")
        title.setObjectName("brandTitle")
        subtitle = QLabel("Bul. İndir. Hazırla. Kur.")
        subtitle.setObjectName("brandSubtitle")
        subtitle.setWordWrap(True)
        text_box.addWidget(title)
        text_box.addWidget(subtitle)
        text_box.addStretch()

        brand_layout.addWidget(logo, 0, Qt.AlignTop)
        brand_layout.addLayout(text_box, 1)
        brand_card.setMinimumHeight(92)
        layout.addWidget(brand_card)
        layout.addSpacing(10)

        self.nav_buttons = []

        def add_group_label(text):
            label = QLabel(
                '<span style="color:#2F7DF0; font-size:8px;">&#9670;</span>'
                f'&nbsp;&nbsp;{text}'
            )
            label.setTextFormat(Qt.RichText)
            label.setObjectName("navGroupLabel")
            layout.addWidget(label)

        def add_nav(name, index, icon_name):
            btn = NavButton(name, icon_name)
            btn.clicked.connect(lambda checked=False, page_index=index: self._show_page(page_index))
            layout.addWidget(btn)
            self.nav_buttons.append(btn)

        add_group_label("GÜNCELLEMELER")
        add_nav("Güncelleme Merkezi", 0, "windows-outline")
        add_nav("Windows Sürüm Takibi", 1, "shield")
        add_nav("Güncelleme Geçmişi", 2, "history")
        add_nav("Yüklü Güncellemeler", 3, "doc")
        add_nav("Favorilerim", 4, "star-fill")

        layout.addSpacing(10)
        divider = QFrame()
        divider.setObjectName("navDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(10)
        add_group_label("ARAÇLAR")
        add_nav("Windows 11 Uyumluluğu", 5, "monitor")
        add_nav("UUP ISO Oluşturucu", 6, "cloud")
        add_nav("İndirme Yöneticisi", 7, "download-tray")
        add_nav("ISO Merkezi", 8, "boxes")
        add_nav("USB Kurulum Aracı", 9, "usb")
        add_nav("Sürücü Yedekleme", 10, "cpu")

        layout.addSpacing(10)
        divider = QFrame()
        divider.setObjectName("navDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(10)
        add_group_label("SİSTEM")
        add_nav("Ayarlar", 11, "gear")
        add_nav("Yardım", 12, "info-outline")
        add_nav("Hakkında", 13, "info-fill")

        layout.addStretch(1)

        self.update_button = QPushButton("  Yeni sürüm mevcut")
        self.update_button.setObjectName("navUpdateButton")
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.setIcon(QIcon(icons.pixmap("download", "#7CE0A4", 44, stroke=2.1)))
        self.update_button.setIconSize(QSize(22, 22))
        self.update_button.setMinimumHeight(46)
        self.update_button.setProperty("themeExempt", True)
        self.update_button.setStyleSheet(
            "QPushButton#navUpdateButton { background: #14432A; color: #B5F5CF; border: 1px solid #2A8A55;"
            " border-radius: 10px; text-align: left; padding: 8px 14px; font-size: 13px; font-weight: 700; }"
            "QPushButton#navUpdateButton:hover { background: #1B5A38; color: #FFFFFF; border-color: #3DB070; }"
        )
        self.update_button.setVisible(False)
        self._update_url = ""
        self.update_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._update_url)) if self._update_url else None)
        layout.addWidget(self.update_button)

        self.help_button = QPushButton("  Bu sayfa nasıl kullanılır?")
        self.help_button.setObjectName("navHelpButton")
        self.help_button.setCursor(Qt.PointingHandCursor)
        self.help_button.setIcon(QIcon(icons.pixmap("info-outline", "#8EA6C6", 36, stroke=1.9)))
        self.help_button.setIconSize(QSize(16, 16))
        self.help_button.setToolTip("Bu sayfanın yardım bölümünü açar (F1)")
        self.help_button.setProperty("themeExempt", True)  # yan menüde, dönüştürülmez
        self.help_button.setStyleSheet(
            "QPushButton#navHelpButton { background: transparent; color: #8EA6C6; border: none;"
            " text-align: left; padding: 6px 14px; font-size: 12px; }"
            "QPushButton#navHelpButton:hover { color: #FFFFFF; }"
        )
        self.help_button.clicked.connect(self.open_page_help)
        layout.addWidget(self.help_button)

        footer = QFrame()
        footer.setObjectName("sidebarFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        footer_layout.setSpacing(12)
        status_dot = QLabel()
        status_dot.setObjectName("statusDot")
        status_dot.setFixedSize(12, 12)
        footer_text = QVBoxLayout()
        footer_text.setSpacing(2)
        version = QLabel(APP_VERSION)
        version.setObjectName("versionLabel")
        self.last_check_label = QLabel("Son kontrol: —")
        self.last_check_label.setObjectName("lastCheckLabel")
        footer_text.addWidget(version)
        footer_text.addWidget(self.last_check_label)
        footer_layout.addWidget(status_dot, 0, Qt.AlignVCenter)
        footer_layout.addLayout(footer_text, 1)
        layout.addWidget(footer)

        # İndirme Yöneticisi satırındaki rozet: devam eden / bekleyen indirmeler.
        self._badge_timer = QTimer(self)
        self._badge_timer.setInterval(1500)
        self._badge_timer.timeout.connect(self._refresh_download_badge)
        self._badge_timer.start()

        return panel

    def _apply_nav_density(self):
        """Düşük yükseklikte menü satırlarını sıkıştırır ki hiçbir öğe kesilmesin."""
        height = self.height()
        row_height = 44 if height >= 830 else (40 if height >= 770 else 36)
        if row_height == getattr(self, "_nav_row_height", None):
            return
        self._nav_row_height = row_height
        for button in getattr(self, "nav_buttons", []):
            button.setFixedHeight(row_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_nav_density()

    def _setup_shortcuts(self):
        """Klavye kısayolları: Ctrl+1…9 sayfalar, Ctrl+0 Ayarlar, Ctrl+F arama, F1 yardım."""
        from PySide6.QtGui import QKeySequence, QShortcut
        self._shortcuts = []

        def add(sequence, handler):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

        for number in range(1, 10):
            add(f"Ctrl+{number}", lambda index=number - 1: self._show_page(index))
        add("Ctrl+0", lambda: self.show_page_by_name("Ayarlar"))
        add("Ctrl+F", self.focus_page_search)
        add("F1", self.open_page_help)

    def focus_page_search(self):
        """Geçerli sayfadaki ilk kullanılabilir arama/metin kutusuna odaklanır."""
        from PySide6.QtWidgets import QLineEdit
        page = self.stack.currentWidget()
        if page is None:
            return
        for edit in page.findChildren(QLineEdit):
            if edit.isVisibleTo(page) and edit.isEnabled() and not edit.isReadOnly():
                edit.setFocus(Qt.ShortcutFocusReason)
                edit.selectAll()
                return

    def open_help(self, section: str | None = None) -> None:
        """Yardım sayfasını (verilirse ilgili bölümde) açar."""
        page = self.page_by_name("Yardım")
        if page is not None and section:
            page.show_section(section)
        self.show_page_by_name("Yardım")

    def open_page_help(self):
        try:
            name = self.page_names[self.stack.currentIndex()]
            self.open_help(name)
        except Exception:
            logger.exception("Yardım bağlantısı açılamadı")

    def _refresh_download_badge(self):
        try:
            counts = DownloadManager.instance().status_counts()
            active = (
                int(counts.get("running", 0))
                + int(counts.get("queued", 0))
                + int(counts.get("paused", 0))
            )
            self.nav_buttons[7].set_badge(active)
        except Exception:
            pass

    def _send_iso_to_usb(self, iso_path: str) -> None:
        """ISO Merkezi'nde seçilen ISO'yu USB Kurulum Aracı'nda açar."""
        usb_page = self.page_by_name("USB Kurulum Aracı")
        if usb_page is None or not hasattr(usb_page, "set_iso_path"):
            return
        self.show_page_by_name("USB Kurulum Aracı")
        usb_page.set_iso_path(iso_path)

    def _on_home_search_completed(self):
        self.last_check_label.setText(
            "Son kontrol: " + QDateTime.currentDateTime().toString("dd.MM.yyyy HH:mm")
        )

    def _show_page(self, index):
        if not (0 <= index < self.stack.count()):
            return
        self.stack.setCurrentIndex(index)
        if self.page_names[index] == "Windows Sürüm Takibi":
            self._unseen_tracker_records = 0
            self.nav_buttons[index].set_badge(0)
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
        DownloadManager.instance().apply_settings(self.settings.get("downloads", {}))
        tracker_page = self.page_by_name("Windows Sürüm Takibi")
        if tracker_page is not None and hasattr(tracker_page, "apply_settings"):
            tracker_page.apply_settings(self.settings)
        if self._tray_icon is not None:
            tracker = self.settings.get("build_tracker", {})
            general = self.settings.get("general", {})
            if tracker.get("notifications_enabled", True) or general.get("run_in_background", False):
                self._tray_icon.show()
            elif not general.get("minimize_to_tray", False):
                self._tray_icon.hide()
        uup_page = self.page_by_name("UUP ISO Oluşturucu")
        if uup_page is not None and hasattr(uup_page, "apply_settings"):
            uup_page.apply_settings(self.settings)

    LEGACY_PAGE_NAMES = {
        "Microsoft Güncelleme Merkezi": "Güncelleme Merkezi",
        "Windows Build Tracker": "Windows Sürüm Takibi",
        "Bilgisayar Uyumluluğu": "Windows 11 Uyumluluğu",
        "Yüklü KB'ler": "Yüklü Güncellemeler",
        "UUP Merkezi": "UUP ISO Oluşturucu",
        "USB Kurulum Merkezi": "USB Kurulum Aracı",
    }

    def show_page_by_name(self, page_name: str) -> bool:
        page_name = self.LEGACY_PAGE_NAMES.get(page_name, page_name)
        try:
            index = self.page_names.index(page_name)
        except ValueError:
            return False
        self._show_page(index)
        return True

    def page_by_name(self, page_name: str):
        page_name = self.LEGACY_PAGE_NAMES.get(page_name, page_name)
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
        tray.messageClicked.connect(self._open_tracker_notification)
        self._tray_icon = tray
        general = self.settings.get("general", {})
        # Bildirimlerin açık olması tek başına programı sistem tepsisine
        # gizlememeli. Tepsi simgesi yalnızca kullanıcı açıkça arka planda
        # çalışma veya tepsiye küçültme seçtiğinde gösterilir.
        if general.get("run_in_background", False) or general.get("minimize_to_tray", False):
            tray.show()

    # ── Program güncelleme denetimi ──
    def check_app_update_on_start(self) -> None:
        general = self.settings.get("general", {})
        if self.skip_update_check or not general.get("check_app_updates", True):
            return
        self.check_app_update(silent=True)

    def check_app_update(self, silent: bool = False) -> None:
        import threading
        from services.app_update_service import AppUpdateService

        def work():
            info = AppUpdateService.check()
            try:
                self._app_update_ready.emit(info, silent)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_app_update_ready(self, info, silent: bool) -> None:
        from ui.widgets.message_dialog import show_information
        if info.available:
            self._update_url = info.url
            self.update_button.setText(f"  Yeni sürüm mevcut\n  {info.latest} · indirmek için tıklayın")
            self.update_button.setToolTip((info.notes or "Yeni sürümü indirmek için tıklayın.") + "\n\nTıklayınca indirme sayfası açılır.")
            self.update_button.setVisible(True)
            if not silent:
                show_information(self, "Güncelleme", f"Yeni sürüm mevcut: {info.latest}\n\n{info.notes}".strip())
        elif not silent:
            if info.error:
                show_information(self, "Güncelleme", "Güncelleme denetimi şu anda yapılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.")
            else:
                show_information(self, "Güncelleme", f"Programınız güncel ({APP_VERSION}).")

    def send_test_notification(self) -> None:
        """Ayarlar'dan: bildirimin bu bilgisayarda görünüp görünmediğini denemek için."""
        if self._tray_icon is None:
            return
        self._tray_icon.show()
        self._tray_icon.showMessage(
            "Bildirim denemesi",
            "Yeni build yayımlandığında bildirimler bu şekilde görünecek.",
            QSystemTrayIcon.Information, 6000,
        )

    def _on_new_tracker_records(self, records) -> None:
        # Uygulama içi rozet: bildirimler kapalı olsa bile yeni kayıt sayısı görünür.
        try:
            tracker_index = self.page_names.index("Windows Sürüm Takibi")
            if self.stack.currentIndex() != tracker_index and records:
                self._unseen_tracker_records = getattr(self, "_unseen_tracker_records", 0) + len(list(records))
                self.nav_buttons[tracker_index].set_badge(self._unseen_tracker_records)
        except Exception:
            logger.exception("Sürüm Takibi rozeti güncellenemedi")
        tracker = self.settings.get("build_tracker", {})
        if not tracker.get("notifications_enabled", True):
            return
        incoming = list(records or [])
        if tracker.get("watchlist_enabled", False):
            matches = [record for record in incoming if BuildWatchService.matches(record, tracker)]
        else:
            allowed = set(tracker.get("notification_channels", []))
            matches = [record for record in incoming if record.channel in allowed]
        if not matches or self._tray_icon is None:
            return

        record = matches[0]
        self._pending_notification_record = record
        self._tray_icon.show()
        title = "Yeni Windows build yayımlandı" if len(matches) == 1 else f"{len(matches)} yeni Windows build yayımlandı"
        identity = record.kb_number or f"Build {record.build_number}"
        message = f"{identity} • Windows 11 {record.windows_version}\n{record.channel} • {record.build_number}"
        if len(matches) > 1:
            message += f"\nve {len(matches) - 1} yeni kayıt daha"
        self._tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 9000)

    def _open_tracker_notification(self) -> None:
        record = self._pending_notification_record
        self._restore_from_tray()
        self.show_page_by_name("Windows Sürüm Takibi")
        tracker_page = self.page_by_name("Windows Sürüm Takibi")
        if record is not None and tracker_page is not None and hasattr(tracker_page, "select_record"):
            tracker_page.select_record(record)

    def _restore_from_tray(self):
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowMaximized | Qt.WindowActive)
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def force_maximized_start(self) -> None:
        """Windows başlangıç kısayolundan gelen küçültülmüş durumu temizler."""
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowMaximized | Qt.WindowActive)
        self.showMaximized()
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
        self.setStyleSheet(styles.main_qss())
        if theme.is_dark():
            self._soften_sidebar_for_dark()

    def _shutdown_background_work(self) -> None:
        """Kapanışta tüm arka plan iş parçacıklarını düzgünce durdurur (aksi halde Qt süreci sonlandırır)."""
        try:
            DownloadManager.instance().shutdown()
        except Exception:
            logger.exception("İndirme yöneticisi kapatılamadı")
        try:
            IsoBuildManager.instance().shutdown()
        except Exception:
            logger.exception("ISO yöneticisi kapatılamadı")
        iso_page = self.page_by_name("ISO Merkezi")
        if iso_page is not None and hasattr(iso_page, "shutdown"):
            try:
                iso_page.shutdown()
            except Exception:
                logger.exception("ISO Merkezi kapatılamadı")
        driver_page = self.page_by_name("Sürücü Yedekleme")
        if driver_page is not None and hasattr(driver_page, "shutdown"):
            try:
                driver_page.shutdown()
            except Exception:
                logger.exception("Sürücü yedekleme sayfası kapatılamadı")
        from PySide6.QtCore import QThread
        for thread in self.findChildren(QThread):
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(300)  # çabuk biten işlere kısa süre tanı; kalanları süreç sonlanırken bırak
            except RuntimeError:
                pass
        if self._tray_icon is not None:
            self._tray_icon.hide()  # çıkışta tepsi simgesi hayalet olarak kalmasın

    def _soften_sidebar_for_dark(self) -> None:
        """Koyu temada yan menü, ana alandan fazla aydınlık kalmasın diye bir ton koyulaştırılır."""
        swaps = {
            "stop:0 #0A1A31, stop:1 #0C2244": "stop:0 #08111F, stop:1 #0A1A2E",
            "#0F2749": "#0E2036", "#1F3F66": "#1B3350", "#14304F": "#162A44", "#1A3555": "#162B45",
        }
        qss = self.styleSheet()
        for a, b in swaps.items():
            qss = qss.replace(a, b)
        self.setProperty("themeExempt", True)  # zaten dönüştürülmüş; tekrar dönüştürme
        self.setStyleSheet(qss)
