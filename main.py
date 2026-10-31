import ctypes
import logging
import sys

from app import startup_timing  # açılış süresi ölçümü: ilk içe aktarılanlardan biri olmalı
from app import i18n
from ui import theme

i18n.install()  # arayüz dili (Türkçe/English); UI modüllerinden önce
theme.install()  # koyu tema seçiliyse, arayüz modülleri yüklenmeden önce etkinleştirilir

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.logger import configure_logging
from app.paths import ICON_DIR
from database.migrations import run_migrations
from app.version import APP_NAME


def _set_windows_app_id():
    """Ensure Windows groups the app under its own taskbar identity/icon."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "BunyaminKaya.WindowsUpdateBuildCenter"
        )
    except Exception:
        pass


_SERVER_NAME = "WindowsUpdateBuildCenter.activate"


def _acquire_single_instance():
    """Aynı anda tek kopya çalışsın: iki kopya aynı indirme/ayar dosyalarını bozabilir.

    Dönüş: (kilit, None) -> bu kopya birincil; (None, None) -> var olan kopya öne getirildi, çıkılmalı.
    """
    from PySide6.QtCore import QLockFile
    from PySide6.QtNetwork import QLocalSocket
    from app.paths import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA_DIR / "app.lock"))
    if lock.tryLock(150):
        return lock, True
    socket = QLocalSocket()
    socket.connectToServer(_SERVER_NAME)
    if socket.waitForConnected(800):
        socket.write(b"show")
        socket.waitForBytesWritten(800)
        socket.disconnectFromServer()
        return None, False
    return lock, True  # kilit var ama sunucu yanıt vermiyor (takılı kayıt): yine de aç


def _listen_for_activation(window):
    from PySide6.QtNetwork import QLocalServer
    QLocalServer.removeServer(_SERVER_NAME)
    server = QLocalServer(window)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda c=conn: (c.readAll(), window._restore_from_tray()))
            conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(on_connection)
    server.listen(_SERVER_NAME)
    return server


def _make_splash():
    """Ağır modüller yüklenirken hemen görünen küçük açılış ekranı (yalnızca görünüm)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen
    from app.version import APP_NAME, APP_VERSION
    w, h = 460, 250
    pm = QPixmap(w, h)
    pm.fill(QColor("#0A1A31"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QColor("#1F3F66"))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)
    logo = QPixmap(str(ICON_DIR / "app_logo_128.png"))
    if not logo.isNull():
        p.drawPixmap(34, 56, logo.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    title = QFont("Segoe UI", 15)
    title.setBold(True)
    p.setFont(title)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRectF(150, 62, w - 170, 50), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, APP_NAME)
    p.setFont(QFont("Segoe UI", 10))
    p.setPen(QColor("#9DB2CC"))
    p.drawText(QRectF(150, 118, w - 170, 22), Qt.AlignLeft | Qt.AlignVCenter, f"{APP_VERSION}  •  Başlatılıyor…")
    p.end()
    splash = QSplashScreen(pm, Qt.WindowStaysOnTopHint)
    splash.show()
    return splash


def _exit_now(code: int) -> None:
    """Arka plan iş parçacıkları (ör. ağ isteği) hâlâ çalışırken normal çıkış Qt'de çökmeye yol açar.

    Kapanış işleri (indirme durumu kaydı vb.) aboutToQuit ile zaten yapıldı; burada
    günlükler boşaltılıp süreç doğrudan sonlandırılır.
    """
    import logging
    import os
    try:
        logging.shutdown()
        sys.stdout and sys.stdout.flush()
        sys.stderr and sys.stderr.flush()
    except Exception:
        pass
    os._exit(int(code))


def main():
    from app import cli
    args = cli.parse()
    if cli.wants_console(args):
        return cli.run(args)  # arayüz açmadan sonucu yazar
    _set_windows_app_id()
    configure_logging()
    run_migrations()

    startup_timing.mark("modüller yüklendi")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("bunyaminkaya.com")
    app.setStyle("Fusion")
    theme.apply_palette(app)

    startup_timing.mark("Qt hazır")
    instance_lock, primary = _acquire_single_instance()
    if not primary:
        return 0  # çalışan kopya öne getirildi

    icon_path = ICON_DIR / "app_logo.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    splash = None
    if not args.minimized:
        try:
            splash = _make_splash()
            app.processEvents()
        except Exception:
            splash = None
    try:
        from ui.main_window import MainWindow  # ağır modüller splash görünürken yüklenir
        startup_timing.mark("arayüz modülleri")
        window = MainWindow()
        startup_timing.mark("pencere oluşturuldu")
    except Exception as exc:
        # PyInstaller/windowed modunda oluşan başlangıç hataları kullanıcıya
        # sessizce yalnızca tepsi simgesi bırakmamalı. Hata hem loglanır hem
        # görünür bir iletiyle gösterilir.
        logging.getLogger(__name__).exception("Ana pencere başlatılamadı")
        if splash is not None:
            splash.close()
        QMessageBox.critical(
            None,
            "Windows Update & Build Center başlatılamadı",
            "Program ana penceresini başlatamadı.\n\n"
            f"Hata: {exc}\n\n"
            "Ayrıntılar app.log dosyasına yazıldı.",
        )
        return 1

    if args.page:
        window.show_page_by_name(args.page)
    if args.no_update_check:
        window.skip_update_check = True
    window._activation_server = _listen_for_activation(window)
    window._instance_lock = instance_lock  # kilit program boyunca tutulur
    if args.minimized:
        window.showMinimized()
    else:
        window.force_maximized_start()
        # Windows oturum açılışında kısayolun eski "küçültülmüş" durumunu biraz
        # gecikmeli uygulamasına karşı pencere durumunu olay döngüsünde tekrar sabitle.
        QTimer.singleShot(0, window.force_maximized_start)
        QTimer.singleShot(350, window.force_maximized_start)
    if splash is not None:
        splash.finish(window)
    startup_timing.mark("pencere görünür")
    QTimer.singleShot(0, lambda: (startup_timing.mark("ilk olay döngüsü"), startup_timing.report(logging.getLogger("app.startup"))))
    QTimer.singleShot(3000, window.check_app_update_on_start)
    window.schedule_welcome_guide_on_start()
    # Qt bazen kaynak koddan (python.exe) çalıştırıldığında görev çubuğu
    # simgesini yalnızca QApplication ikonundan devralmaz. Ana pencerenin
    # native HWND ikonunu da zorlayarak Windows görev çubuğunda aynı simgenin
    # görünmesini garanti altına alıyoruz.
    if hasattr(window, "apply_native_windows_icon"):
        window.apply_native_windows_icon()
    code = app.exec()
    _exit_now(code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
