"""Çalışma anında arayüz dili (Türkçe/İngilizce).

Kaynak dil Türkçedir. İngilizce seçiliyse Qt'ye verilen görünür metinler (etiket, düğme,
ipucu, tablo başlığı, pencere başlığı, dosya penceresi…) ``app/i18n_en.py`` sözlüğüyle
çevrilir; sözlükte olmayan metin olduğu gibi (Türkçe) kalır. Böylece eksik çeviri
programı bozmaz. Mantıkta kullanılan metinlere (combo değerleri, tablo hücreleri,
ayar değerleri) dokunulmaz.

``install()`` arayüz modülleri import edilmeden ÖNCE çağrılmalıdır (``ui.theme`` gibi).
Türkçe seçiliyse hiçbir şey yamalanmaz; ek yük yoktur.

Sözlük anahtarı ``{}`` içeriyorsa kalıptır: ``"{} sürücü bulundu"`` -> ``"{} drivers found"``.
Yakalanan parçalar da ayrıca çevrilir. Kayıt modu: ``WUBC_I18N_RECORD=dosya.json`` ortam
değişkeniyle çevrilmeyen metinler o dosyaya yazılır (geliştirme aracı).
"""
from __future__ import annotations

import atexit
import json
import os
import re

LANG_AUTO = "auto"
LANG_TR = "tr"
LANG_EN = "en"
LANG_LABELS = {LANG_AUTO: "Otomatik (Windows dili)", LANG_TR: "Türkçe", LANG_EN: "English"}

_lang = LANG_TR
_installed = False
_exact: dict[str, str] = {}
_patterns: list[tuple[re.Pattern, str]] = []
_cache: dict[str, str] = {}
_record: set[str] | None = None
_record_path = ""

_TAG = re.compile(r"(<[^>]+>)")
_HAS_LETTER = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü]")


def system_language() -> str:
    """Windows arayüz dili Türkçe ise 'tr', değilse 'en'."""
    try:
        import ctypes
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        return LANG_TR if (langid & 0x3FF) == 0x1F else LANG_EN
    except Exception:
        pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = (os.environ.get(var) or "").lower()
        if value:
            return LANG_TR if value.startswith("tr") else LANG_EN
    return LANG_TR


def configured_language() -> str:
    """Ayarlardaki dil seçimini ('auto' dahil) gerçek koda ('tr'/'en') çevirir."""
    try:
        from services.settings_service import SettingsService
        value = SettingsService.load().get("general", {}).get("language", LANG_AUTO)
    except Exception:
        value = LANG_AUTO
    if value == LANG_AUTO or value not in LANG_LABELS:
        return system_language()
    return value


def current() -> str:
    return _lang


def is_english() -> bool:
    return _lang == LANG_EN


_TOKEN = re.compile(r"(\{#\}|\{\})")


def _compile(entries: dict[str, str]) -> None:
    """``{}`` herhangi bir metni, ``{#}`` yalnızca sayıyı yakalar; çıktıda ikisi de ``{}`` olur."""
    for key, value in entries.items():
        if "{}" in key or "{#}" in key:
            regex = ""
            for part in _TOKEN.split(key):
                if part == "{}":
                    regex += "(.+?)"
                elif part == "{#}":
                    regex += r"(\d+(?:[.,]\d+)?)"
                else:
                    regex += re.escape(part)
            _patterns.append((re.compile(f"^{regex}$", re.DOTALL), value.replace("{#}", "{}")))
        else:
            _exact[key] = value
    _patterns.sort(key=lambda item: len(item[0].pattern), reverse=True)


def _lookup(text: str) -> str | None:
    hit = _exact.get(text)
    if hit is not None:
        return hit
    for pattern, template in _patterns:
        match = pattern.match(text)
        if match:
            groups = [translate(group) for group in match.groups()]
            if re.search(r"\{\d\}", template):  # sıra değiştiren kalıp: {1} ... {0}
                return re.sub(r"\{(\d)\}", lambda m: groups[int(m.group(1))], template)
            out = template
            for group in groups:
                out = out.replace("{}", group, 1)
            return out
    return None


