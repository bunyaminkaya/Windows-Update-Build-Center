"""Koyu tema desteği (yalnızca görünüm).

Mantık: Uygulamadaki tüm sayfalar açık tema renkleriyle yazılmıştır. Koyu mod
açıkken bu modül, stil sayfalarındaki (QSS), çizim kodundaki (QColor) ve
ikonlardaki renkleri çalışma anında koyu karşılıklarına çevirir. Sayfa kodu
ve çalışma mantığı değişmez. Tema seçimi program açılırken okunur; değişiklik
için programın yeniden başlatılması gerekir.

Kurallar (özet):
  * Açık zeminler (kart, sayfa, tablo satırı, kenarlık) koyu tonlara çevrilir.
  * Koyu / orta tonlu metinler açık tonlara çevrilir.
  * Doygun vurgu renkleri (mavi düğmeler, rozetler) zemin olarak aynen kalır.
  * Yan menü (sidebar) zaten koyudur; hiç dönüştürülmez.
"""
from __future__ import annotations

import colorsys
import logging
import re
import sys

logger = logging.getLogger(__name__)

THEME_LIGHT, THEME_DARK, THEME_SYSTEM = "light", "dark", "system"
THEME_LABELS = {THEME_LIGHT: "Açık", THEME_DARK: "Koyu", THEME_SYSTEM: "Sistem"}

_dark = False
_installed = False

# Bu kimliklere sahip kurallar (yan menü) dönüştürülmez.
_EXEMPT_IDS = (
    "sidebar", "brandCard", "brandLogo", "brandTitle", "brandSubtitle",
    "navGroupLabel", "navDivider", "sidebarFooter", "statusDot",
    "versionLabel", "lastCheckLabel",
)
_EXEMPT_RE = re.compile(r"#(" + "|".join(_EXEMPT_IDS) + r")\b")


def is_dark() -> bool:
    return _dark


# ----------------------------------------------------------------------
# Renk dönüşümü
# ----------------------------------------------------------------------
def _parse_hex(h: str):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None


def _to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        *(max(0, min(255, int(round(v * 255)))) for v in (r, g, b))
    )


def _interp(points, x):
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


# Açık zemin parlaklığı -> koyu zemin parlaklığı
_BG_CURVE = [
    (0.60, 0.36), (0.75, 0.28), (0.85, 0.225), (0.90, 0.19), (0.95, 0.15),
    (0.965, 0.10), (0.975, 0.085), (0.985, 0.125), (1.0, 0.155),
]


def _map_bg_rgb(r, g, b):
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if l < 0.60:
        return r, g, b  # koyu / doygun vurgu: aynen kalır
    if l < 0.72 and s > 0.35:
        return r, g, b  # orta-açık doygun vurgu (ör. sarı rozet) aynen kalır
    nl = _interp(_BG_CURVE, l)
    ns = min(1.0, s) * 0.55
    if s < 0.15:  # nötr gri / beyaz: soğuk (mavi) bir ton kat, "kömür grisi" görünmesin
        h, ns = 0.600, 0.30
    return colorsys.hls_to_rgb(h, nl, ns)


def _map_text_rgb(r, g, b):
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if l >= 0.70:
        return r, g, b  # zaten açık metin (koyu zemin üstü)
    nl = max(0.66, 0.97 - 0.80 * l)
    # koyu lacivert metinler (başlıklar) yumuşak, hafif mavimsi beyaza dönüşsün
    ns = s * (0.45 if l < 0.30 else 0.85 if s < 0.9 else 1.0)
    return colorsys.hls_to_rgb(h, nl, ns)


def bg_hex(color: str) -> str:
    """Zemin / kenarlık rengi için koyu karşılık (#RRGGBB)."""
    if not _dark or not isinstance(color, str):
        return color
    rgb = _parse_hex(color) if color.startswith("#") else None
    if rgb is None:
        return color
    return _to_hex(*_map_bg_rgb(*rgb))


def border_hex(color: str) -> str:
    """Kenarlık / ayırıcı çizgiler için: zemin dönüşümüne ek olarak bir ton açılır (daha okunur)."""
    if not _dark or not isinstance(color, str):
        return color
    rgb = _parse_hex(color) if color.startswith("#") else None
    if rgb is None:
        return color
    r, g, b = _map_bg_rgb(*rgb)
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    if _first_l(rgb) >= 0.60:  # yalnızca açık çizgiler (koyu/vurgu kenarlıklar aynen kalır)
        l = min(0.5, l + 0.06)
    return _to_hex(*colorsys.hls_to_rgb(h, l, sat))


