from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame

class SimplePage(QWidget):
    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)

        info = QLabel("Bu modül geliştirme planındaki ilgili aşamada aktif edilecek.")
        info.setObjectName("infoBox")
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()
