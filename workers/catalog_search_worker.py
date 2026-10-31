from PySide6.QtCore import QObject, Signal
from services.unified_search_service import UnifiedSearchService


class CatalogSearchWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, query: str, architectures=None):
        super().__init__()
        self.query = query
        self.architectures = architectures

    def run(self) -> None:
        try:
            results = UnifiedSearchService().search(self.query, self.architectures)
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))
