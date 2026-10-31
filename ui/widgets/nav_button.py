from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from ui import icons
from ui.theme import raw_qcolor

QColor = raw_qcolor()  # yan menü her temada koyu kalır; renkler dönüştürülmez


class NavButton(QPushButton):
    """Sol menü satırı: ikon + metin, sağda ok / rozet. Yalnızca görünümdür."""

    ICON_SIZE = 21

    def __init__(self, text: str, icon_name: str, parent=None):
        super().__init__(text, parent)
        self._icon_name = icon_name
        self._badge = 0
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)

    def sizeHint(self) -> QSize:
        return QSize(200, 44)

    def set_badge(self, count: int) -> None:
        count = max(0, int(count or 0))
        if count != self._badge:
            self._badge = count
            self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        checked = self.isChecked()
        hovered = self.underMouse()

        if checked:
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0.0, QColor("#1561DB"))
            grad.setColorAt(1.0, QColor("#2074EE"))
            path = QPainterPath()
            path.addRoundedRect(rect, 10, 10)
            painter.fillPath(path, grad)
            painter.setPen(QPen(QColor("#3C85F0"), 1))
            painter.drawPath(path)
        elif hovered:
            path = QPainterPath()
            path.addRoundedRect(rect, 10, 10)
            painter.fillPath(path, QColor("#12294A"))

        # Sol ikon
        icon_color = "#FFFFFF" if checked else "#D3DFF0"
        pix = icons.pixmap(self._icon_name, icon_color, self.ICON_SIZE)
        icon_y = (self.height() - self.ICON_SIZE) / 2
        painter.drawPixmap(15, int(round(icon_y)), pix)

        # Metin: uzun başlıklar kesilmeden önce font biraz küçültülür.
        text_left = 15 + self.ICON_SIZE + 11
        available = self.width() - text_left - 36
        font = QFont(self.font())
        font.setWeight(QFont.DemiBold if checked else QFont.Medium)
        point = 9.3
        font.setPointSizeF(point)
        while point > 8.4 and QFontMetrics(font).horizontalAdvance(self.text()) > available:
            point -= 0.2
            font.setPointSizeF(point)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF") if checked else QColor("#DCE6F5"))
        text_rect = QRectF(text_left, 0, available, self.height())
        elided = painter.fontMetrics().elidedText(self.text(), Qt.ElideRight, int(available))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        # Sağ taraf: rozet / aktif ikonu / ok
        right_center_x = self.width() - 24
        if self._badge > 0:
            diameter = 24
            badge_rect = QRectF(
                right_center_x - diameter / 2,
                (self.height() - diameter) / 2,
                diameter,
                diameter,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#1F6FEB"))
            painter.drawEllipse(badge_rect)
            badge_font = QFont(self.font())
            badge_font.setPixelSize(11)
            badge_font.setWeight(QFont.Bold)
            painter.setFont(badge_font)
            painter.setPen(QColor("#FFFFFF"))
            label = str(self._badge) if self._badge < 100 else "99+"
            painter.drawText(badge_rect, Qt.AlignCenter, label)
        elif checked:
            pix = icons.pixmap("chevron-right", "#FFFFFF", 15, stroke=2.4)
            painter.drawPixmap(int(right_center_x - 7), int((self.height() - 15) / 2), pix)
        elif False:
            pix = icons.pixmap("home", "#FFFFFF", 17, stroke=2.0)
            painter.drawPixmap(int(right_center_x - 8), int((self.height() - 17) / 2), pix)
        else:
            pix = icons.pixmap("chevron-right", "#8EA6C6", 15, stroke=2.2)
            painter.drawPixmap(int(right_center_x - 7), int((self.height() - 15) / 2), pix)
