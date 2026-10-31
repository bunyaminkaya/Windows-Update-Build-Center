from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ui import styles

from services.download_manager import DownloadManager
from services.iso_batch_view import BatchView, compute_view
from services.iso_build_manager import IsoBuildManager
from services.settings_service import auto_create_iso_enabled

MAX_CARDS = 2


class _Card(QFrame):
    def __init__(self, panel: "IsoBuildPanel", batch_id: str):
        super().__init__()
        self._panel = panel
        self.batch_id = batch_id
        self.setObjectName("isoBatchCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(12)
        left = QVBoxLayout(); left.setSpacing(3)
        self.title = QLabel(); self.title.setObjectName("isoBatchTitle")
        self.text = QLabel(); self.text.setObjectName("isoBatchText"); self.text.setWordWrap(True)
        self.bar = QProgressBar(); self.bar.setTextVisible(False); self.bar.setFixedHeight(5)
        left.addWidget(self.title); left.addWidget(self.text); left.addWidget(self.bar)
        lay.addLayout(left, 1)
        self.primary = QPushButton(); self.primary.setObjectName("isoPrimary"); self.primary.setCursor(Qt.PointingHandCursor)
        self.primary.clicked.connect(lambda: panel._do(self.batch_id, self.view.primary_action))
        self.extra: dict[str, QPushButton] = {}
        buttons = QHBoxLayout(); buttons.setSpacing(8)
        buttons.addWidget(self.primary)
        for key, label in (("details", "Ayrıntılar"), ("cancel", "Durdur"), ("open_iso_center", "ISO Merkezi'nde Göster")):
            b = QPushButton(label); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: panel._do(self.batch_id, k))
            buttons.addWidget(b); self.extra[key] = b
        lay.addLayout(buttons, 0)
        self.view: BatchView | None = None

    def apply(self, view: BatchView) -> None:
        self.view = view
        self.title.setText(view.title)
        self.text.setText(view.text)
        self.primary.setText(view.primary_label)
        self.primary.setEnabled(view.primary_enabled)
        for key, button in self.extra.items():
            button.setVisible(key in view.actions)
        if view.phase in ("downloading", "download_problem") and view.total:
            self.bar.setRange(0, view.total); self.bar.setValue(view.done); self.bar.setVisible(True)
        elif view.phase == "building":
            self.bar.setRange(0, 0); self.bar.setVisible(True)
        else:
            self.bar.setVisible(False)


