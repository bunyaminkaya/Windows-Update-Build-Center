from PySide6.QtCore import QObject, Signal

from services.package_service import PackageService


class PackageLookupWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, kb: str):
        super().__init__()
        self.kb = kb

    def run(self):
        try:
            packages = PackageService().find_packages_for_kb(
                self.kb
            )
            self.finished.emit(packages)
        except Exception as exc:
            self.failed.emit(str(exc))
