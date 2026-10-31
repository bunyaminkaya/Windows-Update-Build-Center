from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt

from app import i18n
from ui import styles
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)


class RoundedComboPopup(QWidget):
    """A real transparent top-level popup with a painted rounded surface.

    Qt stylesheets cannot reliably clip a top-level popup window on Windows.
    Painting the rounded card on a translucent window removes the rectangular
    native popup background completely.
    """

    RADIUS = 9.0
    BORDER_WIDTH = 1.0

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("modernComboPopup")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAutoFillBackground(False)

        layout = QVBoxLayout(self)
        # Keep content inside the rounded edge so selected rows can never paint
        # square corners over the popup surface.
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("modernComboPopupList")
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.setFocusPolicy(Qt.StrongFocus)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setMouseTracking(True)
        self.list_widget.viewport().setMouseTracking(True)
        self.list_widget.setFrameShape(QListWidget.NoFrame)
        self.list_widget.viewport().setAutoFillBackground(False)

        # The popup is a separate top-level window, so it does not inherit the
        # MainWindow stylesheet on Windows. Keep the theme here to guarantee
        # identical hover/selection colors everywhere ModernComboBox is used.
        self.list_widget.setStyleSheet(styles.qss("""
            QListWidget#modernComboPopupList {
                background: transparent;
                border: none;
                outline: none;
                padding: 4px;
                color: #14213D;
            }
            QListWidget#modernComboPopupList::item {
                min-height: 28px;
                padding: 6px 10px;
                margin: 1px 2px;
                border: none;
                border-radius: 7px;
                color: #14213D;
                background: transparent;
            }
            QListWidget#modernComboPopupList::item:hover {
                background: #EAF2FF;
                color: #0B1736;
            }
            QListWidget#modernComboPopupList::item:selected {
                background: @BLUE@;
                color: #FFFFFF;
            }
            QListWidget#modernComboPopupList::item:selected:hover {
                background: #185ABE;
                color: #FFFFFF;
            }
            QListWidget#modernComboPopupList QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 7px 3px 7px 0;
            }
            QListWidget#modernComboPopupList QScrollBar::handle:vertical {
                background: #C3D2E7;
                min-height: 26px;
                border-radius: 4px;
            }
            QListWidget#modernComboPopupList QScrollBar::handle:vertical:hover {
                background: #9FB7D7;
            }
            QListWidget#modernComboPopupList QScrollBar::add-line:vertical,
            QListWidget#modernComboPopupList QScrollBar::sub-line:vertical,
            QListWidget#modernComboPopupList QScrollBar::add-page:vertical,
            QListWidget#modernComboPopupList QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
            }
        """))
        self.list_widget.itemEntered.connect(self._on_item_hovered)
        layout.addWidget(self.list_widget)

    def _on_item_hovered(self, item: QListWidgetItem) -> None:
        # Follow the mouse with the active row. This avoids Windows keeping the
        # old keyboard-selected row in its default grey highlight.
        self.list_widget.setCurrentItem(item)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Half-pixel inset keeps the 1px border fully inside the widget.
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        painter.fillPath(path, QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#C9D5E4"), self.BORDER_WIDTH))
        painter.drawPath(path)


class ModernComboBox(QComboBox):
    """Theme-consistent combo box with a custom rounded popup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: RoundedComboPopup | None = None
        self._popup_list: QListWidget | None = None
        self.setObjectName("modernComboBox")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("popupOpen", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setMinimumContentsLength(12)

    def paintEvent(self, event) -> None:
        # QSS'deki native down-arrow bazı Windows/PySide6 kombinasyonlarında
        # görünmeyebiliyor. Kutunun açılır menü olduğu her zaman belli olsun diye
        # oku kendimiz çiziyoruz.
        if i18n.is_english():
            # Kapalı kutudaki metni, mantıkta kullanılan değeri değiştirmeden çevirerek çiz.
            sp = QStylePainter(self)
            opt = QStyleOptionComboBox()
            self.initStyleOption(opt)
            opt.currentText = i18n.tr(opt.currentText)
            sp.drawComplexControl(QStyle.CC_ComboBox, opt)
            sp.drawControl(QStyle.CE_ComboBoxLabel, opt)
            sp.end()
        else:
            super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#53657D"), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        cx = self.width() - 17
        cy = self.height() // 2
        painter.drawLine(cx - 4, cy - 2, cx, cy + 2)
        painter.drawLine(cx, cy + 2, cx + 4, cy - 2)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Prevent QComboBox from invoking its native rectangular popup.
        if event.button() == Qt.LeftButton:
            event.accept()
            self.setFocus(Qt.MouseFocusReason)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            event.accept()
            if self._popup is not None and self._popup.isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_F4):
            event.accept()
            self.showPopup()
            return
        if key == Qt.Key_Down and event.modifiers() & Qt.AltModifier:
            event.accept()
            self.showPopup()
            return
        if key == Qt.Key_Escape and self._popup is not None:
            event.accept()
            self.hidePopup()
            return
        super().keyPressEvent(event)

    def showPopup(self) -> None:
        if self.count() <= 0:
            return

        if self._popup is not None:
            self._close_popup()

        popup = RoundedComboPopup(self.window())
        list_widget = popup.list_widget

        row_height = 38
        for row in range(self.count()):
            item = QListWidgetItem(i18n.tr(self.itemText(row)))
            item.setData(Qt.UserRole, row)
            item.setSizeHint(QSize(max(self.width() - 18, 120), row_height))
            list_widget.addItem(item)

        if self.currentIndex() >= 0:
            list_widget.setCurrentRow(self.currentIndex())

        list_widget.itemClicked.connect(self._select_popup_item)
        list_widget.itemActivated.connect(self._select_popup_item)

        visible_count = min(max(self.count(), 1), 9)
        popup_width = self.width()
        popup_height = visible_count * row_height + 8
        popup.resize(popup_width, popup_height)

        combo_top = self.mapToGlobal(QPoint(0, 0))
        combo_bottom = self.mapToGlobal(QPoint(0, self.height()))
        screen = self.screen().availableGeometry()
        gap = 4

        x = min(
            max(combo_top.x(), screen.left()),
            screen.right() - popup_width + 1,
        )

        if combo_bottom.y() + gap + popup_height <= screen.bottom():
            y = combo_bottom.y() + gap
        else:
            y = max(screen.top(), combo_top.y() - popup_height - gap)

        popup.move(x, y)
        self._popup = popup
        self._popup_list = list_widget
        self.setProperty("popupOpen", True)
        self._refresh_style()

        popup.destroyed.connect(self._on_popup_destroyed)
        popup.show()
        popup.raise_()
        list_widget.setFocus(Qt.PopupFocusReason)

    def hidePopup(self) -> None:
        self._close_popup()

    def _select_popup_item(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.UserRole)
        if isinstance(row, int) and 0 <= row < self.count():
            self.setCurrentIndex(row)
            self.activated.emit(row)
        self._close_popup()

    def _close_popup(self) -> None:
        popup = self._popup
        self._popup = None
        self._popup_list = None
        self.setProperty("popupOpen", False)
        self._refresh_style()
        if popup is not None:
            popup.close()

    def _on_popup_destroyed(self) -> None:
        self._popup = None
        self._popup_list = None
        self.setProperty("popupOpen", False)
        self._refresh_style()

    def _refresh_style(self) -> None:
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()