def _translate_core(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()):]
    hit = _lookup(stripped)
    if hit is not None:
        return lead + hit + tail
    if "<" in stripped and ">" in stripped:
        pieces = _TAG.split(stripped)
        changed = False
        for i, piece in enumerate(pieces):
            if not piece or piece.startswith("<"):
                continue
            inner = translate(piece)
            if inner != piece:
                pieces[i] = inner
                changed = True
        if changed:
            return lead + "".join(pieces) + tail
    if "\n" in stripped:
        lines = stripped.split("\n")
        out = [translate(line) if line.strip() else line for line in lines]
        if out != lines:
            return lead + "\n".join(out) + tail
    # "Ad: değer" biçimindeki etiketler
    if ": " in stripped and len(stripped) < 160:
        head, _, rest = stripped.partition(": ")
        head_t = _lookup(head)
        if head_t is not None:
            return lead + f"{head_t}: {translate(rest)}" + tail
    if _record is not None and _HAS_LETTER.search(stripped) and len(stripped) > 1:
        _record.add(stripped)
    return text


def translate(text):
    """Metni geçerli dile çevirir (Türkçede ya da sözlükte yoksa aynen döner)."""
    if _lang != LANG_EN or not isinstance(text, str) or not text:
        return text
    cached = _cache.get(text)
    if cached is not None:
        return cached
    result = _translate_core(text)
    if len(_cache) < 20000:
        _cache[text] = result
    return result


tr = translate


def _flush_record() -> None:
    if _record is None or not _record_path:
        return
    try:
        with open(_record_path, "w", encoding="utf-8") as handle:
            json.dump(sorted(_record), handle, ensure_ascii=False, indent=0)
    except OSError:
        pass


def _wrap_method(cls, name: str, arg_index: int = 0) -> None:
    """cls.name(self, ...) çağrısında arg_index'teki metni çevirir."""
    original = getattr(cls, name, None)
    if original is None:
        return

    def wrapper(self, *args, **kwargs):
        if len(args) > arg_index and isinstance(args[arg_index], str):
            args = args[:arg_index] + (translate(args[arg_index]),) + args[arg_index + 1:]
        return original(self, *args, **kwargs)

    wrapper.__name__ = name
    try:
        setattr(cls, name, wrapper)
    except (TypeError, AttributeError):
        pass


def _wrap_init(cls) -> None:
    original = cls.__init__

    def init(self, *args, **kwargs):
        if args and isinstance(args[0], str):
            args = (translate(args[0]),) + args[1:]
        original(self, *args, **kwargs)

    try:
        cls.__init__ = init
    except (TypeError, AttributeError):
        pass


def _wrap_static(cls, name: str, indexes: tuple[int, ...]) -> None:
    original = getattr(cls, name, None)
    if original is None:
        return

    def wrapper(*args, **kwargs):
        args = list(args)
        for i in indexes:
            if len(args) > i and isinstance(args[i], str):
                args[i] = translate(args[i])
        return original(*args, **kwargs)

    try:
        setattr(cls, name, staticmethod(wrapper))
    except (TypeError, AttributeError):
        pass


