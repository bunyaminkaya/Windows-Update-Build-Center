import sys
import ctypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.logger import configure_logging
from app.paths import ICON_DIR
from database.migrations import run_migrations
from ui.main_window import MainWindow
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


def main():
    _set_windows_app_id()
    configure_logging()
    run_migrations()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("bunyaminkaya.com")
    app.setStyle("Fusion")

    icon_path = ICON_DIR / "app_logo.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    # Qt bazen kaynak koddan (python.exe) çalıştırıldığında görev çubuğu
    # simgesini yalnızca QApplication ikonundan devralmaz. Ana pencerenin
    # native HWND ikonunu da zorlayarak Windows görev çubuğunda aynı simgenin
    # görünmesini garanti altına alıyoruz.
    if hasattr(window, "apply_native_windows_icon"):
        window.apply_native_windows_icon()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
