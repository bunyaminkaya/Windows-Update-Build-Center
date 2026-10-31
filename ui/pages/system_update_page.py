from __future__ import annotations

import ctypes
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QFrame, QFileDialog, QMessageBox, QTextEdit, QCheckBox, QDialog,
    QDialogButtonBox, QAbstractItemView, QComboBox
)

from ui import styles
from services.windows_update_service import WindowsUpdateService, SystemSnapshot
from services.catalog_service import CatalogService
from services.package_service import PackageService
from services.build_tracker_service import BuildTrackerService
from services.download_manager import DownloadManager
from services.settings_service import SettingsService


class _Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class PackageDetailsDialog(QDialog):
    def __init__(self, package, snapshot: SystemSnapshot | None, parent=None):
        super().__init__(parent)
        self.package = package
        self.snapshot = snapshot
        self.setWindowTitle(f"KB Paket Ayrıntısı • {package.filename}")
        self.resize(920, 650)
        root = QVBoxLayout(self)
        title = QLabel(package.update_title or package.filename)
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        meta = QTableWidget(0, 2)
        meta.setHorizontalHeaderLabels(["Alan", "Değer"])
        meta.setEditTriggers(QAbstractItemView.NoEditTriggers)
        meta.setSelectionBehavior(QAbstractItemView.SelectRows)
        meta.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        meta.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        rows = [
            ("KB / Update ID", f"{getattr(package, 'update_title', '')} / {package.update_id}"),
            ("Dosya", package.filename),
            ("Tür", package.file_type),
            ("Mimari", package.architecture),
            ("Boyut", package.size),
            ("Ürün / Windows", package.product or "—"),
            ("Sınıflandırma", package.classification or "—"),
            ("Sürüm", package.version or "—"),
            ("Catalog tarihi", package.last_updated or "—"),
            ("Öneri", "ÖNERİLEN" if package.recommended else "Alternatif"),
            ("Öneri gerekçesi", package.recommendation_reason or "—"),
            ("Build Tracker değişiklik özeti", getattr(package, "tracker_description", "") or "Bu KB için Build Tracker açıklaması bulunamadı."),
            ("Supersedence", getattr(package, "supersedence", "") or "Catalog arama sonucu doğrudan supersedence zinciri sağlamıyor; kurulum öncesi hedef build/KB karşılaştırması zorunlu."),
            ("Kaynak URL", package.direct_url),
            ("Kurulum", (f"wusa.exe \"{package.filename}\" /quiet /norestart" if package.file_type.upper()=="MSU" else f"DISM.exe /Online /Add-Package /PackagePath:\"{package.filename}\" /NoRestart" if package.file_type.upper()=="CAB" else f"\"{package.filename}\" /quiet /norestart")),
            ("Kaldırma", WindowsUpdateService.uninstall_command(getattr(self, "selected_kb", "")) or "Bu paket türü için KB kaldırma komutu bulunamadı."),
        ]
        for a, b in rows:
            r = meta.rowCount(); meta.insertRow(r)
            meta.setItem(r, 0, QTableWidgetItem(a)); meta.setItem(r, 1, QTableWidgetItem(str(b)))
        root.addWidget(meta, 1)
        note = QLabel(
            "Supersedence: Catalog arama sonucu tek başına bir paketin başka bir KB tarafından "
            "yerine geçirilip geçirilmediğini kesinleştirmez. Bu nedenle program eski/uyumsuz "
            "paketleri puanlamada geriye atar; kurulumdan önce hedef build ve yüklü KB durumu da kontrol edilir."
        )
        note.setWordWrap(True); note.setObjectName("infoNote"); root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject); root.addWidget(buttons)


