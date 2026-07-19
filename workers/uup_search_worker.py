from PySide6.QtCore import QObject, Signal

from services.uup_service import UupService


class UupSearchWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        build,
        architecture,
        language,
        edition,
    ):
        super().__init__()
        self.build = build
        self.architecture = architecture
        self.language = language
        self.edition = edition

    def run(self):
        try:
            results = UupService().search(
                self.build,
                self.architecture,
                self.language,
                self.edition,
            )
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
