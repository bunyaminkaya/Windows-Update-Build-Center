from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QAbstractItemView,
    QLineEdit, QGridLayout
)

from app.paths import SETTINGS_PATH
from services.download_manager import DownloadManager
from services.iso_build_manager import IsoBuildManager
from ui.widgets.modern_combo_box import ModernComboBox
from ui.widgets.message_dialog import show_error, show_information, show_success, ask_confirmation


@dataclass
class IsoRecord:
    path: Path
    build: str = "—"
    architecture: str = "—"
    language: str = "—"
    edition: str = "—"
    product: str = "Windows"

    @property
    def size_text(self) -> str:
        try:
            size = self.path.stat().st_size
        except OSError:
            return "—"
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        unit = units[0]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                break
            value /= 1024
        return f"{value:.2f} {unit}" if unit in {"GB", "TB"} else f"{value:.1f} {unit}"

    @property
    def modified_text(self) -> str:
        try:
            return datetime.fromtimestamp(self.path.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
        except OSError:
            return "—"


class HashWorker(QThread):
    completed = Signal(str, str)
    failed = Signal(str)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            digest = hashlib.sha256()
            with self.path.open("rb") as handle:
                while True:
                    chunk = handle.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            self.completed.emit(str(self.path), digest.hexdigest().upper())
        except Exception as exc:
            self.failed.emit(str(exc))


class IsoCenterPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[IsoRecord] = []
        self.filtered_records: list[IsoRecord] = []
        self.selected_record: IsoRecord | None = None
        self._hash_worker: HashWorker | None = None
        self._hash_cache: dict[str, str] = {}
        self._build_ui()
        self.refresh_scan()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(14)

        title = QLabel("Windows ISO Merkezi")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        subtitle = QLabel("Oluşturduğunuz ve bilgisayarınızdaki Windows ISO dosyalarını tek merkezden yönetin.")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(subtitle)

        controls = QFrame(); controls.setObjectName("isoCard")
        cl = QVBoxLayout(controls); cl.setContentsMargins(14, 14, 14, 14); cl.setSpacing(10)
        top = QHBoxLayout(); top.setSpacing(8)
        self.search = QLineEdit(); self.search.setPlaceholderText("ISO adı, build veya sürüm ara...")
        self.search.textChanged.connect(self._apply_filters)
        top.addWidget(self.search, 1)
        refresh = QPushButton("Yeniden Tara"); refresh.clicked.connect(self.refresh_scan); top.addWidget(refresh)
        add_folder = QPushButton("ISO Klasörü Ekle"); add_folder.clicked.connect(self._add_folder); top.addWidget(add_folder)
        cl.addLayout(top)

        filters = QHBoxLayout(); filters.setSpacing(8)
        self.build_filter = self._combo("Build: Tüm Build'ler")
        self.arch_filter = self._combo("Mimari: Tüm Mimariler")
        self.lang_filter = self._combo("Dil: Tüm Diller")
        self.edition_filter = self._combo("Edition: Tüm Edition'lar")
        for combo in (self.build_filter, self.arch_filter, self.lang_filter, self.edition_filter):
            combo.currentIndexChanged.connect(self._apply_filters)
            filters.addWidget(combo, 1)
        cl.addLayout(filters)
        root.addWidget(controls)

        body = QHBoxLayout(); body.setSpacing(12)
        table_card = QFrame(); table_card.setObjectName("isoCard")
        tl = QVBoxLayout(table_card); tl.setContentsMargins(10, 10, 10, 10)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["ISO Dosyası", "Build", "Mimari", "Dil", "Edition", "Boyut", "Tarih", "Konum"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 7): self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        tl.addWidget(self.table)
        body.addWidget(table_card, 3)

        detail = QFrame(); detail.setObjectName("isoCard"); detail.setMinimumWidth(330); detail.setMaximumWidth(410)
        dl = QVBoxLayout(detail); dl.setContentsMargins(16, 16, 16, 16); dl.setSpacing(12)
        h = QLabel("Seçili ISO"); h.setObjectName("sectionTitle"); dl.addWidget(h)
        self.detail_title = QLabel("Listeden bir ISO seçin"); self.detail_title.setWordWrap(True); self.detail_title.setObjectName("isoDetailTitle"); dl.addWidget(self.detail_title)
        self.info_labels = {}
        grid = QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)
        for idx, key in enumerate(["Build", "Mimari", "Dil", "Edition", "Boyut", "Tarih", "SHA-256"]):
            box = QFrame(); box.setObjectName("infoTile")
            bl = QVBoxLayout(box); bl.setContentsMargins(9, 7, 9, 7); bl.setSpacing(2)
            k = QLabel(key); k.setObjectName("tileKey"); v = QLabel("—"); v.setObjectName("tileValue"); v.setWordWrap(True)
            bl.addWidget(k); bl.addWidget(v); self.info_labels[key] = v
            if key == "SHA-256": grid.addWidget(box, 3, 0, 1, 2)
            else: grid.addWidget(box, idx // 2, idx % 2)
        dl.addLayout(grid)
        self.path_label = QLabel("Konum: —"); self.path_label.setWordWrap(True); self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse); dl.addWidget(self.path_label)
        dl.addStretch()
        self.open_btn = QPushButton("ISO Klasörünü Aç"); self.open_btn.clicked.connect(self._open_folder)
        self.mount_btn = QPushButton("ISO'yu Bağla"); self.mount_btn.clicked.connect(self._mount_iso)
        self.hash_btn = QPushButton("SHA-256 Doğrula"); self.hash_btn.clicked.connect(self._hash_iso)
        self.usb_btn = QPushButton("USB Hazırlamaya Gönder"); self.usb_btn.clicked.connect(self._usb_placeholder)
        self.delete_btn = QPushButton("ISO'yu Sil"); self.delete_btn.setProperty("danger", True); self.delete_btn.clicked.connect(self._delete_iso)
        for b in (self.open_btn, self.mount_btn, self.hash_btn, self.usb_btn, self.delete_btn):
            b.setEnabled(False); b.setMinimumHeight(38); dl.addWidget(b)
        body.addWidget(detail, 1)
        root.addLayout(body, 1)

        self.setStyleSheet("""
            QFrame#isoCard { background:#FFFFFF; border:1px solid #D9E4F2; border-radius:10px; }
            QLineEdit, QComboBox { background:#FFFFFF; border:1px solid #C9D7E8; border-radius:8px; padding:8px 10px; min-height:22px; }
            QPushButton { background:#246BD8; color:white; border:none; border-radius:7px; padding:8px 14px; font-weight:600; }
            QPushButton:hover { background:#1D5FC5; }
            QPushButton:disabled { background:#D7DEE8; color:#8C9AAF; }
            QPushButton[danger="true"] { background:#FFFFFF; color:#D63A3A; border:1px solid #F1A8A8; }
            QPushButton[danger="true"]:hover { background:#FFF0F0; }
            QTableWidget { background:#FFFFFF; border:none; gridline-color:#E7EDF5; selection-background-color:#D9E9FF; selection-color:#0B1736; }
            QHeaderView::section { background:#EAF2FD; color:#17345C; padding:8px; border:none; border-right:1px solid #D6E1F0; font-weight:600; }
            QLabel#sectionTitle, QLabel#isoDetailTitle { color:#0B1736; font-size:16px; font-weight:700; }
            QFrame#infoTile { background:#F5F8FC; border:1px solid #D9E4F2; border-radius:8px; }
            QLabel#tileKey { color:#7B8DA5; font-size:11px; }
            QLabel#tileValue { color:#10264A; font-size:13px; font-weight:600; }
        """)

    def _combo(self, first: str):
        combo = ModernComboBox()
        combo.addItem(first)
        return combo

    def _combo_value(self, text: str) -> str:
        return text.split(": ", 1)[1] if ": " in text else text

    def _load_settings(self):
        try: return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception: return {}

    def _save_settings(self, data):
        try: SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception: pass

    def _scan_roots(self) -> list[Path]:
        roots: list[Path] = []
        settings = self._load_settings()
        for raw in settings.get("iso_scan_folders", []):
            p = Path(raw)
            if p.exists(): roots.append(p)
        for state in IsoBuildManager.instance().all_states().values():
            iso = state.get("iso_path", "")
            if iso:
                p = Path(iso)
                if p.exists(): roots.append(p.parent)
            meta = state.get("metadata", {}) or {}
            project = meta.get("project_dir", "")
            if project:
                p = Path(project)
                if p.exists(): roots.append(p)
        for job in DownloadManager.instance().all_jobs():
            try:
                p = Path(job.target_path)
                if p.exists(): roots.append(p.parent)
            except Exception: pass
        # Deduplicate and prefer shallow roots only once.
        out = []
        seen = set()
        for root in roots:
            key = str(root.resolve()).lower()
            if key not in seen:
                seen.add(key); out.append(root)
        return out

    def refresh_scan(self):
        found: dict[str, IsoRecord] = {}
        states = IsoBuildManager.instance().all_states()
        state_by_iso = {}
        for state in states.values():
            p = state.get("iso_path", "")
            if p: state_by_iso[str(Path(p).resolve()).lower()] = state
        for root in self._scan_roots():
            try:
                for path in root.rglob("*.iso"):
                    key = str(path.resolve()).lower()
                    meta = (state_by_iso.get(key, {}).get("metadata", {}) or {})
                    found[key] = self._record_from_path(path, meta)
            except (OSError, PermissionError):
                continue
        self.records = sorted(found.values(), key=lambda r: r.path.stat().st_mtime if r.path.exists() else 0, reverse=True)
        self._populate_filters(); self._apply_filters()

    def _record_from_path(self, path: Path, meta: dict) -> IsoRecord:
        name = path.stem
        build = str(meta.get("build", meta.get("build_number", "")) or "")
        if not build:
            m = re.search(r"(?<!\d)(\d{5}\.\d+)(?!\d)", name); build = m.group(1) if m else "—"
        arch = str(meta.get("architecture", "") or "")
        if not arch:
            for token in ("ARM64", "x64", "x86"):
                if token.lower() in name.lower(): arch = token; break
        lang = str(meta.get("language", meta.get("lang", "")) or "—")
        edition = str(meta.get("edition", "") or "")
        if not edition:
            lower = name.lower()
            edition = "Windows 11 Pro" if "professional" in lower or "_pro" in lower else "—"
        product = str(meta.get("product", "Windows") or "Windows")
        return IsoRecord(path=path, build=build or "—", architecture=arch or "—", language=lang, edition=edition, product=product)

    def _populate_filters(self):
        specs = [
            (self.build_filter, "Build: Tüm Build'ler", [f"Build: {v}" for v in sorted({r.build for r in self.records if r.build != "—"})]),
            (self.arch_filter, "Mimari: Tüm Mimariler", [f"Mimari: {v}" for v in sorted({r.architecture for r in self.records if r.architecture != "—"})]),
            (self.lang_filter, "Dil: Tüm Diller", [f"Dil: {v}" for v in sorted({r.language for r in self.records if r.language != "—"})]),
            (self.edition_filter, "Edition: Tüm Edition'lar", [f"Edition: {v}" for v in sorted({r.edition for r in self.records if r.edition != "—"})]),
        ]
        for combo, first, values in specs:
            old = combo.currentText(); combo.blockSignals(True); combo.clear(); combo.addItem(first); combo.addItems(values)
            idx = combo.findText(old); combo.setCurrentIndex(idx if idx >= 0 else 0); combo.blockSignals(False)

    def _apply_filters(self):
        query = self.search.text().strip().lower()
        values = [self._combo_value(self.build_filter.currentText()), self._combo_value(self.arch_filter.currentText()), self._combo_value(self.lang_filter.currentText()), self._combo_value(self.edition_filter.currentText())]
        firsts = ["Tüm Build'ler", "Tüm Mimariler", "Tüm Diller", "Tüm Edition'lar"]
        out = []
        for r in self.records:
            hay = f"{r.path.name} {r.build} {r.architecture} {r.language} {r.edition}".lower()
            if query and query not in hay: continue
            attrs = [r.build, r.architecture, r.language, r.edition]
            if any(v != f and v != a for v, f, a in zip(values, firsts, attrs)): continue
            out.append(r)
        self.filtered_records = out
        self.table.setRowCount(len(out))
        for row, r in enumerate(out):
            vals = [r.path.name, r.build, r.architecture, r.language, r.edition, r.size_text, r.modified_text, str(r.path.parent)]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val); item.setToolTip(str(r.path) if col in {0,7} else val); self.table.setItem(row, col, item)
        self.selected_record = None; self._render_detail()

    def _selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        self.selected_record = self.filtered_records[rows[0].row()] if rows else None
        self._render_detail()

    def _render_detail(self):
        r = self.selected_record; enabled = r is not None
        for b in (self.open_btn, self.mount_btn, self.hash_btn, self.usb_btn, self.delete_btn): b.setEnabled(enabled)
        if not r:
            self.detail_title.setText("Listeden bir ISO seçin")
            for label in self.info_labels.values(): label.setText("—")
            self.path_label.setText("Konum: —"); return
        self.detail_title.setText(r.path.name)
        data = {"Build":r.build,"Mimari":r.architecture,"Dil":r.language,"Edition":r.edition,"Boyut":r.size_text,"Tarih":r.modified_text,"SHA-256":self._hash_cache.get(str(r.path), "Henüz doğrulanmadı")}
        for k,v in data.items(): self.info_labels[k].setText(v)
        self.path_label.setText(f"Konum: {r.path}")

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "ISO klasörü seç")
        if not folder: return
        settings = self._load_settings(); folders = list(settings.get("iso_scan_folders", []))
        if folder not in folders: folders.append(folder)
        settings["iso_scan_folders"] = folders; self._save_settings(settings); self.refresh_scan()

    def _open_folder(self):
        r = self.selected_record
        if not r: return
        try:
            if os.name == "nt": subprocess.Popen(["explorer.exe", "/select,", str(r.path)])
            else: subprocess.Popen(["xdg-open", str(r.path.parent)])
        except Exception as exc: show_error(self, "ISO Klasörü", str(exc), "Klasör açılamadı")

    def _mount_iso(self):
        r = self.selected_record
        if not r: return
        try:
            if os.name == "nt": os.startfile(str(r.path))
            else: show_information(self, "ISO Bağlama", "Otomatik ISO bağlama şu anda Windows üzerinde destekleniyor.")
        except Exception as exc: show_error(self, "ISO Bağlama", str(exc), "ISO bağlanamadı")

    def _hash_iso(self):
        r = self.selected_record
        if not r or self._hash_worker is not None: return
        self.hash_btn.setEnabled(False); self.hash_btn.setText("SHA-256 hesaplanıyor...")
        self._hash_worker = HashWorker(r.path)
        self._hash_worker.completed.connect(self._hash_done); self._hash_worker.failed.connect(self._hash_failed); self._hash_worker.start()

    def _hash_done(self, path: str, digest: str):
        self._hash_cache[path] = digest; self._hash_worker = None; self.hash_btn.setText("SHA-256 Doğrula"); self._render_detail()
        show_success(self, "SHA-256", digest, "Doğrulama tamamlandı")

    def _hash_failed(self, error: str):
        self._hash_worker = None; self.hash_btn.setText("SHA-256 Doğrula"); self._render_detail(); show_error(self, "SHA-256", error, "Doğrulama başarısız")

    def _delete_iso(self):
        r = self.selected_record
        if not r: return
        if not ask_confirmation(self, "ISO'yu Sil", f"{r.path.name}\n\nBu dosya diskten kalıcı olarak silinecek.", destructive=True, confirm_text="ISO'yu Sil"):
            return
        try: r.path.unlink(); self.refresh_scan(); show_success(self, "ISO Silindi", "ISO dosyası diskten silindi.")
        except Exception as exc: show_error(self, "ISO Silme", str(exc), "Dosya silinemedi")

    def _usb_placeholder(self):
        show_information(self, "USB Hazırlama Merkezi", "ISO seçimi hazır. USB hazırlama modülü bir sonraki geliştirme aşamasında etkinleştirilecek.")
