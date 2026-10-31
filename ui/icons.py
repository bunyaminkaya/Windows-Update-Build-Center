"""Vektör (SVG) tabanlı arayüz ikonları.

Yalnızca görünüm içindir: harici ikon dosyası gerektirmez, her boyutta keskin
çizilir ve rengi koddan verilir. QtSvg kullanılamazsa boş ikon döner; program
çalışmaya devam eder.
"""
from __future__ import annotations

from functools import lru_cache

from ui import theme as _theme

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap

try:  # QtSvg her PySide6 kurulumunda bulunur; yine de güvenli tarafta kalalım.
    from PySide6.QtSvg import QSvgRenderer
except Exception:  # pragma: no cover
    QSvgRenderer = None


# {c} = ana renk, {bg} = dolgu ikonlarda içteki "oyuk" rengi
_STROKE = {
    "search": '<circle cx="11" cy="11" r="7.5"/><line x1="21" y1="21" x2="16.4" y2="16.4"/>',
    "chevron-right": '<polyline points="9 18 15 12 9 6"/>',
    "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
    "x": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "star": '<polygon points="12 2.5 14.9 8.6 21.5 9.4 16.6 14 17.9 20.6 12 17.4 6.1 20.6 7.4 14 2.5 9.4 9.1 8.6"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "external": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
    "calendar": '<rect x="3" y="4.5" width="18" height="17" rx="2.5"/><line x1="16" y1="2.5" x2="16" y2="6.5"/><line x1="8" y1="2.5" x2="8" y2="6.5"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "clock": '<circle cx="12" cy="12" r="9.5"/><polyline points="12 6.5 12 12 15.8 14"/>',
    "cube": '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.3 7 12 12 20.7 7"/><line x1="12" y1="22" x2="12" y2="12"/>',
    "gear-outline": '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="8.6 12 11 14.4 15.6 9.6"/>',
    "history": '<path d="M3 4v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 9"/><polyline points="12 7.5 12 12 15.5 14"/>',
    "monitor": '<rect x="2.5" y="3.5" width="19" height="13" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="16.5" x2="12" y2="21"/>',
    "download-tray": '<path d="M12 3v12"/><polyline points="7 10.5 12 15.5 17 10.5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1.5 1.5 0 0 1-1.5 1.5H4.5A1.5 1.5 0 0 1 3 20z"/><polyline points="9.5 21.5 9.5 14 14.5 14 14.5 21.5"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7.5" r="4"/>',
    "windows-outline": '<rect x="3" y="3" width="8" height="8" rx="1.2"/><rect x="13" y="3" width="8" height="8" rx="1.2"/><rect x="3" y="13" width="8" height="8" rx="1.2"/><rect x="13" y="13" width="8" height="8" rx="1.2"/>',
    "usb": '<g transform="rotate(-45 12 12)"><rect x="8" y="9" width="8" height="13" rx="2"/><path d="M10 9V3.5h4V9"/><line x1="10.6" y1="5.8" x2="10.6" y2="5.8"/><line x1="13.4" y1="5.8" x2="13.4" y2="5.8"/></g>',
    "bug": '<rect x="8" y="6.5" width="8" height="13.5" rx="4"/><path d="M8 11H4M8 16H4M16 11h4M16 16h4M9 4l1.6 2.6M15 4l-1.6 2.6M12 11v9"/>',
    "bulb": '<path d="M9.5 18h5M10.5 21h3"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1.1 1.2 1.1 2.2h5c0-1 .5-1.7 1.1-2.2A6 6 0 0 0 12 3z"/>',
    "message": '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.6-.8L3 21l1.9-5.1A8.4 8.4 0 1 1 21 11.5z"/>',
    "mail": '<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><polyline points="3 7.2 12 13.2 21 7.2"/>',
    "undo": '<polyline points="2 4 2 10 8 10"/><path d="M3.9 15a9 9 0 1 0 2-9.3L2 10"/>',
    "send": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "globe": '<circle cx="12" cy="12" r="9.5"/><line x1="2.5" y1="12" x2="21.5" y2="12"/><path d="M12 2.5a14.5 14.5 0 0 1 3.8 9.5 14.5 14.5 0 0 1-3.8 9.5 14.5 14.5 0 0 1-3.8-9.5A14.5 14.5 0 0 1 12 2.5z"/>',
    "code": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "check": '<polyline points="5 12.5 10 17.5 19 7"/>',
    "info-outline": '<circle cx="12" cy="12" r="9.5"/><line x1="12" y1="16.5" x2="12" y2="11.5"/><line x1="12" y1="7.8" x2="12.01" y2="7.8"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15"/>',
    "tray": '<path d="M3 13.5 5.6 6.4A2 2 0 0 1 7.5 5h9a2 2 0 0 1 1.9 1.4L21 13.5"/><rect x="3" y="13.5" width="18" height="7" rx="2"/><line x1="7" y1="17" x2="7.01" y2="17"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1.5 1.5 0 0 1-1.5-1.5V4A1.5 1.5 0 0 1 4 2.5h9.5A1.5 1.5 0 0 1 15 4v1"/>',
    "cpu": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "trash": '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    "list": '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    "boxes": '<rect x="8.5" y="2.5" width="7" height="6" rx="1.5"/><rect x="2.5" y="15.5" width="7" height="6" rx="1.5"/><rect x="14.5" y="15.5" width="7" height="6" rx="1.5"/><path d="M12 8.5V12M6 15.5V12h12v3.5"/>',
    "sliders": '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
    "cloud-outline": '<path d="M18 10h-1.3A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
    "doc": '<path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z"/><polyline points="14 2.5 14 8 19.5 8"/><line x1="8.5" y1="13" x2="15.5" y2="13"/><line x1="8.5" y1="16.8" x2="15.5" y2="16.8"/>',
}