def install(force: str | None = None) -> str:
    """Dili etkinleştirir; seçilen dil kodunu döner. UI modüllerinden önce çağrılmalıdır."""
    global _lang, _installed, _record, _record_path
    if _installed:
        return _lang
    _installed = True
    requested = force or configured_language()
    _lang = requested if requested in (LANG_TR, LANG_EN) else LANG_TR
    record = os.environ.get("WUBC_I18N_RECORD", "")
    if record:
        _record, _record_path = set(), record
        atexit.register(_flush_record)
    if _lang != LANG_EN:
        return _lang

    from app.i18n_en import EN
    _compile(EN)

    from PySide6 import QtGui, QtWidgets, QtCore  # noqa: F401

    W = QtWidgets
    _wrap_method(W.QLabel, "setText")
    _wrap_method(W.QAbstractButton, "setText")
    _wrap_method(W.QGroupBox, "setTitle")
    for cls in (W.QLabel, W.QPushButton, W.QCheckBox, W.QRadioButton, W.QToolButton, W.QGroupBox):
        _wrap_init(cls)
    _wrap_method(W.QLineEdit, "setPlaceholderText")
    _wrap_method(W.QPlainTextEdit, "setPlaceholderText")
    _wrap_method(W.QTextEdit, "setPlaceholderText")
    _wrap_method(W.QWidget, "setToolTip")
    _wrap_method(W.QWidget, "setStatusTip")
    _wrap_method(W.QWidget, "setWindowTitle")
    _wrap_method(W.QTabBar, "setTabText", 1)
    for cls in (W.QTabWidget, W.QTabBar):
        for name in ("addTab", "insertTab"):
            original_tab = getattr(cls, name)

            def tab_wrapper(self, *args, _orig=original_tab):
                return _orig(self, *[translate(a) if isinstance(a, str) else a for a in args])

            setattr(cls, name, tab_wrapper)
    _wrap_method(W.QTabWidget, "setTabText", 1)
    _wrap_method(W.QMenu, "setTitle")
    _wrap_method(W.QMenu, "addAction")
    _wrap_method(QtGui.QAction, "setText")

    original_header = W.QTableWidget.setHorizontalHeaderLabels

    def set_header(self, labels):
        original_header(self, [translate(x) if isinstance(x, str) else x for x in labels])

    W.QTableWidget.setHorizontalHeaderLabels = set_header

    original_message = W.QSystemTrayIcon.showMessage

    def show_message(self, title, message, *args, **kwargs):
        return original_message(self, translate(title), translate(message), *args, **kwargs)

    W.QSystemTrayIcon.showMessage = show_message
    _wrap_method(W.QSystemTrayIcon, "setToolTip")

    # Özel çizilen metin (delegeler, grafikler): drawText içindeki tüm str argümanlar
    original_draw = QtGui.QPainter.drawText

    def draw_text(self, *args):
        return original_draw(self, *[translate(a) if isinstance(a, str) else a for a in args])

    try:
        QtGui.QPainter.drawText = draw_text
    except (TypeError, AttributeError):
        pass

    # Varsayılan tablo hücreleri: yalnızca görüntü çevrilir, hücre verisi (mantık) Türkçe kalır
    class _TrDelegate(W.QStyledItemDelegate):
        def initStyleOption(self, option, index):
            super().initStyleOption(option, index)
            if option.text:
                option.text = translate(option.text)

    original_table_init = W.QTableWidget.__init__

    def table_init(self, *args, **kwargs):
        original_table_init(self, *args, **kwargs)
        self._tr_delegate = _TrDelegate(self)
        self.setItemDelegate(self._tr_delegate)

    try:
        W.QTableWidget.__init__ = table_init
    except (TypeError, AttributeError):
        pass
    _wrap_method(W.QTableWidgetItem, "setToolTip")

    # İleti kutuları
    M = W.QMessageBox
    for name in ("setText", "setInformativeText", "setDetailedText", "setCheckBoxText"):
        _wrap_method(M, name)
    for name in ("question", "information", "warning", "critical", "about"):
        _wrap_static(M, name, (1, 2))

    # Dosya seçim pencereleri: (parent, başlık, klasör/dosya, süzgeç)
    _wrap_static(W.QFileDialog, "getExistingDirectory", (1,))
    _wrap_static(W.QFileDialog, "getOpenFileName", (1, 3))
    _wrap_static(W.QFileDialog, "getSaveFileName", (1, 3))
    return _lang
