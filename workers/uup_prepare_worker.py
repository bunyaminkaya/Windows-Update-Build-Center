from PySide6.QtCore import QObject, Signal

from services.uup_service import UupService


class UupPrepareWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, uuid, language_code, edition_code, architecture):
        super().__init__()
        self.uuid = uuid
        self.language_code = language_code
        self.edition_code = edition_code
        self.architecture = architecture

    def run(self):
        try:
            packages = UupService().get_download_packages(
                self.uuid,
                self.language_code,
                self.edition_code,
                self.architecture,
            )
            self.finished.emit(packages)
        except Exception as exc:
            self.failed.emit(str(exc))