class SystemUpdatePage(QWidget):
    """6-12: sistem uygunluğu, KB denetimi, doğru paket, doğrulama, kurulum ve sorun giderme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot: SystemSnapshot | None = None
        self.selected_kb = ""
        self._installed_items = []
        self._last_packages = []
        self._last_report = None
        self._verified_files: dict[str, dict] = {}
        self.worker = None
        self._build_ui(); self._apply_styles(); self.refresh_system(); self.refresh_installed()

    def _panel(self, title):
        f = QFrame(); f.setObjectName("updatePanel")
        v = QVBoxLayout(f); v.setContentsMargins(14,14,14,14); v.setSpacing(9)
        if title:
            l = QLabel(title); l.setObjectName("panelTitle"); v.addWidget(l)
        return f, v

    def _build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(24,20,24,20); root.setSpacing(10)
        title=QLabel("Bilgisayar & Güncelleme Merkezi"); title.setObjectName("pageTitle")
        sub=QLabel("Bilgisayarınızın uygunluğunu, yüklü güncellemeleri ve güncelleme işlemlerini güvenli biçimde kontrol edin.")
        sub.setObjectName("pageSubtitle"); root.addWidget(title); root.addWidget(sub)
        self.tabs=QTabWidget(); root.addWidget(self.tabs,1)
        self._build_compat_tab(); self._build_installed_tab(); self._build_kb_tab()
        self._build_verify_tab(); self._build_install_tab(); self._build_troubleshoot_tab()

    def _build_compat_tab(self):
        w=QWidget(); v=QVBoxLayout(w); v.setSpacing(10)
        p,pv=self._panel("Uyumluluk")
        desc=QLabel("Seçtiğiniz güncelleme veya build için bilgisayarınızın Windows sürümü, donanımı, güvenlik özellikleri ve kanalını kontrol eder.")
        desc.setWordWrap(True); desc.setObjectName("infoNote"); pv.addWidget(desc)
        row=QHBoxLayout()
        self.compat_target=QLineEdit(); self.compat_target.setPlaceholderText("Hedef KB veya build: KB5071234 / 26100.900")
        self.compat_check=QPushButton("Sistemi ve Hedefi Kontrol Et"); self.compat_check.clicked.connect(self._analyze_target)
        self.compat_latest=QPushButton("Build Tracker Hedefini Al"); self.compat_latest.clicked.connect(self._load_tracker_target)
        row.addWidget(self.compat_target,1); row.addWidget(self.compat_check); row.addWidget(self.compat_latest); pv.addLayout(row)
        self.compat_table=QTableWidget(0,4); self.compat_table.setHorizontalHeaderLabels(["Kontrol","Mevcut / Hedef","Sonuç","Neden / Açıklama"]); self._table_style(self.compat_table); pv.addWidget(self.compat_table,1)
        self.compat_summary=QLabel("Sistem analizi bekleniyor."); self.compat_summary.setWordWrap(True); self.compat_summary.setObjectName("infoNote"); pv.addWidget(self.compat_summary)
        v.addWidget(p,1); self.tabs.addTab(w,"Uyumluluk")

    def _build_installed_tab(self):
        w=QWidget(); v=QVBoxLayout(w)
        desc=QLabel("Bilgisayarınızda yüklü olan Windows KB güncellemelerini görüntüleyin, karşılaştırın ve gerektiğinde güvenli biçimde kaldırın.")
        desc.setWordWrap(True); desc.setObjectName("infoNote"); v.addWidget(desc)
        row=QHBoxLayout()
        self.installed_refresh=QPushButton("Yüklü KB'leri Yenile"); self.installed_refresh.clicked.connect(self.refresh_installed)
        self.compare_tracker=QPushButton("Build Tracker ile Eksik KB Kontrolü"); self.compare_tracker.clicked.connect(self.compare_with_tracker)
        self.failed_btn=QPushButton("Başarısız Güncellemeleri Tara"); self.failed_btn.clicked.connect(self._show_failed_updates)
        self.remove_cmd_btn=QPushButton("Seçili KB Kaldırma Komutu"); self.remove_cmd_btn.clicked.connect(self._show_remove_command)
        self.installed_filter=QLineEdit(); self.installed_filter.setPlaceholderText("KB / açıklama / tarih ara…"); self.installed_filter.textChanged.connect(self._filter_installed)
        for x in (self.installed_refresh,self.compare_tracker,self.failed_btn,self.remove_cmd_btn): row.addWidget(x)
        row.addWidget(self.installed_filter,1); v.addLayout(row)
        self.installed_table=QTableWidget(0,7); self.installed_table.setHorizontalHeaderLabels(["KB","Açıklama","Kurulum tarihi","Kaynak","Kaldırılabilir","Durum","Kaldırma komutu"]); self._table_style(self.installed_table); v.addWidget(self.installed_table,1)
        self.installed_info=QLabel("—"); self.installed_info.setWordWrap(True); self.installed_info.setObjectName("infoNote"); v.addWidget(self.installed_info)
        self.tabs.addTab(w,"Yüklü KB'ler")

    def _build_kb_tab(self):
        w=QWidget(); v=QVBoxLayout(w)
        row=QHBoxLayout(); self.kb_input=QLineEdit(); self.kb_input.setPlaceholderText("KB numarası (örn. KB5066835)")
        self.kb_search=QPushButton("KB'yi Microsoft Catalog'dan Getir"); self.kb_search.clicked.connect(self.search_kb)
        self.kb_only_compatible=QCheckBox("Uyumsuz / Dynamic / Safe OS paketlerini gizle"); self.kb_only_compatible.setChecked(True); self.kb_only_compatible.stateChanged.connect(lambda _=0:self._render_packages())
        row.addWidget(self.kb_input,1); row.addWidget(self.kb_search); row.addWidget(self.kb_only_compatible); v.addLayout(row)
        self.kb_target_summary=QLabel("KB aradıktan sonra ürün, sürüm, mimari, paket türü ve önerilen paket burada gösterilir."); self.kb_target_summary.setWordWrap(True); self.kb_target_summary.setObjectName("infoNote"); v.addWidget(self.kb_target_summary)
        self.kb_table=QTableWidget(0,8); self.kb_table.setHorizontalHeaderLabels(["Dosya","Mimari","Tür","Boyut","Windows / Ürün","Sınıf","Öneri","İşlem"]); self._table_style(self.kb_table); v.addWidget(self.kb_table,1)
        self.kb_table.cellDoubleClicked.connect(self._package_details)
        row2=QHBoxLayout(); self.kb_article=QPushButton("Microsoft Update Catalog'u Aç"); self.kb_article.clicked.connect(self._open_catalog); self.kb_article.setEnabled(False)
        self.kb_download=QPushButton("Seçili Paketi İndirme Yöneticisine Ekle"); self.kb_download.clicked.connect(self._download_selected_package); self.kb_download.setEnabled(False)
        row2.addWidget(self.kb_article); row2.addWidget(self.kb_download); row2.addStretch(1); v.addLayout(row2)
        self.tabs.addTab(w,"KB Ayrıntı & Paket Seçimi")

    def _build_verify_tab(self):
        w=QWidget(); v=QVBoxLayout(w)
        pre=QLabel("GÜVENLİK AKIŞI: indirmeden önce HTTPS + Microsoft kaynak alan adı + mimari/ürün/paket türü kontrol edilir. İndirme bittikten sonra SHA-256 + Authenticode imzası + dosya boyutu/format kontrolü yapılır. Doğrulanmayan paket 11. adıma geçemez.")
        pre.setWordWrap(True); pre.setObjectName("warningNote"); v.addWidget(pre)
        row=QHBoxLayout(); self.verify_path=QLineEdit(); self.verify_path.setPlaceholderText("MSU / CAB / EXE dosyası…")
        self.expected_sha=QLineEdit(); self.expected_sha.setPlaceholderText("Beklenen SHA-256 (opsiyonel)")
        browse=QPushButton("Dosya Seç"); browse.clicked.connect(self._pick_verify_file)
        verify=QPushButton("Şimdi Doğrula"); verify.clicked.connect(self.verify_file)
        row.addWidget(self.verify_path,1); row.addWidget(self.expected_sha,1); row.addWidget(browse); row.addWidget(verify); v.addLayout(row)
        self.verify_output=QTextEdit(); self.verify_output.setReadOnly(True); v.addWidget(self.verify_output,1)
        self.tabs.addTab(w,"İndirme Doğrulaması")

    def _build_install_tab(self):
        w=QWidget(); v=QVBoxLayout(w)
        self.admin_label=QLabel(); self.admin_label.setWordWrap(True); self.admin_label.setObjectName("infoNote"); v.addWidget(self.admin_label)
        self.install_precheck=QLabel("Kurulumdan önce program dosyayı tekrar doğrular; geri yükleme noktası ve yönetici yetkisi ayrıca kontrol edilir."); self.install_precheck.setWordWrap(True); self.install_precheck.setObjectName("warningNote"); v.addWidget(self.install_precheck)
        row=QHBoxLayout(); self.install_path=QLineEdit(); self.install_path.setPlaceholderText("Kurulacak MSU / CAB / EXE")
        b=QPushButton("Dosya Seç"); b.clicked.connect(self._pick_install_file); row.addWidget(self.install_path,1); row.addWidget(b); v.addLayout(row)
        grid=QGridLayout(); self.restore_cb=QCheckBox("Kurulumdan önce geri yükleme noktası oluştur"); self.restore_cb.setChecked(True)
        self.silent_cb=QCheckBox("Sessiz kurulum / yeniden başlatma yapma"); self.silent_cb.setChecked(True)
        self.verify_before_install_cb=QCheckBox("Kurulumdan hemen önce güvenlik doğrulamasını zorunlu tut"); self.verify_before_install_cb.setChecked(True)
        grid.addWidget(self.restore_cb,0,0); grid.addWidget(self.silent_cb,0,1); grid.addWidget(self.verify_before_install_cb,1,0,1,2); v.addLayout(grid)
        self.install_btn=QPushButton("Doğrula ve Güncellemeyi Kur"); self.install_btn.setObjectName("dangerButton"); self.install_btn.clicked.connect(self.install_package); v.addWidget(self.install_btn)
        self.install_output=QTextEdit(); self.install_output.setReadOnly(True); v.addWidget(self.install_output,1)
        self._update_admin_state(); self.tabs.addTab(w,"Kurulum Merkezi")

    def _build_troubleshoot_tab(self):
        w=QWidget(); v=QVBoxLayout(w)
        row=QHBoxLayout(); b=QPushButton("Tam Windows Update Analizi"); b.clicked.connect(self.troubleshoot); self.export_btn=QPushButton("Raporu Kaydet"); self.export_btn.clicked.connect(self.save_report); self.export_btn.setEnabled(False); row.addWidget(b); row.addWidget(self.export_btn); v.addLayout(row)
        self.trouble_table=QTableWidget(0,3); self.trouble_table.setHorizontalHeaderLabels(["Kontrol","Sonuç","Açıklama"]); self._table_style(self.trouble_table); v.addWidget(self.trouble_table,1)
        self.trouble_output=QTextEdit(); self.trouble_output.setReadOnly(True); v.addWidget(self.trouble_output,1); self.tabs.addTab(w,"Sorun Giderme")

    @staticmethod
    def _table_style(t):
        t.setAlternatingRowColors(True); t.setSelectionBehavior(QAbstractItemView.SelectRows); t.setEditTriggers(QAbstractItemView.NoEditTriggers); t.horizontalHeader().setStretchLastSection(True); t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def _run(self, fn, done, button=None):
        if self.worker and self.worker.isRunning(): return
        if button: button.setEnabled(False)
        self.worker=_Worker(fn,self); self.worker.done.connect(done); self.worker.failed.connect(lambda e:self._worker_error(e,button)); self.worker.finished.connect(lambda:(button.setEnabled(True) if button else None)); self.worker.start()

    def _worker_error(self,msg,button=None):
        if button: button.setEnabled(True)
        QMessageBox.warning(self,"İşlem başarısız",msg)

    def refresh_system(self): self._run(WindowsUpdateService.snapshot,self._system_loaded,self.compat_check)
    def _system_loaded(self,s): self.snapshot=s; self._render_compat(WindowsUpdateService.compatibility(s))

    def _render_compat(self, rows):
        self.compat_table.setRowCount(0)
        for row in rows:
            vals=list(row) + [""] * (4-len(row)); r=self.compat_table.rowCount(); self.compat_table.insertRow(r)
            for c,val in enumerate(vals[:4]): self.compat_table.setItem(r,c,QTableWidgetItem(str(val)))
        ok=sum(1 for r in rows if str(r[2]) in {"Uygun","Eşleşiyor","Aynı veya daha yeni","Hazır"})
        self.compat_summary.setText(f"Kontrol tamamlandı: {ok}/{len(rows)} temel kontrol uygun veya bilgilendirici. 'Kontrol gerekli' sonucu, hedef sürüm/build ve Windows Update kanalının ayrıca incelenmesi gerektiğini belirtir.")

    def _analyze_target(self):
        target=self.compat_target.text().strip()
        if not target: self.refresh_system(); return
        def job():
            s=WindowsUpdateService.snapshot()
            if re.fullmatch(r"KB?\s*\d+",target,re.I):
                kb="KB"+re.sub(r"\D","",target)
                updates=CatalogService().search(kb)
                return s, updates[0] if updates else None
            return s,target
        def done(data):
            s,obj=data; self.snapshot=s
            rows=WindowsUpdateService.compatibility(s,obj if not isinstance(obj,str) else None)
            if isinstance(obj,str): rows.append(("Hedef build",obj,"Daha yeni" if WindowsUpdateService._build_tuple(s.build)<WindowsUpdateService._build_tuple(obj) else "Aynı veya daha yeni","Yerel build ile karşılaştırıldı."))
            else:
                if obj:
                    rows += [("Hedef KB",obj.title,"Bulundu","Microsoft Update Catalog kaydı bulundu."),("Hedef ürün",obj.product or "—","Kontrol gerekli","Catalog ürün alanı mevcut."),("Hedef mimari",getattr(obj,'architecture','—'),"Kontrol gerekli","Paket mimarisi ayrıca 8–9 adımında eşleştirilir.")]
                else: rows.append(("Hedef KB",target,"Bulunamadı","Microsoft Update Catalog kaydı alınamadı."))
            self._render_compat(rows)
        self._run(job,done,self.compat_check)

    def _load_tracker_target(self):
        def job():
            records,_=BuildTrackerService().fetch(); return records[0] if records else None
        def done(record):
            if not record:return
            self.compat_target.setText(record.kb_number or record.build_number)
            self.snapshot=self.snapshot or WindowsUpdateService.snapshot()
            self._render_compat(WindowsUpdateService.compatibility(self.snapshot,record))
            self.compat_summary.setText(f"Build Tracker hedefi: {record.kb_number or '—'} • Windows {record.windows_version} • Build {record.build_number} • Kanal {record.channel or '—'}.")
        self._run(job,done,self.compat_latest)

    def refresh_installed(self): self._run(WindowsUpdateService.installed_updates,self._installed_loaded,self.installed_refresh)
    def _installed_loaded(self,items): self._installed_items=items; self._render_installed(items)

    def _render_installed(self,items):
        self.installed_table.setRowCount(0)
        for x in items:
            r=self.installed_table.rowCount(); self.installed_table.insertRow(r)
            vals=[x.kb,x.description,x.installed_on,x.source,"Evet" if x.removable else "Hayır","Yüklü",WindowsUpdateService.uninstall_command(x.kb)]
            for c,val in enumerate(vals): self.installed_table.setItem(r,c,QTableWidgetItem(str(val)))
        self.installed_info.setText(f"{len(items)} yüklü KB bulundu. Tarih, kaynak, kaldırılabilirlik ve kaldırma komutu gösteriliyor. 'Eksik KB' kontrolü 7. adımdaki Build Tracker karşılaştırmasıyla ayrıca yapılır.")

    def _filter_installed(self,text):
        q=text.lower()
        for r in range(self.installed_table.rowCount()): self.installed_table.setRowHidden(r,not any(q in (self.installed_table.item(r,c).text().lower() if self.installed_table.item(r,c) else "") for c in range(self.installed_table.columnCount())))

    def _show_failed_updates(self):
        self._run(WindowsUpdateService.failed_updates,lambda events:self._show_failed_result(events),self.failed_btn)
    def _show_failed_result(self,events):
        if not events: QMessageBox.information(self,"Başarısız güncellemeler","Son 30 günde WindowsUpdateClient kaydında Error/Warning olayı bulunamadı."); return
        dlg=QDialog(self); dlg.setWindowTitle("Başarısız Windows Update olayları"); dlg.resize(900,600); l=QVBoxLayout(dlg); t=QTextEdit(); t.setReadOnly(True); t.setPlainText("\n\n".join(events[:50])); l.addWidget(t); buttons=QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(dlg.reject); l.addWidget(buttons); dlg.exec()

    def _show_remove_command(self):
        row=self.installed_table.currentRow()
        if row<0:return
        kb=self.installed_table.item(row,0).text() if self.installed_table.item(row,0) else ""
        cmd=WindowsUpdateService.uninstall_command(kb)
        QMessageBox.information(self,"KB kaldırma komutu",cmd or "Seçili satır için geçerli KB bulunamadı.")

    def compare_with_tracker(self):
        def job(): return BuildTrackerService().fetch()[0]
        def done(records):
            installed={re.sub(r"\D","",x.kb).lstrip("0") for x in self._installed_items}
            missing=[]
            for rec in records[:100]:
                n=re.sub(r"\D","",rec.kb_number or "").lstrip("0")
                if n and n not in installed: missing.append(rec)
            self.installed_info.setText(f"Build Tracker: {len(records[:100])} kayıt incelendi • {len(missing)} KB bilgisayarda yüklü görünmüyor. Bunlar 'kesin eksik' değil; hedef Windows sürümü, build ve supersedence kontrolü gerekir.")
            for rec in missing[:30]:
                r=self.installed_table.rowCount(); self.installed_table.insertRow(r)
                vals=[rec.kb_number or "—",rec.description or "Build Tracker kaydı","—","Build Tracker","—","Eksik / doğrulama gerekli",WindowsUpdateService.uninstall_command(rec.kb_number)]
                for c,val in enumerate(vals): self.installed_table.setItem(r,c,QTableWidgetItem(str(val)))
        self._run(job,done,self.compare_tracker)

    def search_kb(self):
        kb=self.kb_input.text().strip().upper()
        if not kb:return
        self.selected_kb=kb if kb.startswith("KB") else "KB"+re.sub(r"\D","",kb)
        def job():
            updates=CatalogService().search(self.selected_kb); packages=PackageService().find_packages_for_kb(self.selected_kb)
            packages=WindowsUpdateService.package_filter(packages,self.snapshot or WindowsUpdateService.snapshot())
            return updates,packages
        self._run(job,self._kb_loaded,self.kb_search)

    def _kb_loaded(self,data):
        updates,packages=data; self._last_packages=packages
        try:
            tracker_matches=[x for x in BuildTrackerService.load_cache()[0] if (x.kb_number or "").upper()==self.selected_kb.upper()]
            if tracker_matches:
                for pkg in packages:
                    pkg.tracker_description=tracker_matches[0].description or ""
        except Exception:
            pass
        if updates:
            u=updates[0]
            self.kb_target_summary.setText(f"{self.selected_kb} • {u.title}\nÜrün: {u.product or '—'} • Sınıf: {u.classification or '—'} • Sürüm: {u.version or '—'} • Tarih: {u.last_updated or '—'} • Boyut: {u.size or '—'}\nKaynak: Microsoft Update Catalog • Paketler sistem mimarisi, dil, ürün ve Dynamic Update/Safe OS ayrımıyla puanlandı.")
        else:self.kb_target_summary.setText(f"{self.selected_kb}: Microsoft Update Catalog kaydı bulunamadı.")
        self.kb_article.setEnabled(bool(updates)); self.kb_download.setEnabled(bool(packages))
        self._render_packages()

    def _render_packages(self):
        packages=self._last_packages; self.kb_table.setRowCount(0)
        for p in packages:
            if self.kb_only_compatible.isChecked() and (p.recommendation_score < 0 or "Dynamic/Safe OS" in (p.recommendation_reason or "")):
                continue
            r=self.kb_table.rowCount(); self.kb_table.insertRow(r)
            vals=[p.filename,p.architecture,p.file_type,p.size,p.product or "—",p.classification or "—",("★ ÖNERİLEN • "+p.recommendation_reason) if p.recommended else f"Alternatif • Puan {p.recommendation_score}","Ayrıntı / İndir"]
            for c,val in enumerate(vals): self.kb_table.setItem(r,c,QTableWidgetItem(str(val)))
            self.kb_table.item(r,7).setData(Qt.UserRole,p.direct_url); self.kb_table.item(r,7).setData(Qt.UserRole+1,p)

    def _selected_package(self):
        row=self.kb_table.currentRow()
        if row<0:return None
        return self.kb_table.item(row,7).data(Qt.UserRole+1) if self.kb_table.item(row,7) else None
    def _package_details(self,row,col):
        p=self.kb_table.item(row,7).data(Qt.UserRole+1) if self.kb_table.item(row,7) else None
        if p: PackageDetailsDialog(p,self.snapshot,self).exec()
    def _download_selected_package(self):
        p=self._selected_package()
        if not p:return
        if not WindowsUpdateService.pre_download_check(p,self.snapshot or WindowsUpdateService.snapshot()):
            QMessageBox.warning(self,"İndirme engellendi","Paket sisteminiz için ön kontrolden geçmedi. Mimari/ürün/tür eşleşmesini kontrol edin."); return
        settings=SettingsService.load(); folder=str(settings.get("downloads",{}).get("default_folder","") or "").strip()
        initial=str(Path(folder)/p.filename) if folder and Path(folder).exists() else p.filename
        target,_=QFileDialog.getSaveFileName(self,"Microsoft paketini kaydet",initial,"Microsoft paketleri (*.msu *.cab *.exe);;Tüm dosyalar (*.*)")
        if not target:return
        DownloadManager.instance().add_download(p,target)
        self.install_path.setText(target); self.verify_path.setText(target)
        self.kb_target_summary.setText(self.kb_target_summary.text()+"\n\nİndirme başlatıldı. İndirme tamamlanınca 10. adım otomatik güvenlik doğrulaması yapacaktır.")

    def _open_catalog(self):
        if self.selected_kb: QDesktopServices.openUrl(QUrl("https://www.catalog.update.microsoft.com/Search.aspx?q="+self.selected_kb))

    def _pick_verify_file(self):
        p,_=QFileDialog.getOpenFileName(self,"Paket seç","","Microsoft paketleri (*.msu *.cab *.exe);;Tüm dosyalar (*.*)")
        if p:self.verify_path.setText(p)
    def verify_file(self):
        p=self.verify_path.text().strip()
        if p:self._run(lambda:WindowsUpdateService.verify_file(p,self.expected_sha.text().strip()),self._verify_loaded)
    def _verify_loaded(self,r):
        if r.get("exists"): self._verified_files[os.path.normcase(os.path.abspath(r["path"]))]=r
        self.verify_output.setPlainText(WindowsUpdateService.format_verification(r))
        if r.get("exists") and r.get("valid"): self.install_path.setText(r["path"])

    def _pick_install_file(self):
        p,_=QFileDialog.getOpenFileName(self,"Kurulum paketi seç","","Microsoft paketleri (*.msu *.cab *.exe);;Tüm dosyalar (*.*)")
        if p:self.install_path.setText(p)
    def _update_admin_state(self):
        admin=False
        if os.name=="nt":
            try: admin=bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception: pass
        self.admin_label.setText("Yönetici yetkisi: "+("VAR — kurulum etkin." if admin else "YOK — Kurulum için programı Yönetici olarak çalıştırın.")); self.install_btn.setEnabled(admin)

    def install_package(self):
        p=self.install_path.text().strip()
        if not p:return
        if not os.path.exists(p): QMessageBox.warning(self,"Dosya bulunamadı","Kurulum dosyası mevcut değil."); return
        if self.verify_before_install_cb.isChecked():
            self.install_output.append("[ÖN KONTROL] Paket tekrar doğrulanıyor…")
            r=WindowsUpdateService.verify_file(p); self._verified_files[os.path.normcase(os.path.abspath(p))]=r
            self.install_output.append(WindowsUpdateService.format_verification(r))
            if not r.get("valid"):
                QMessageBox.critical(self,"Kurulum engellendi","Paket güvenlik doğrulamasından geçmedi. SHA-256/dijital imza kontrolü başarısız veya belirsiz."); return
        if QMessageBox.question(self,"Kurulum onayı","Kurulum başlatılacak. Geri yükleme noktası oluşturulsun mu?" if self.restore_cb.isChecked() else "Kurulum başlatılsın mı?")!=QMessageBox.Yes:return
        if self.restore_cb.isChecked():
            ok,msg=WindowsUpdateService.create_restore_point(); self.install_output.append("[GERİ YÜKLEME] "+("BAŞARILI" if ok else "BAŞARISIZ")+"\n"+msg)
            if not ok and QMessageBox.question(self,"Geri yükleme noktası oluşturulamadı","Koruma noktası oluşturulamadı. Buna rağmen devam edilsin mi?")!=QMessageBox.Yes:return
        self._run(lambda:WindowsUpdateService.install_package(p,self.silent_cb.isChecked()),self._install_loaded,self.install_btn)
    def _install_loaded(self,data):
        ok,msg=data; self.install_output.append(("\nKURULUM BAŞARILI\n" if ok else "\nKURULUM BAŞARISIZ\n")+msg+"\n")
        if ok:self.refresh_installed()

    def troubleshoot(self): self.export_btn.setEnabled(False); self._run(WindowsUpdateService.troubleshoot,self._trouble_loaded)
    def _trouble_loaded(self,r):
        self._last_report=r; self.trouble_table.setRowCount(0)
        for name,val,desc in r.get("checks",[]):
            row=self.trouble_table.rowCount(); self.trouble_table.insertRow(row); self.trouble_table.setItem(row,0,QTableWidgetItem(name)); self.trouble_table.setItem(row,1,QTableWidgetItem(str(val))); self.trouble_table.setItem(row,2,QTableWidgetItem(desc))
        self.trouble_output.setPlainText("Rapor zamanı: "+r["generated_at"]+"\nHata kodları: "+(", ".join(r["error_codes"]) if r["error_codes"] else "Bulunamadı")+"\n\nSon Windows Update olayları:\n\n"+"\n\n".join(r["failed_events"])[:20000]); self.export_btn.setEnabled(True)
    def save_report(self):
        if not self._last_report:return
        p,_=QFileDialog.getSaveFileName(self,"Raporu kaydet","WindowsUpdate_Rapor.txt","Metin dosyası (*.txt)")
        if p:
            r=self._last_report; Path(p).write_text("Windows Update & Build Center\n"+r["generated_at"]+"\n\n"+"\n".join(f"{a}: {b} — {c}" for a,b,c in r["checks"])+"\n\nHata kodları: "+", ".join(r["error_codes"])+"\n\n"+"\n\n".join(r["failed_events"]),encoding="utf-8")

    def _apply_styles(self):
        self.setStyleSheet(styles.qss("""
        QLabel#panelTitle, QLabel#dialogTitle { font-weight:700; color:#13243B; font-size:15px; }
        QFrame#updatePanel { background:#FFFFFF; border:1px solid #DCE5F0; border-radius:10px; }
        QTabWidget::pane { border:1px solid #DCE5F0; background:#F7F9FC; border-radius:8px; }
        QTabBar::tab { background:#EEF3F9; color:#53657D; padding:9px 13px; margin-right:2px; border-radius:6px; }
        QTabBar::tab:selected { background:@BLUE@; color:white; }
        QLineEdit, QTextEdit, QTableWidget, QComboBox { background:#FFFFFF; border:1px solid #D7E1ED; border-radius:7px; padding:6px; }
        QTableWidget { padding:0; gridline-color:#EDF1F6; }
        QHeaderView::section { background:#F7F9FC; color:#53657D; border:none; border-bottom:1px solid #DCE5F0; padding:8px; font-weight:700; }
        QPushButton { background:#FFFFFF; color:#1C4F98; border:1px solid #CAD8EA; border-radius:7px; padding:8px 12px; font-weight:600; }
        QPushButton:hover { background:#F4F8FD; border-color:#8CB0E5; }
        QPushButton#dangerButton { background:#C83B3B; color:white; border:none; }
        QLabel#infoNote { background:#F2F7FF; color:#55708E; border:1px solid #D7E5F7; border-radius:8px; padding:9px; }
        QLabel#warningNote { background:#FFF7E8; color:#7B5A16; border:1px solid #F0D79D; border-radius:8px; padding:10px; }
        QCheckBox { color:#34465D; }
        """))

    def closeEvent(self,e):
        if self.worker and self.worker.isRunning(): self.worker.quit()
        super().closeEvent(e)
