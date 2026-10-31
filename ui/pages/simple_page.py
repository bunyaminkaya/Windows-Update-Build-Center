from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame


class SimplePage(QWidget):
    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(12)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        layout.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName("warningNote")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        layout.addStretch(1)

    def set_error_details(self, details: str) -> None:
        self.error_label.setText(
            "Ayrıntı: " + str(details) +
            "\n\nUygulama günlük dosyası: %LOCALAPPDATA%\\Windows Update & Build Center\\logs\\app.log"
        )
        self.error_label.setVisible(True)
