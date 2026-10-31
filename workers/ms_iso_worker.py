from PySide6.QtCore import QObject, Signal

from services.ms_iso_service import MicrosoftIsoRejected, MicrosoftIsoService


class MsIsoLinkWorker(QObject):
    """Microsoft'un resmi ISO bağlantısını arka planda alır."""

    finished = Signal(object)          # IsoOffer
    failed = Signal(str, bool)         # mesaj, Microsoft reddetti mi?

    def __init__(self, language: str, architecture: str):
        super().__init__()
        self.language = language
        self.architecture = architecture

    def run(self) -> None:
        try:
            self.finished.emit(MicrosoftIsoService().find(self.language, self.architecture))
        except MicrosoftIsoRejected as exc:
            self.failed.emit(str(exc), True)
        except Exception as exc:
            self.failed.emit(str(exc), False)
