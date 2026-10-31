from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import Qt

from ui import styles
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QWidget,
)


@dataclass(frozen=True)
class DialogAction:
    key: str
    text: str
    role: str = "primary"  # primary | secondary | danger


class MessageDialog(QDialog):
    """Application-wide modern replacement for QMessageBox."""

    TYPE_STYLES = {
        "info": ("i", "#EAF3FF", "#1E67D8"),
        "success": ("✓", "#EAF8F0", "#168447"),
        "warning": ("!", "#FFF7E8", "#B7791F"),
        "error": ("!", "#FFF0F0", "#D83A3A"),
        "question": ("?", "#EAF3FF", "#1E67D8"),
    }

    def __init__(
        self,
        title: str,
        heading: str,
        message: str,
        actions: Iterable[DialogAction] | None = None,
        dialog_type: str = "info",
        parent=None,
    ):
        super().__init__(parent)
        self.result_key: str | None = None
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMaximumWidth(760)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        icon_text, icon_bg, icon_fg = self.TYPE_STYLES.get(
            dialog_type, self.TYPE_STYLES["info"]
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("modernDialogCard")
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(14)

        icon = QLabel(icon_text)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(44, 44)
        icon.setStyleSheet(
            f"background:{icon_bg};color:{icon_fg};border-radius:22px;"
            "font-size:22px;font-weight:800;"
        )
        header.addWidget(icon, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(5)
        heading_label = QLabel(heading)
        heading_label.setObjectName("dialogHeading")
        heading_label.setWordWrap(True)
        text_col.addWidget(heading_label)

        message_label = QLabel(message)
        message_label.setObjectName("dialogMessage")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_col.addWidget(message_label)
        header.addLayout(text_col, 1)
        layout.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("dialogSeparator")
        layout.addWidget(line)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addStretch()

        action_list = list(actions or [DialogAction("ok", "Tamam", "primary")])
        for action in action_list:
            button = QPushButton(action.text)
            button.setProperty("dialogRole", action.role)
            button.setMinimumWidth(max(110, len(action.text) * 8 + 34))
            button.setMinimumHeight(38)
            button.clicked.connect(lambda checked=False, key=action.key: self._finish(key))
            button_row.addWidget(button)

        layout.addLayout(button_row)

        self.setStyleSheet(
            styles.qss("""
            QDialog { background: #F3F7FC; color: #14213D; }
            QFrame#modernDialogCard {
                background: #FFFFFF;
                border: 1px solid #D9E4F2;
                border-radius: 12px;
            }
            QLabel { background: transparent; color: #14213D; }
            QLabel#dialogHeading {
                color: #0B1736;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#dialogMessage {
                color: #536781;
                font-size: 13px;
            }
            QFrame#dialogSeparator { color: #E1E9F3; }
            QPushButton {
                background: #FFFFFF;
                color: @BLUE@;
                border: 1px solid #BFD1E8;
                border-radius: 7px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover { background: #EEF5FF; border-color: #8FB3E7; }
            QPushButton[dialogRole="primary"] {
                background: @BLUE@;
                color: #FFFFFF;
                border-color: @BLUE@;
            }
            QPushButton[dialogRole="primary"]:hover { background: #1D5FC5; }
            QPushButton[dialogRole="danger"] {
                background: #FFFFFF;
                color: #D63A3A;
                border-color: #F1A8A8;
            }
            QPushButton[dialogRole="danger"]:hover { background: #FFF0F0; }
            """)
        )

    def _finish(self, key: str):
        self.result_key = key
        self.accept()


def show_dialog(
    parent,
    title: str,
    heading: str,
    message: str,
    *,
    dialog_type: str = "info",
    actions: Iterable[DialogAction] | None = None,
) -> str | None:
    dialog = MessageDialog(
        title=title,
        heading=heading,
        message=message,
        actions=actions,
        dialog_type=dialog_type,
        parent=parent,
    )
    dialog.exec()
    return dialog.result_key


def show_message(parent, title: str, heading: str, message: str, button_text: str = "Tamam"):
    return show_dialog(
        parent,
        title,
        heading,
        message,
        dialog_type="info",
        actions=[DialogAction("ok", button_text, "primary")],
    )


def show_information(parent, title: str, message: str, heading: str | None = None):
    return show_dialog(parent, title, heading or title, message, dialog_type="info")


def show_success(parent, title: str, message: str, heading: str | None = None):
    return show_dialog(parent, title, heading or title, message, dialog_type="success")


def show_warning(parent, title: str, message: str, heading: str | None = None):
    return show_dialog(parent, title, heading or title, message, dialog_type="warning")


def show_error(parent, title: str, message: str, heading: str | None = None):
    return show_dialog(parent, title, heading or title, message, dialog_type="error")


def ask_confirmation(
    parent,
    title: str,
    message: str,
    *,
    heading: str | None = None,
    confirm_text: str = "Evet",
    cancel_text: str = "Vazgeç",
    destructive: bool = False,
) -> bool:
    result = show_dialog(
        parent,
        title,
        heading or title,
        message,
        dialog_type="question",
        actions=[
            DialogAction("cancel", cancel_text, "secondary"),
            DialogAction("confirm", confirm_text, "danger" if destructive else "primary"),
        ],
    )
    return result == "confirm"


def ask_choice(
    parent,
    title: str,
    heading: str,
    message: str,
    choices: Iterable[DialogAction],
) -> str | None:
    return show_dialog(
        parent,
        title,
        heading,
        message,
        dialog_type="question",
        actions=choices,
    )