def _first_l(rgb) -> float:
    return colorsys.rgb_to_hls(*rgb)[1]


def fg_hex(color: str) -> str:
    """Metin / çizgi rengi için koyu zemin üstünde okunur karşılık."""
    if not _dark or not isinstance(color, str):
        return color
    rgb = _parse_hex(color) if color.startswith("#") else None
    if rgb is None:
        return color
    return _to_hex(*_map_text_rgb(*rgb))


def auto_hex(color: str) -> str:
    """Bağlamı bilinmeyen çizim rengi: açık ise zemin, koyu ise metin sayılır."""
    if not _dark or not isinstance(color, str):
        return color
    rgb = _parse_hex(color) if color.startswith("#") else None
    if rgb is None:
        return color
    _, l, _ = colorsys.rgb_to_hls(*rgb)
    if l >= 0.60:
        return _to_hex(*_map_bg_rgb(*rgb))
    if l < 0.50:
        return _to_hex(*_map_text_rgb(*rgb))
    return color


# ----------------------------------------------------------------------
# QSS dönüşümü
# ----------------------------------------------------------------------
_COLOR_TOKEN = re.compile(
    r"(?<![\w#])(#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b"
    r"|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[\d.]+\s*)?\)"
    r"|\bwhite\b|\bblack\b)"
)
_BLOCK = re.compile(r"([^{}]*)\{([^{}]*)\}", re.S)
_DECL = re.compile(r"([\w-]+)\s*:\s*([^;]+);?")

_TEXT_PROPS = {"color", "selection-color"}
_BG_PROPS = {
    "background", "background-color", "alternate-background-color",
    "selection-background-color", "gridline-color",
}


def _is_bg_prop(prop: str) -> bool:
    return prop in _BG_PROPS or prop.startswith("border") or prop in ("outline",)


def _convert_token(tok: str, fn) -> str:
    low = tok.lower()
    if low == "white":
        return fn("#FFFFFF")
    if low == "black":
        return tok
    if low.startswith("rgb"):
        nums = re.findall(r"[\d.]+", tok)
        r, g, b = (int(float(n)) for n in nums[:3])
        new = fn(_to_hex(r / 255, g / 255, b / 255))
        nr, ng, nb = (int(new[i:i + 2], 16) for i in (1, 3, 5))
        if len(nums) > 3:
            return f"rgba({nr}, {ng}, {nb}, {nums[3]})"
        return f"rgb({nr}, {ng}, {nb})"
    return fn(tok)


def _convert_value(value: str, fn) -> str:
    return _COLOR_TOKEN.sub(lambda m: _convert_token(m.group(1), fn), value)


def _first_color_l(value: str):
    m = _COLOR_TOKEN.search(value)
    if not m:
        return None
    tok = m.group(1)
    if tok.lower() == "white":
        return 1.0, 0.0
    if tok.lower().startswith("rgb"):
        nums = [int(float(n)) for n in re.findall(r"[\d.]+", tok)[:3]]
        rgb = tuple(n / 255 for n in nums)
    else:
        rgb = _parse_hex(tok)
    if rgb is None:
        return None
    _, l, s = colorsys.rgb_to_hls(*rgb)
    return l, s


def _convert_body(body: str) -> str:
    decls = _DECL.findall(body)
    if not decls:
        return body
    # Zemin değişmeden kalıyorsa (doygun düğme / rozet) metin rengi de kalmalı.
    keep_text = False
    for prop, value in decls:
        if prop in ("background", "background-color") and "gradient" not in value:
            ls = _first_color_l(value)
            if ls is not None:
                l, s = ls
                if (0.0 < l < 0.60) or (l < 0.72 and s > 0.35 and l >= 0.60):
                    keep_text = True
    def repl(m):
        prop, value = m.group(1), m.group(2)
        if prop in _TEXT_PROPS:
            if keep_text and prop == "color":
                return m.group(0)
            new = _convert_value(value, fg_hex)
        elif _is_bg_prop(prop):
            new = _convert_value(value, border_hex if (prop.startswith("border") or prop in ("outline", "gridline-color")) else bg_hex)
        else:
            return m.group(0)
        return m.group(0).replace(value, new, 1)
    return _DECL.sub(repl, body)


