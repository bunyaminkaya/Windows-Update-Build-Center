from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ui import icons, styles


class EmptyState(QWidget):
    """Tablo boşken tablonun üzerinde gösterilen ikonlu açıklama (yalnızca görünüm)."""

    clicked = Signal()

    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(8)
        self.circle = QLabel()
        self.circle.setObjectName("emptyCircle")
        self.circle.setFixedSize(92, 92)
        self.circle.setAlignment(Qt.AlignCenter)
        self.circle.setPixmap(icons.pixmap(icon_name, "#1768E0", 46, stroke=1.9))
        lay.addWidget(self.circle, 0, Qt.AlignHCenter)
        lay.addSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("emptyTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.text = QLabel()
        self.text.setObjectName("emptyText")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setFixedWidth(420)
        self.button = QPushButton()
        self.button.setObjectName("emptyButton")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.clicked.emit)
        lay.addWidget(self.title)
        lay.addWidget(self.text, 0, Qt.AlignHCenter)
        lay.addSpacing(6)
        lay.addWidget(self.button, 0, Qt.AlignHCenter)
        self.setStyleSheet(styles.qss("""
            QWidget#emptyState { background: transparent; }
            QLabel#emptyCircle { background: #E3EEFC; border-radius: 46px; }
            QLabel#emptyTitle { color: #0B1736; font-size: 18px; font-weight: 700; background: transparent; }
            QLabel#emptyText { color: #65728A; font-size: 13px; background: transparent; }
            QPushButton#emptyButton { background: #FFFFFF; color: @BLUE@; border: 1px solid #CBD9EC;
                border-radius: 10px; padding: 9px 20px; font-weight: 700; min-height: 20px; }
            QPushButton#emptyButton:hover { background: #F1F6FD; border-color: #9DB9E6; }
        """))

    def _fit_text(self) -> None:
        """Açıklama kutusu, bulunduğu alandan geniş olmasın ve sarılan satırlar kesilmesin."""
        width = max(160, min(420, self.width() - 40)) if self.width() > 0 else 420
        self.text.setFixedWidth(width)
        if self.text.text():
            self.text.setMinimumHeight(self.text.heightForWidth(width))
        self.text.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()

    def set_content(self, title: str, text: str, button: str | None = None) -> None:
        self.title.setText(title)
        self.text.setText(text)
        self.text.setVisible(bool(text))
        self._fit_text()
        self.button.setText(button or "")
        self.button.setVisible(bool(button))


class _Follow(QObject):
    """Boş durumu tablonun içerik alanına yayar."""

    def __init__(self, view, overlay):
        super().__init__(overlay)
        self._view, self._overlay = view, overlay

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Show):
            self._overlay.setGeometry(self._view.rect())
        return False


def attach_empty_state(table, icon_name: str, resolver) -> EmptyState:
    """Tablo boşken (satır yoksa) üzerine bir boş durum koyar.

    resolver() -> (başlık, açıklama, düğme metni | None); her değişimde çağrılır.
    """
    view = table.viewport()
    overlay = EmptyState(icon_name, view)
    watcher = _Follow(view, overlay)
    view.installEventFilter(watcher)
    overlay.setGeometry(view.rect())

    def sync(*_args):
        try:
            empty = table.rowCount() == 0
            if empty:
                overlay.set_content(*resolver())
                overlay.setGeometry(view.rect())
                overlay.raise_()
            overlay.setVisible(empty)
        except RuntimeError:
            pass

    model = table.model()
    for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.layoutChanged):
        signal.connect(sync)
    overlay._sync = sync
    sync()
    return overlay