_FILL = {
    "cloud": '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
    "cloud-down": '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/><path d="M12 9.5v7" stroke="{bg}" stroke-width="2" fill="none"/><polyline points="9 14 12 17 15 14" stroke="{bg}" stroke-width="2" fill="none"/>',
    "star-fill": '<polygon points="12 2.5 14.9 8.6 21.5 9.4 16.6 14 17.9 20.6 12 17.4 6.1 20.6 7.4 14 2.5 9.4 9.1 8.6"/>',
    "info-fill": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="11" x2="12" y2="16.5" stroke="{bg}" stroke-width="2.2" fill="none"/><circle cx="12" cy="7.6" r="1.3" fill="{bg}" stroke="none"/>',
    "check-circle": '<circle cx="12" cy="12" r="11"/><polyline points="7 12.4 10.6 16 17.2 8.6" stroke="#FFFFFF" stroke-width="2.4" fill="none"/>',
    "warning": '<path d="M10.3 3.6 1.8 18.2A2 2 0 0 0 3.5 21.2h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="14" stroke="#FFFFFF" stroke-width="2.2" fill="none"/><circle cx="12" cy="17.3" r="1.2" fill="#FFFFFF" stroke="none"/>',
    "gear": '<circle cx="12" cy="12" r="3.4" fill="{bg}" stroke="none"/>',
}

_GEAR_BODY = _STROKE["gear-outline"]


def _svg(name: str, color: str, bg: str, stroke: float) -> str | None:
    head = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    )
    if name == "windows":
        return (
            head + '><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#37B6FF"/><stop offset="1" stop-color="#1263E8"/>'
            '</linearGradient></defs>'
            '<g fill="url(#g)"><rect x="2" y="2.4" width="9.2" height="9" rx="1.1"/>'
            '<rect x="12.8" y="1.4" width="9.2" height="10" rx="1.1"/>'
            '<rect x="2" y="12.6" width="9.2" height="9" rx="1.1"/>'
            '<rect x="12.8" y="12.6" width="9.2" height="10" rx="1.1"/></g></svg>'
        )
    if name == "windows-color":
        return (
            head + '><rect x="2" y="2" width="9.5" height="9.5" fill="#F25022"/>'
            '<rect x="12.5" y="2" width="9.5" height="9.5" fill="#7FBA00"/>'
            '<rect x="2" y="12.5" width="9.5" height="9.5" fill="#00A4EF"/>'
            '<rect x="12.5" y="12.5" width="9.5" height="9.5" fill="#FFB900"/></svg>'
        )
    if name == "windows-white":
        return (
            head + f'fill="{color}"><rect x="2.5" y="3" width="8.6" height="8.4" rx="1"/>'
            f'<rect x="12.9" y="2" width="8.6" height="9.4" rx="1"/>'
            f'<rect x="2.5" y="12.6" width="8.6" height="8.4" rx="1"/>'
            f'<rect x="12.9" y="12.6" width="8.6" height="9.4" rx="1"/></svg>'
        )
    if name == "gear":
        return (
            head + f'fill="{color}" stroke="{color}" stroke-width="1.2" '
            f'stroke-linejoin="round">{_GEAR_BODY}<circle cx="12" cy="12" r="3.4" '
            f'fill="{bg}" stroke="none"/></svg>'
        )
    if name in _FILL:
        body = _FILL[name].replace("{bg}", bg)
        return (
            head + f'fill="{color}" stroke="{color}" stroke-width="1.4" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
        )
    if name in _STROKE:
        return (
            head + f'fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round">{_STROKE[name]}</svg>'
        )
    return None


@lru_cache(maxsize=512)
def _render(name: str, color: str, bg: str, size: int, stroke: float, dpr: float) -> QPixmap:
    px = max(1, int(round(size * dpr)))
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(dpr)
    svg = _svg(name, color, bg, stroke)
    if svg is None or QSvgRenderer is None:
        return pixmap
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def _dpr() -> float:
    try:
        screen = QGuiApplication.primaryScreen()
        return max(1.0, float(screen.devicePixelRatio())) if screen else 1.0
    except Exception:
        return 1.0


def pixmap(name: str, color: str = "#FFFFFF", size: int = 20, bg: str = "#0B1D36", stroke: float = 1.9) -> QPixmap:
    if _theme.is_dark():  # koyu tema: ikon rengi ve oyuk rengi koyu zemine uyarlanır
        color, bg = _theme.fg_hex(color), _theme.bg_hex(bg)
    return _render(name, color, bg, int(size), float(stroke), max(2.0, _dpr()))


def icon(name: str, color: str = "#FFFFFF", size: int = 20, bg: str = "#0B1D36", stroke: float = 1.9) -> QIcon:
    return QIcon(pixmap(name, color, size, bg, stroke))