def transform_qss(qss: str) -> str:
    if not _dark or not qss:
        return qss
    try:
        if "{" not in qss:
            return _convert_body(qss)

        def block(m):
            selector, body = m.group(1), m.group(2)
            if _EXEMPT_RE.search(selector):
                return m.group(0)
            return selector + "{" + _convert_body(body) + "}"
        head, sep, _ = qss.partition("{")
        out = _BLOCK.sub(block, qss)
        # Seçicisiz baştaki bildirimler (nadir): olduğu gibi bırak.
        return out
    except Exception:  # pragma: no cover - görünüm hatası programı durdurmasın
        logger.exception("Koyu tema dönüşümü başarısız")
        return qss


def transform_html(text: str) -> str:
    """Etiketlerdeki satır içi (<span style='color:#..'>) renkleri çevirir."""
    if not _dark or not text or "color" not in text:
        return text
    return re.sub(
        r"(color\s*:\s*)(#[0-9a-fA-F]{6})",
        lambda m: m.group(1) + fg_hex(m.group(2)),
        text,
    )


def exempt(widget) -> None:
    """Widget'ın stil sayfasının koyu modda dönüştürülmesini engeller."""
    widget.setProperty("themeExempt", True)


# ----------------------------------------------------------------------
# Kurulum
# ----------------------------------------------------------------------
def system_prefers_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except Exception:
        return False


def configured_theme() -> str:
    try:
        from services.settings_service import SettingsService
        value = SettingsService.load().get("appearance", {}).get("theme", THEME_LIGHT)
    except Exception:
        value = THEME_LIGHT
    return value if value in THEME_LABELS else THEME_LIGHT


def install(force: str | None = None) -> bool:
    """Temayı çalışma anında etkinleştirir. UI modülleri import edilmeden ÖNCE çağrılmalıdır."""
    global _dark, _installed
    if _installed:
        return _dark
    mode = force or configured_theme()
    _dark = system_prefers_dark() if mode == THEME_SYSTEM else mode == THEME_DARK
    _installed = True
    if not _dark:
        return False

    from PySide6 import QtGui, QtWidgets

    raw_color = QtGui.RawQColor = getattr(QtGui, "RawQColor", QtGui.QColor)

    class ThemedQColor(raw_color):
        def __init__(self, *args):
            if len(args) == 1 and isinstance(args[0], str) and args[0].startswith("#"):
                args = (auto_hex(args[0]),)
            super().__init__(*args)

    QtGui.QColor = ThemedQColor

    original = QtWidgets.QWidget.setStyleSheet

    def set_style_sheet(self, sheet):
        try:
            if not self.property("themeExempt"):
                sheet = transform_qss(sheet)
        except Exception:
            pass
        original(self, sheet)

    QtWidgets.QWidget.setStyleSheet = set_style_sheet

    for cls in (QtWidgets.QLabel,):
        original_set_text = cls.setText

        def set_text(self, text, _orig=original_set_text):
            if isinstance(text, str) and "<" in text:
                text = transform_html(text)
            _orig(self, text)
        cls.setText = set_text
    return True


def raw_qcolor():
    """Dönüştürülmeyen (olduğu gibi) QColor sınıfı - yan menü gibi sabit renkler için."""
    from PySide6 import QtGui
    return getattr(QtGui, "RawQColor", QtGui.QColor)


def apply_palette(app) -> None:
    """Qt'nin kendi çizdiği öğeler (kaydırma çubuğu, menü, ipucu) için koyu palet."""
    if not _dark:
        return
    from PySide6.QtGui import QPalette
    RC = raw_qcolor()
    p = QPalette()
    roles = {
        QPalette.Window: "#0E1623", QPalette.WindowText: "#E4EAF4",
        QPalette.Base: "#161F2E", QPalette.AlternateBase: "#1A2434",
        QPalette.ToolTipBase: "#1E2A3D", QPalette.ToolTipText: "#E4EAF4",
        QPalette.Text: "#E4EAF4", QPalette.Button: "#1E2A3D",
        QPalette.ButtonText: "#E4EAF4", QPalette.BrightText: "#FFFFFF",
        QPalette.Link: "#5B9BF5", QPalette.Highlight: "#2167D5",
        QPalette.HighlightedText: "#FFFFFF",
        QPalette.PlaceholderText: "#7F8DA6",
    }
    for role, col in roles.items():
        p.setColor(role, RC(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, RC("#6B778D"))
    app.setPalette(p)
