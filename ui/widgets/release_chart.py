from __future__ import annotations

from collections import OrderedDict
from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

# Kanal -> çubuk rengi (hem açık hem koyu zeminde okunur doygun tonlar)
CHANNELS = OrderedDict([
    ("GA / Retail", "#2167D5"),
    ("Release Preview", "#F59E0B"),
    ("Beta", "#16A34A"),
    ("Dev", "#06B6D4"),
    ("Experimental", "#8B5CF6"),
    ("Canary", "#EF4444"),
])
from app import i18n

_MONTHS = (["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
           if i18n.is_english() else
           ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"])


def channel_key(channel: str) -> str:
    value = (channel or "").casefold()
    for name in ("Release Preview", "Beta", "Dev", "Experimental", "Canary"):
        if name.casefold() in value:
            return name
    return "GA / Retail"


def monthly_counts(records, months: int = 12, now: datetime | None = None):
    """Son N ay için {(yıl, ay): {kanal: adet}} sözlüğünü ve ay listesini döner (eskiden yeniye)."""
    now = now or datetime.now()
    keys = []
    year, month = now.year, now.month
    for _ in range(months):
        keys.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    keys.reverse()
    data = {k: {c: 0 for c in CHANNELS} for k in keys}
    for record in records:
        try:
            stamp = datetime.strptime(record.release_date, "%Y-%m-%d")
        except Exception:
            continue
        key = (stamp.year, stamp.month)
        if key in data:
            data[key][channel_key(record.channel)] += 1
    return keys, data


class ReleaseChart(QWidget):
    """Kanallara göre aylık yayın sayısı (yığılmış çubuk grafik). Yalnızca görüntüler."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self._keys: list = []
        self._data: dict = {}
        self._active = list(CHANNELS)
        self._bars: list = []  # (QRectF, ay anahtarı, kanal, adet)
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event) -> None:
        from PySide6.QtWidgets import QToolTip
        pos = event.position()
        for rect, key, channel, count in self._bars:
            if rect.contains(pos):
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{_MONTHS[key[1] - 1]} {key[0]} • {channel}: {count} yayın",
                    self,
                )
                return
        QToolTip.hideText()

    def set_records(self, records) -> None:
        self._keys, self._data = monthly_counts(records)
        used = [c for c in CHANNELS if any(self._data[k][c] for k in self._keys)]
        self._active = used or list(CHANNELS)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._bars = []
        text = QColor("#53657D")
        grid = QColor("#D5DFEC")
        w, h = self.width(), self.height()
        left, right, top, bottom = 44, 16, 14, 58
        plot = QRectF(left, top, w - left - right, h - top - bottom)
        totals = [sum(self._data[k].values()) for k in self._keys] or [0]
        peak = max(max(totals), 1)
        step = 1 if peak <= 6 else 2 if peak <= 14 else 5 if peak <= 40 else 10
        top_value = ((peak + step - 1) // step) * step
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)
        for value in range(0, top_value + 1, step):
            y = plot.bottom() - plot.height() * value / top_value
            p.setPen(QPen(grid, 1))
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            p.setPen(text)
            p.drawText(QRectF(0, y - 9, left - 8, 18), Qt.AlignRight | Qt.AlignVCenter, str(value))
        n = max(len(self._keys), 1)
        slot = plot.width() / n
        bar_w = min(38.0, slot * 0.62)
        for i, key in enumerate(self._keys):
            x = plot.left() + slot * i + (slot - bar_w) / 2
            y = plot.bottom()
            for channel in CHANNELS:
                count = self._data[key][channel]
                if not count:
                    continue
                seg = plot.height() * count / top_value
                y -= seg
                p.setPen(Qt.NoPen)
                p.setBrush(_raw(CHANNELS[channel]))
                p.drawRoundedRect(QRectF(x, y, bar_w, seg), 2, 2)
                self._bars.append((QRectF(x, y, bar_w, seg), key, channel, count))
            total = totals[i]
            p.setPen(text)
            if total:
                p.drawText(QRectF(x - 6, y - 17, bar_w + 12, 16), Qt.AlignHCenter | Qt.AlignBottom, str(total))
            label = _MONTHS[key[1] - 1] + (f" {str(key[0])[2:]}" if key[1] == 1 or i == 0 else "")
            p.drawText(QRectF(x - 10, plot.bottom() + 6, bar_w + 20, 16), Qt.AlignHCenter | Qt.AlignTop, label)
        # Gösterge
        x = plot.left()
        ly = h - 22
        for channel in self._active:
            p.setPen(Qt.NoPen)
            p.setBrush(_raw(CHANNELS[channel]))
            p.drawRoundedRect(QRectF(x, ly + 3, 10, 10), 3, 3)
            p.setPen(text)
            width = p.fontMetrics().horizontalAdvance(channel)
            p.drawText(QRectF(x + 15, ly, width + 6, 16), Qt.AlignLeft | Qt.AlignVCenter, channel)
            x += 15 + width + 22


def _raw(color: str) -> QColor:
    """Kanal renkleri her temada aynı kalır (koyu tema dönüşümü uygulanmaz)."""
    from ui.theme import raw_qcolor
    return raw_qcolor()(color)