class IsoBuildPanel(QFrame):
    """İndirme Yöneticisi'nde UUP/ISO işlerinin durumunu ve ISO oluşturma düğmesini gösterir."""

    details_requested = Signal(str)
    iso_center_requested = Signal(str)

    def __init__(self, parent=None, manager=None, iso_manager=None):
        super().__init__(parent)
        self.setObjectName("isoBuildPanel")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setStyleSheet(styles.qss("""
            QFrame#isoBuildPanel { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px; }
            QFrame#isoBatchCard { background: #F3F7FC; border: 1px solid #DCE5F1; border-radius: 10px; }
            QLabel { background: transparent; }
            QLabel#isoPanelTitle { color: #0A1F44; font-size: 17px; font-weight: 700; }
            QLabel#isoBatchTitle { color: #0A1F44; font-size: 14px; font-weight: 700; }
            QLabel#isoBatchText { color: #3A4D70; font-size: 13px; }
            QPushButton { background: #FFFFFF; color: @BLUE@; border: 1px solid #CBD9EC; border-radius: 9px;
                padding: 7px 16px; font-weight: 600; min-height: 20px; }
            QPushButton:hover { background: #F1F6FD; border-color: #9DB9E6; }
            QPushButton#isoPrimary { background: #1768E0; color: #FFFFFF; border: none; }
            QPushButton#isoPrimary:hover { background: #135BC4; }
            QPushButton:disabled, QPushButton#isoPrimary:disabled { background: #E6ECF5; color: #8A98B0; border: 1px solid #E6ECF5; }
            QProgressBar { background: #DCE7F7; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: #1768E0; border-radius: 3px; }
        """))
        self.manager = manager or DownloadManager.instance()
        self.iso_manager = iso_manager or IsoBuildManager.instance()
        self._cards: dict[str, _Card] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(8)
        head_row = QHBoxLayout(); head_row.setSpacing(12)
        head = QLabel("ISO Oluşturma"); head.setObjectName("isoPanelTitle")
        self.hint = QLabel(); self.hint.setObjectName("isoBatchText"); self.hint.setWordWrap(True)
        head_row.addWidget(head, 0)
        head_row.addWidget(self.hint, 1)
        lay.addLayout(head_row)
        self._body = QVBoxLayout(); self._body.setSpacing(8)
        lay.addLayout(self._body)

        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        for sig in (self.manager.job_added, self.manager.job_updated):
            sig.connect(lambda *_: self.schedule_refresh())
        for sig in (self.iso_manager.queue_changed,):
            sig.connect(self.schedule_refresh)
        for sig in (self.iso_manager.status_changed, self.iso_manager.build_started, self.iso_manager.build_finished,
                    self.iso_manager.build_failed, self.iso_manager.build_cancelled):
            sig.connect(lambda *_: self.schedule_refresh())
        self.refresh()

    def schedule_refresh(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    # ---- veri ----
    def _batches(self) -> dict[str, list]:
        grouped: dict[str, list] = {}
        for job in self.manager.all_jobs():
            if job.batch_id and job.batch_kind == "uup_iso":
                grouped.setdefault(job.batch_id, []).append(job)
        return grouped

    def refresh(self) -> None:
        auto = auto_create_iso_enabled()
        grouped = self._batches()
        states = self.iso_manager.all_states()
        views = [compute_view(bid, jobs, states.get(bid), auto) for bid, jobs in grouped.items()]
        # Önce işlem bekleyenler/sürenler, sonra bitmişler; en güncel olanlar öne.
        views.sort(key=lambda v: (v.phase == "built", -float(states.get(v.batch_id, {}).get("updated_at", 0) or 0)))
        views = views[:MAX_CARDS]
        keep = {v.batch_id for v in views}
        for bid in list(self._cards):
            if bid not in keep:
                card = self._cards.pop(bid)
                self._body.removeWidget(card); card.deleteLater()
        for index, view in enumerate(views):
            card = self._cards.get(view.batch_id)
            if card is None:
                card = _Card(self, view.batch_id)
                self._cards[view.batch_id] = card
                self._body.insertWidget(index, card)
            card.apply(view)
        self.hint.setText(
            "İndirme bitince ISO kendiliğinden oluşturulur (Ayarlar > UUP / ISO'dan değiştirebilirsiniz)."
            if auto else
            "Otomatik oluşturma kapalı: indirme bitince düğme etkinleşir, ISO'yu siz başlatırsınız."
        )
        self.setVisible(bool(views))

    # ---- eylemler ----
    def _jobs(self, batch_id: str) -> list:
        return self._batches().get(batch_id, [])

    def _do(self, batch_id: str, action: str) -> None:
        jobs = self._jobs(batch_id)
        state = self.iso_manager.state(batch_id)
        if action == "start" and jobs:
            meta = dict(jobs[0].batch_meta or {})
            self.iso_manager.start_build(batch_id, meta)
        elif action == "retry_downloads":
            ids = [j.id for j in jobs if j.status in ("Hata", "İptal edildi", "İptal Edildi")]
            self.manager.retry_many(ids)
        elif action == "retry_build":
            self.iso_manager.retry_build(batch_id)
        elif action == "cancel":
            self.iso_manager.cancel_build(batch_id)
        elif action == "details":
            self.details_requested.emit(batch_id)
        elif action == "open_iso_center":
            self.iso_center_requested.emit(batch_id)
        elif action == "open_folder":
            target = state.get("iso_path", "")
            folder = Path(target).parent if target else Path((state.get("metadata", {}) or {}).get("project_dir", ""))
            if str(folder) and folder.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self.schedule_refresh()
