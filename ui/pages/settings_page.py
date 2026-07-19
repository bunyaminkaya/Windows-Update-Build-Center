from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
    QStackedWidget, QCheckBox, QLineEdit, QFileDialog, QSpinBox,
    QSizePolicy,
)

from app.paths import DATA_DIR, LOG_DIR, SETTINGS_PATH
from services.download_manager import DownloadManager
from services.settings_service import SettingsService
from ui.widgets.message_dialog import show_information, show_warning, ask_confirmation
from ui.widgets.modern_combo_box import ModernComboBox


class SettingsPage(QWidget):
    settings_saved = Signal(object)

    CATEGORIES = [
        "Genel",
        "İndirme",
        "UUP / ISO",
        "Windows Build Tracker",
        "Gelişmiş",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = SettingsService.load()
        self._category_buttons: list[QPushButton] = []
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 24)
        root.setSpacing(16)

        subtitle = QLabel("Programın indirme, UUP / ISO ve Windows Build Tracker tercihlerini yönetin.")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(14)

        nav = QFrame()
        nav.setObjectName("settingsNav")
        nav.setFixedWidth(230)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(10, 10, 10, 10)
        nl.setSpacing(6)

        for index, name in enumerate(self.CATEGORIES):
            btn = QPushButton(name)
            btn.setObjectName("settingsNavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(42)
            btn.clicked.connect(lambda checked=False, i=index: self._show_category(i))
            nl.addWidget(btn)
            self._category_buttons.append(btn)
        nl.addStretch()
        body.addWidget(nav)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._general_page())
        self.stack.addWidget(self._downloads_page())
        self.stack.addWidget(self._uup_page())
        self.stack.addWidget(self._tracker_page())
        self.stack.addWidget(self._advanced_page())
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.save_button = QPushButton("Değişiklikleri Kaydet")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setMinimumHeight(42)
        self.save_button.clicked.connect(self.save_settings)
        footer.addWidget(self.save_button)
        root.addLayout(footer)

        self._show_category(0)
        self.setStyleSheet(self._styles())

    def _page_shell(self, title: str, description: str):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = QFrame()
        card.setObjectName("settingsCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(14)
        h = QLabel(title)
        h.setObjectName("settingsSectionTitle")
        d = QLabel(description)
        d.setObjectName("settingsSectionDescription")
        d.setWordWrap(True)
        cl.addWidget(h)
        cl.addWidget(d)
        layout.addWidget(card)
        return page, layout, card, cl

    def _row(self, title: str, description: str, widget):
        frame = QFrame()
        frame.setObjectName("settingRow")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(3)
        t = QLabel(title)
        t.setObjectName("settingTitle")
        d = QLabel(description)
        d.setObjectName("settingDescription")
        d.setWordWrap(True)
        text.addWidget(t)
        text.addWidget(d)
        lay.addLayout(text, 1)
        if widget is not None:
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            lay.addWidget(widget)
        return frame

    def _folder_editor(self):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        edit = QLineEdit()
        edit.setMinimumWidth(290)
        button = QPushButton("Seç")
        button.setObjectName("secondaryButton")
        button.clicked.connect(lambda: self._pick_folder(edit))
        lay.addWidget(edit)
        lay.addWidget(button)
        return box, edit

    def _general_page(self):
        page, layout, card, cl = self._page_shell(
            "Genel Ayarlar",
            "Programın açılış davranışını ve temel kullanım tercihlerini belirleyin.",
        )
        self.open_last_page = QCheckBox()
        cl.addWidget(self._row("Son kullanılan sayfayı aç", "Program yeniden başladığında en son kullandığınız bölümü açar.", self.open_last_page))
        self.check_tracker_on_start = QCheckBox()
        cl.addWidget(self._row("Açılışta güncellemeleri kontrol et", "Windows Build Tracker verilerini program açılırken kontrol eder.", self.check_tracker_on_start))
        self.run_in_background = QCheckBox()
        cl.addWidget(self._row("Arka planda çalışmaya devam et", "Etkinleştirildiğinde program kapatılsa bile sistem tepsisinde çalışmaya devam eder.", self.run_in_background))
        self.minimize_to_tray = QCheckBox()
        cl.addWidget(self._row("Kapatınca sistem tepsisine küçült", "Etkinleştirildiğinde pencereyi kapatmak programdan çıkmak yerine sistem tepsisine küçültür.", self.minimize_to_tray))
        self.start_with_windows = QCheckBox()
        cl.addWidget(self._row("Windows ile başlat", "Programın Windows başlangıcında açılması için tercih olarak kaydedilir.", self.start_with_windows))
        layout.addStretch()
        return page

    def _downloads_page(self):
        page, layout, card, cl = self._page_shell(
            "İndirme Ayarları",
            "İndirme klasörünü, eşzamanlı bağlantı sayısını ve indirme davranışlarını yönetin.",
        )
        folder_box, self.download_folder = self._folder_editor()
        cl.addWidget(self._row("Varsayılan indirme klasörü", "Yeni indirmelerde varsayılan olarak kullanılacak klasör.", folder_box))
        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(1, 8)
        self.max_concurrent.setSuffix(" indirme")
        self.max_concurrent.setMinimumWidth(150)
        cl.addWidget(self._row("Aynı anda indirilecek dosya sayısı", "İndirme Yöneticisi aynı anda en fazla bu kadar bağlantı çalıştırır.", self.max_concurrent))
        self.open_download_folder = QCheckBox()
        cl.addWidget(self._row("İndirme tamamlanınca klasörü aç", "Tamamlanan indirme klasörünün otomatik açılması için tercih.", self.open_download_folder))
        self.resume_incomplete = QCheckBox()
        cl.addWidget(self._row("Yarım kalan indirmeleri otomatik devam ettir", "Program yeniden açıldığında yarım kalan indirmeleri kuyruğa alır.", self.resume_incomplete))
        self.duplicate_policy = ModernComboBox()
        self.duplicate_policy.addItems(["Dosya Çakışması: Benzersiz ad oluştur", "Dosya Çakışması: Üzerine yazma"])
        self.duplicate_policy.setMinimumWidth(300)
        cl.addWidget(self._row("Dosya çakışması", "Aynı isimli bir dosya bulunduğunda uygulanacak davranış.", self.duplicate_policy))
        layout.addStretch()
        return page

    def _uup_page(self):
        page, layout, card, cl = self._page_shell(
            "UUP / ISO Ayarları",
            "UUP indirme ve ISO oluşturma işlemlerinde kullanılacak varsayılanları belirleyin.",
        )
        self.default_arch = ModernComboBox()
        self.default_arch.addItems(["Mimari: Sistem varsayılanı", "Mimari: x64", "Mimari: ARM64", "Mimari: x86"])
        self.default_arch.setMinimumWidth(260)
        cl.addWidget(self._row("Varsayılan mimari", "UUP Merkezi ilk açıldığında seçilecek mimari.", self.default_arch))
        self.default_language = ModernComboBox()
        self.default_language.addItems(["Dil: Sistem varsayılanı", "Dil: Türkçe", "Dil: English (United States)", "Dil: Deutsch", "Dil: Français"])
        self.default_language.setMinimumWidth(300)
        cl.addWidget(self._row("Varsayılan dil", "UUP Merkezi ilk açıldığında seçilecek dil.", self.default_language))
        self.default_edition = ModernComboBox()
        self.default_edition.addItems(["Edition: Windows 11 Pro", "Edition: Windows 11"])
        self.default_edition.setMinimumWidth(260)
        cl.addWidget(self._row("Varsayılan edition", "ISO oluşturma işleminde varsayılan Windows edition seçimi.", self.default_edition))
        work_box, self.iso_work_folder = self._folder_editor()
        cl.addWidget(self._row("ISO çalışma klasörü", "Dönüştürme sırasında geçici çalışma dosyalarının tutulacağı klasör.", work_box))
        output_box, self.iso_output_folder = self._folder_editor()
        cl.addWidget(self._row("ISO çıktı klasörü", "Tamamlanan ISO dosyalarının varsayılan olarak kaydedileceği klasör.", output_box))
        self.open_iso_folder = QCheckBox()
        cl.addWidget(self._row("ISO tamamlandığında klasörü aç", "ISO başarıyla oluşturulduğunda çıktı klasörünü açar.", self.open_iso_folder))
        self.clean_temp_files = QCheckBox()
        cl.addWidget(self._row("Geçici dosyaları otomatik temizle", "ISO işlemi tamamlandıktan sonra geçici çalışma dosyalarını temizlemek için tercih.", self.clean_temp_files))
        layout.addStretch()
        return page

    def _tracker_page(self):
        page, layout, card, cl = self._page_shell(
            "Windows Build Tracker",
            "Build Tracker veri kaynağı ve otomatik yenileme davranışını yönetin.",
        )
        self.tracker_source = QLineEdit()
        self.tracker_source.setReadOnly(True)
        self.tracker_source.setMinimumWidth(420)
        cl.addWidget(self._row("Veri kaynağı", "Programın build verilerini aldığı sabit kaynak adresi.", self.tracker_source))
        self.tracker_refresh_start = QCheckBox()
        cl.addWidget(self._row("Program açılışında güncelle", "Program başlatıldığında Build Tracker verilerini otomatik kontrol eder.", self.tracker_refresh_start))
        self.tracker_interval = ModernComboBox()
        self.tracker_interval.addItems(["Güncelleme Sıklığı: 30 dakika", "Güncelleme Sıklığı: 1 saat", "Güncelleme Sıklığı: 2 saat", "Güncelleme Sıklığı: 6 saat"])
        self.tracker_interval.setMinimumWidth(280)
        cl.addWidget(self._row("Otomatik güncelleme sıklığı", "Program açıkken Build Tracker verilerinin ne sıklıkta kontrol edileceği.", self.tracker_interval))
        button_row = QHBoxLayout()
        clear_cache = QPushButton("Build Tracker Önbelleğini Temizle")
        clear_cache.setObjectName("secondaryButton")
        clear_cache.clicked.connect(self._clear_tracker_cache)
        button_row.addWidget(clear_cache)
        button_row.addStretch()
        cl.addLayout(button_row)
        layout.addStretch()
        return page

    def _advanced_page(self):
        page, layout, card, cl = self._page_shell(
            "Gelişmiş Ayarlar",
            "Program verilerini, günlükleri ve önbelleği yönetin.",
        )
        buttons = [
            ("Log klasörünü aç", "Program günlük dosyalarının bulunduğu klasörü açar.", self._open_logs),
            ("Veri klasörünü aç", "Ayarlar, önbellek ve yerel veri dosyalarının bulunduğu klasörü açar.", self._open_data),
            ("İndirme geçmişini temizle", "Tamamlanan indirme kayıtlarını İndirme Yöneticisi üzerinden temizler.", self._clear_download_history),
            ("Ayarları sıfırla", "Tüm ayarları varsayılan değerlere geri döndürür.", self._reset_settings),
        ]
        for title, desc, handler in buttons:
            btn = QPushButton(title)
            btn.setObjectName("secondaryButton")
            btn.clicked.connect(handler)
            cl.addWidget(self._row(title, desc, btn))
        layout.addStretch()
        return page

    def _show_category(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._category_buttons):
            btn.setChecked(i == index)

    def _pick_folder(self, edit: QLineEdit):
        current = edit.text().strip()
        start = current if current and Path(current).exists() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Klasör Seç", start)
        if folder:
            edit.setText(folder)

    @staticmethod
    def _strip_prefix(text: str) -> str:
        return text.split(": ", 1)[1] if ": " in text else text

    def _load_values(self):
        s = self._settings
        g = s["general"]
        d = s["downloads"]
        u = s["uup_iso"]
        b = s["build_tracker"]

        self.open_last_page.setChecked(bool(g["open_last_page"]))
        self.check_tracker_on_start.setChecked(bool(g["check_tracker_on_start"]))
        self.run_in_background.setChecked(bool(g["run_in_background"]))
        self.minimize_to_tray.setChecked(bool(g["minimize_to_tray"]))
        self.start_with_windows.setChecked(bool(g["start_with_windows"]))

        self.download_folder.setText(str(d["default_folder"]))
        self.max_concurrent.setValue(int(d["max_concurrent"]))
        self.open_download_folder.setChecked(bool(d["open_folder_on_complete"]))
        self.resume_incomplete.setChecked(bool(d["resume_incomplete"]))
        self._set_combo(self.duplicate_policy, f"Dosya Çakışması: {d['duplicate_policy']}")

        self._set_combo(self.default_arch, f"Mimari: {u['default_architecture']}")
        self._set_combo(self.default_language, f"Dil: {u['default_language']}")
        self._set_combo(self.default_edition, f"Edition: {u['default_edition']}")
        self.iso_work_folder.setText(str(u["work_folder"]))
        self.iso_output_folder.setText(str(u["output_folder"]))
        self.open_iso_folder.setChecked(bool(u["open_iso_folder_on_complete"]))
        self.clean_temp_files.setChecked(bool(u["clean_temp_files"]))

        self.tracker_source.setText(str(b["source_url"]))
        self.tracker_refresh_start.setChecked(bool(b["refresh_on_start"]))
        minutes = int(b["refresh_interval_minutes"])
        label = {30: "30 dakika", 60: "1 saat", 120: "2 saat", 360: "6 saat"}.get(minutes, "1 saat")
        self._set_combo(self.tracker_interval, f"Güncelleme Sıklığı: {label}")

    def _set_combo(self, combo: ModernComboBox, text: str):
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def save_settings(self):
        interval_text = self._strip_prefix(self.tracker_interval.currentText())
        interval_map = {"30 dakika": 30, "1 saat": 60, "2 saat": 120, "6 saat": 360}
        self._settings = {
            "general": {
                **self._settings.get("general", {}),
                "open_last_page": self.open_last_page.isChecked(),
                "check_tracker_on_start": self.check_tracker_on_start.isChecked(),
                "run_in_background": self.run_in_background.isChecked(),
                "minimize_to_tray": self.minimize_to_tray.isChecked(),
                "start_with_windows": self.start_with_windows.isChecked(),
            },
            "downloads": {
                "default_folder": self.download_folder.text().strip(),
                "max_concurrent": self.max_concurrent.value(),
                "open_folder_on_complete": self.open_download_folder.isChecked(),
                "resume_incomplete": self.resume_incomplete.isChecked(),
                "duplicate_policy": self._strip_prefix(self.duplicate_policy.currentText()),
            },
            "uup_iso": {
                "default_architecture": self._strip_prefix(self.default_arch.currentText()),
                "default_language": self._strip_prefix(self.default_language.currentText()),
                "default_edition": self._strip_prefix(self.default_edition.currentText()),
                "work_folder": self.iso_work_folder.text().strip(),
                "output_folder": self.iso_output_folder.text().strip(),
                "open_iso_folder_on_complete": self.open_iso_folder.isChecked(),
                "clean_temp_files": self.clean_temp_files.isChecked(),
            },
            "build_tracker": {
                "source_url": "https://bunyaminkaya.com/windows-build-tracker/",
                "refresh_on_start": self.tracker_refresh_start.isChecked(),
                "refresh_interval_minutes": interval_map.get(interval_text, 60),
            },
            "advanced": self._settings.get("advanced", {}),
        }
        self._apply_startup_preference(self.start_with_windows.isChecked())
        SettingsService.save(self._settings)
        DownloadManager.instance().set_max_concurrent(self.max_concurrent.value())
        self.settings_saved.emit(self._settings)
        show_information(self, "Ayarlar", "Ayarlar başarıyla kaydedildi ve uygulanabilir değişiklikler hemen etkinleştirildi.")

    def _apply_startup_preference(self, enabled: bool) -> None:
        if os.name != "nt":
            return
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    if getattr(sys, "frozen", False):
                        command = f'"{sys.executable}"'
                    else:
                        main_py = Path(__file__).resolve().parents[2] / "main.py"
                        command = f'"{sys.executable}" "{main_py}"'
                    winreg.SetValueEx(key, "WindowsUpdateBuildCenter", 0, winreg.REG_SZ, command)
                    try:
                        winreg.DeleteValue(key, "MicrosoftDirektLinkBulucu")
                    except FileNotFoundError:
                        pass
                else:
                    for value_name in ("WindowsUpdateBuildCenter", "MicrosoftDirektLinkBulucu"):
                        try:
                            winreg.DeleteValue(key, value_name)
                        except FileNotFoundError:
                            pass
        except Exception as exc:
            show_warning(self, "Windows başlangıcı", f"Windows başlangıç ayarı uygulanamadı: {exc}")

    def _open_path(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            try:
                subprocess.Popen(["explorer.exe", str(path)])
            except Exception as exc:
                show_warning(self, "Klasör açılamadı", str(exc))

    def _open_logs(self):
        self._open_path(LOG_DIR)

    def _open_data(self):
        self._open_path(DATA_DIR)

    def _clear_tracker_cache(self):
        candidates = [
            DATA_DIR / "build_tracker_cache.json",
            DATA_DIR / "windows_build_tracker_cache.json",
        ]
        removed = 0
        for path in candidates:
            if path.exists():
                try:
                    path.unlink()
                    removed += 1
                except Exception:
                    pass
        show_information(self, "Önbellek", f"Build Tracker önbelleği temizlendi. Silinen dosya: {removed}")

    def _clear_download_history(self):
        manager = DownloadManager.instance()
        completed = [job.id for job in manager.all_jobs() if getattr(job, "status", "") == "Tamamlandı"]
        if not completed:
            show_information(self, "İndirme geçmişi", "Temizlenecek tamamlanmış indirme kaydı bulunmuyor.")
            return
        if not ask_confirmation(self, "İndirme geçmişi", f"{len(completed)} tamamlanmış indirme kaydı listeden kaldırılsın mı?"):
            return
        result = manager.remove_jobs(completed, delete_files=False)
        removed = len(result.get("removed", []))
        show_information(self, "İndirme geçmişi", f"{removed} kayıt temizlendi.")

    def _reset_settings(self):
        if not ask_confirmation(self, "Ayarları Sıfırla", "Tüm ayarlar varsayılan değerlere döndürülsün mü?"):
            return
        self._settings = SettingsService.reset()
        self._load_values()
        self.settings_saved.emit(self._settings)
        show_information(self, "Ayarlar", "Tüm ayarlar varsayılan değerlere döndürüldü.")

    @staticmethod
    def _styles() -> str:
        return """
            QFrame#settingsNav, QFrame#settingsCard {
                background: #FFFFFF;
                border: 1px solid #DCE5F0;
                border-radius: 12px;
            }
            QPushButton#settingsNavButton {
                text-align: left;
                padding: 9px 12px;
                border: none;
                border-radius: 8px;
                color: #34445C;
                background: transparent;
                font-weight: 600;
            }
            QPushButton#settingsNavButton:hover { background: #EEF4FD; }
            QPushButton#settingsNavButton:checked { background: #2167D5; color: white; }
            QLabel#settingsSectionTitle { color: #0B1736; font-size: 18px; font-weight: 700; }
            QLabel#settingsSectionDescription { color: #6F7E94; font-size: 13px; }
            QFrame#settingRow {
                background: #F8FAFD;
                border: 1px solid #E1E8F2;
                border-radius: 9px;
            }
            QLabel#settingTitle { color: #14213D; font-weight: 600; }
            QLabel#settingDescription { color: #7A889D; font-size: 12px; }
            QPushButton#secondaryButton {
                background: #FFFFFF;
                color: #1D57A8;
                border: 1px solid #C8D7EA;
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: 600;
            }
            QPushButton#secondaryButton:hover { background: #F0F6FF; border-color: #8FB3E8; }
            QSpinBox {
                background: white;
                border: 1px solid #C9D5E4;
                border-radius: 8px;
                padding: 8px 10px;
                min-height: 26px;
            }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 19px; height: 19px; }
        """
