from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ui import icons, styles

logger = logging.getLogger(__name__)

STEPS = [
    ("search", "Ara", "Güncelleme Merkezi'nde KB veya build numarasını arayın.",
     "Resmi Microsoft kayıtlarından ilgili güncellemeyi bulun.", "Menüde: Güncelleme Merkezi"),
    ("download", "İndir", "Resmi paketi ya da UUP kaynağını seçip indirin.",
     "İndirme Yöneticisi ilerlemeyi, hızı ve kalan süreyi gösterir.", "Menüde: İndirme Yöneticisi"),
    ("usb", "USB'ye yaz", "ISO'yu USB belleğe yazın, bilgisayarı buradan kurun.",
     "Önyüklenebilir USB birkaç adımda hazırlanır.", "Menüde: USB Kurulum Aracı"),
]


class _ResizeWatcher(QObject):
    """Ana pencere boyutu değişince kaplamayı pencereye uydurur."""

    def __init__(self, overlay: QWidget):
        super().__init__(overlay)
        self._overlay = overlay

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            try:
                self._overlay.setGeometry(obj.rect())
            except RuntimeError:
                pass
        return False


class WelcomeGuide(QWidget):
    """İlk açılış rehberi.

    Ayrı bir pencere (top-level) açmaz: ana pencerenin içinde, karartılmış bir
    katman olarak çizilir. Böylece Windows'ta pencere durumu değişimlerinde
    yanıp sönme / kendiliğinden kapanma gibi sorunlar yaşanmaz. Sadece görünüm.
    """

    closed = Signal(bool)  # True: kullanıcı Atla/Başlayalım dedi

    def __init__(self, window: QWidget, start: int = 0):
        super().__init__(window)
        self.setObjectName("wgOverlay")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._done = False
        self.index = start

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        card = QFrame()
        card.setObjectName("wgCard")
        card.setFixedSize(620, 560)
        outer.addWidget(card, 0, Qt.AlignCenter)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(10, 25, 50, 90))
        card.setGraphicsEffect(shadow)

        root = QVBoxLayout(card)
        root.setContentsMargins(36, 28, 36, 28)
        root.setSpacing(0)
        top = QHBoxLayout()
        self.counter = QLabel()
        self.counter.setObjectName("wgCounter")
        top.addWidget(self.counter)
        top.addStretch(1)
        self.skip = QPushButton("Atla")
        self.skip.setObjectName("wgSkip")
        self.skip.setCursor(Qt.PointingHandCursor)
        self.skip.setAutoDefault(False)
        self.skip.clicked.connect(self._finish)
        top.addWidget(self.skip)
        root.addLayout(top)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        for ic, title, text, sub, where in STEPS:
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setAlignment(Qt.AlignCenter)
            lay.setSpacing(10)
            tile = QLabel()
            tile.setObjectName("wgTile")
            tile.setFixedSize(110, 110)
            tile.setAlignment(Qt.AlignCenter)
            tile.setPixmap(icons.pixmap(ic, "#1768E0", 54, stroke=1.9))
            lay.addWidget(tile, 0, Qt.AlignHCenter)
            lay.addSpacing(18)
            t = QLabel(title)
            t.setObjectName("wgTitle")
            t.setAlignment(Qt.AlignCenter)
            d = QLabel(text)
            d.setObjectName("wgText")
            d.setAlignment(Qt.AlignCenter)
            d.setWordWrap(True)
            s = QLabel(sub)
            s.setObjectName("wgSub")
            s.setAlignment(Qt.AlignCenter)
            s.setWordWrap(True)
            w = QLabel(where)
            w.setObjectName("wgWhere")
            w.setAlignment(Qt.AlignCenter)
            for x in (t, d, s):
                lay.addWidget(x)
            lay.addSpacing(6)
            lay.addWidget(w, 0, Qt.AlignHCenter)
            self.stack.addWidget(page)

        dots = QHBoxLayout()
        dots.setAlignment(Qt.AlignCenter)
        dots.setSpacing(8)
        self.dots = []
        for _ in STEPS:
            dt = QLabel()
            dt.setFixedSize(10, 10)
            self.dots.append(dt)
            dots.addWidget(dt)
        root.addLayout(dots)
        root.addSpacing(18)

        nav = QHBoxLayout()
        nav.setSpacing(12)
        self.back = QPushButton("Geri")
        self.back.setObjectName("wgGhost")
        self.back.setAutoDefault(False)
        self.back.clicked.connect(lambda: self.go(self.index - 1))
        self.next = QPushButton()
        self.next.setObjectName("wgPrimary")
        self.next.setAutoDefault(False)
        self.next.clicked.connect(self._next)
        for b in (self.back, self.next):
            b.setCursor(Qt.PointingHandCursor)
        nav.addWidget(self.back, 1)
        nav.addWidget(self.next, 2)
        root.addLayout(nav)

        self.setStyleSheet(styles.qss("""
            QWidget#wgOverlay { background: rgba(10, 25, 50, 150); }
            QFrame#wgCard { background:#FFFFFF; border:1px solid #DCE5F1; border-radius:20px; }
            QLabel { background:transparent; }
            QLabel#wgCounter { color:#6B7C99; font-size:12px; font-weight:600; }
            QPushButton#wgSkip { background:transparent; border:none; color:#5F7090; font-size:13px; font-weight:600; }
            QPushButton#wgSkip:hover { color:@BLUE@; }
            QLabel#wgTile { background:#E3EEFC; border-radius:55px; }
            QLabel#wgTitle { color:#0A1F44; font-size:28px; font-weight:700; }
            QLabel#wgText { color:#1F2F4D; font-size:15px; font-weight:600; }
            QLabel#wgSub { color:#5F7090; font-size:13px; }
            QLabel#wgWhere { color:@BLUE@; background:#EAF2FE; border-radius:12px; padding:5px 14px; font-size:12px; font-weight:600; }
            QPushButton#wgPrimary { background:@BLUE@; color:#FFF; border:none; border-radius:10px; font-size:14px; font-weight:700; min-height:46px; }
            QPushButton#wgPrimary:hover { background:#135BC4; }
            QPushButton#wgGhost { background:#FFF; color:@BLUE@; border:1px solid #CBD9EC; border-radius:10px; font-size:14px; font-weight:700; min-height:46px; }
            QPushButton#wgGhost:disabled { color:#B6C3D8; background:#F4F7FB; border-color:#E5ECF5; }
        """))

        self._watcher = _ResizeWatcher(self)
        window.installEventFilter(self._watcher)
        self.setGeometry(window.rect())
        self.go(start)

    def go(self, i: int):
        self.index = max(0, min(len(STEPS) - 1, i))
        self.stack.setCurrentIndex(self.index)
        self.counter.setText(f"Adım {self.index + 1} / {len(STEPS)}")
        self.back.setEnabled(self.index > 0)
        self.next.setText("Başlayalım" if self.index == len(STEPS) - 1 else "İleri")
        for k, d in enumerate(self.dots):
            on = k == self.index
            d.setStyleSheet(styles.qss(f"background:{'@BLUE@' if on else '#CBD9EC'}; border-radius:5px;"))

    def _next(self):
        if self.index == len(STEPS) - 1:
            self._finish()
        else:
            self.go(self.index + 1)

    def keyPressEvent(self, event):
        # Esc = Atla; sağ/sol ok tuşları adımlar arasında gezer. (Enter bilerek yok:
        # programı klavyeden başlatırken kazara adım geçilmesin.)
        if event.key() == Qt.Key_Escape:
            self._finish()
        elif event.key() == Qt.Key_Right:
            self._next()
        elif event.key() == Qt.Key_Left:
            self.go(self.index - 1)
        else:
            super().keyPressEvent(event)

    def _finish(self):
        if self._done:
            return
        self._done = True
        logger.info("Karşılama rehberi kapatıldı (kullanıcı onayladı).")
        self.hide()
        self.closed.emit(True)
        self.deleteLater()


def show_welcome_guide(window, on_closed=None) -> WelcomeGuide:
    """Rehberi ana pencerenin içinde gösterir (engellemez)."""
    guide = WelcomeGuide(window)
    if on_closed is not None:
        guide.closed.connect(on_closed)
    guide.show()
    guide.raise_()
    guide.setFocus()
    logger.info("Karşılama rehberi gösterildi.")
    return guide
