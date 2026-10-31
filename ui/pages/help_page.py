from __future__ import annotations

import html
import webbrowser

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from app import i18n
from ui import help_content as content
from ui import icons, styles, theme


def _pick(pair) -> str:
    return pair[1] if i18n.is_english() else pair[0]


class HelpPage(QWidget):
    """Programı bölüm bölüm anlatan uygulama içi yardım."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = content.KEYS[0]
        self._build_ui()
        self.show_section(self._current)

    # ---- arayüz ----
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(14)
        title = QLabel("Yardım")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        subtitle = QLabel("Programın her bölümünün ne işe yaradığını ve nasıl kullanılacağını buradan öğrenin.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Yardımda ara...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("helpList")
        self.list.setFixedWidth(250)
        self.list.setFocusPolicy(Qt.NoFocus)
        for section in content.SECTIONS:
            item = QListWidgetItem(_pick(section["title"]))
            item.setData(Qt.UserRole, section["key"])
            self.list.addItem(item)
        self.list.currentItemChanged.connect(self._item_changed)
        left.addWidget(self.list, 1)
        body.addLayout(left)

        self.browser = QTextBrowser()
        self.browser.setObjectName("helpBrowser")
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._open_link)
        body.addWidget(self.browser, 1)

        self.setStyleSheet(styles.qss("""
            QLineEdit { background:#FFFFFF; border:1px solid #C9D7E8; border-radius:8px; padding:8px 10px; min-height:22px; }
            QListWidget#helpList { background:#FFFFFF; border:1px solid #D9E4F2; border-radius:10px; padding:6px; outline:0; }
            QListWidget#helpList::item { padding:9px 10px; border-radius:7px; color:#17345C; }
            QListWidget#helpList::item:selected { background:#D9E9FF; color:#0B1736; font-weight:600; }
            QListWidget#helpList::item:hover:!selected { background:#F0F5FC; }
            QTextBrowser#helpBrowser { background:#FFFFFF; border:1px solid #D9E4F2; border-radius:10px; padding:10px; }
        """))

    # ---- davranış ----
    def show_section(self, key: str):
        """Verilen bölümü (veya sayfa adını) açar."""
        key = content.section_for(key)
        self.search.clear()
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.UserRole) == key:
                self.list.setCurrentItem(item)
                break
        self._render(key)

    def _item_changed(self, current, _previous):
        if current is not None:
            self._render(current.data(Qt.UserRole))

    def _filter(self, text: str):
        needle = text.strip().casefold()
        first = None
        for row in range(self.list.count()):
            item = self.list.item(row)
            section = self._section(item.data(Qt.UserRole))
            hit = not needle or needle in self._haystack(section)
            item.setHidden(not hit)
            if hit and first is None:
                first = item
        current = self.list.currentItem()
        if first is not None and (current is None or current.isHidden()):
            self.list.setCurrentItem(first)

    @staticmethod
    def _section(key):
        return next(s for s in content.SECTIONS if s["key"] == key)

    @staticmethod
    def _haystack(section) -> str:
        parts = [section["key"], *section["title"], *section["what"]]
        for tr, en in section["steps"] + section["notes"]:
            parts += [tr, en]
        return " ".join(parts).casefold()

    def _open_link(self, url: QUrl):
        target = url.toString()
        if target.startswith(("http://", "https://")):
            try:
                webbrowser.open(target)
            except Exception:
                pass
        elif target.startswith("page:"):
            window = self.window()
            if hasattr(window, "show_page_by_name"):
                window.show_page_by_name(target[5:])

    def _render(self, key: str):
        self._current = key
        s = self._section(key)
        dark = theme.is_dark()
        fg, muted, accent, box = ("#E6ECF7", "#9FB0C8", "#6FA8FF", "#1C2B45") if dark else ("#10264A", "#5B6B84", "#2167D5", "#F2F6FC")
        lang_label = lambda tr, en: html.escape(tr if not i18n.is_english() else en)  # noqa: E731
        parts = [f'<h2 style="color:{fg}; margin:0 0 4px 0;">{html.escape(_pick(s["title"]))}</h2>']
        parts.append(f'<p style="color:{muted}; font-size:12px; margin:0 0 10px 0;">{lang_label("Ne işe yarar?", "What is it for?")}</p>')
        # "what" birden çok paragraf olabilir (boş satırla ayrılır).
        for paragraph in _pick(s["what"]).split("\n\n"):
            parts.append(f'<p style="color:{fg}; font-size:14px; line-height:160%; margin:0 0 10px 0;">{html.escape(paragraph.strip())}</p>')
        if s["steps"]:
            parts.append(f'<h3 style="color:{fg}; margin:16px 0 4px 0;">{lang_label("Nasıl kullanılır?", "How to use it")}</h3><ol style="color:{fg}; font-size:14px;">')
            parts += [f'<li style="margin-bottom:8px; line-height:150%;">{html.escape(_pick(step))}</li>' for step in s["steps"]]
            parts.append("</ol>")
        if s["notes"]:
            # Notlar madde imi yerine, düz yazı halinde vurgulu bir kutuda gösterilir.
            parts.append(f'<h3 style="color:{fg}; margin:16px 0 6px 0;">{lang_label("Bilmekte fayda var", "Good to know")}</h3>')
            body = "".join(
                f'<p style="color:{fg}; font-size:14px; line-height:150%; margin:0 0 8px 0;">{html.escape(_pick(note))}</p>'
                for note in s["notes"]
            )
            parts.append(f'<table width="100%" cellspacing="0" cellpadding="10"><tr><td bgcolor="{box}">{body}</td></tr></table>')
        if s["links"]:
            parts.append(f'<h3 style="color:{fg}; margin:16px 0 4px 0;">{lang_label("Daha fazla bilgi (bunyaminkaya.com)", "More information (bunyaminkaya.com)")}</h3><ul style="color:{fg}; font-size:14px;">')
            for tr, en, url in s["links"]:
                parts.append(f'<li style="margin-bottom:6px;"><a style="color:{accent};" href="{html.escape(url)}">{html.escape(en if i18n.is_english() else tr)}</a></li>')
            parts.append("</ul>")
        self.browser.setHtml("".join(parts))
        self.browser.verticalScrollBar().setValue(0)
