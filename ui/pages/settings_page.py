from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize, QRectF, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel, QPushButton,
    QStackedWidget, QCheckBox, QLineEdit, QFileDialog, QSpinBox,
    QSizePolicy, QScrollArea,
)

from app.paths import DATA_DIR, LOG_DIR, SETTINGS_PATH
from services.download_manager import DownloadManager
from services.settings_service import SettingsService
from ui import icons
from ui.theme import raw_qcolor
from ui.widgets.message_dialog import show_information, show_warning, ask_confirmation
from ui.widgets.modern_combo_box import ModernComboBox


class WatchChoiceButton(QPushButton):
    """Takip seçeneklerini görünür, açıklayıcı seçim kartları olarak gösterir."""

    def __init__(self, text: str, group: str, parent=None):
        super().__init__(parent)
        self.choice_text = text
        self.setObjectName("watchChoice")
        self.setProperty("choiceGroup", group)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setToolTip(f"{text} seçeneğini takip listesine eklemek veya çıkarmak için tıklayın.")
        self.toggled.connect(self._sync_text)
        self._sync_text(False)

    def _sync_text(self, checked: bool) -> None:
        self.setText(("✓  " if checked else "+  ") + self.choice_text)


class ToggleSwitch(QCheckBox):
    """Aç/kapat anahtarı. QCheckBox davranışını (isChecked/setChecked/toggled) aynen korur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(54, 30)
        self._pos = 1.0 if self.isChecked() else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(130)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)

    def _on_anim(self, value) -> None:
        self._pos = float(value)
        self.update()

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        RC = raw_qcolor()
        off, on = QColor("#CED7E4"), RC("#1768E0")
        t = self._pos
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 1, self.width(), self.height() - 2), 14, 14)
        knob = 24
        x = 3 + t * (self.width() - knob - 6)
        painter.setBrush(QColor(0, 0, 0, 30))
        painter.drawEllipse(QRectF(x, 3.5, knob, knob))
        painter.setBrush(RC("#FFFFFF"))
        painter.drawEllipse(QRectF(x, 3, knob, knob))


class SettingsPage(QWidget):
    settings_saved = Signal(object)

    BLUE = "#1768E0"
    NAV_ICONS = ["gear", "download-tray", "cloud-outline", "boxes", "sliders"]
    PAGE_ICONS = {
        "Genel Ayarlar": "gear",
        "İndirme Ayarları": "download-tray",
        "UUP / ISO Ayarları": "cloud-outline",
        "Windows Sürüm Takibi": "boxes",
        "Gelişmiş Ayarlar": "sliders",
    }
    ROW_ICONS = {
        "Son kullanılan sayfayı aç": "clock",
        "Açılışta güncellemeleri kontrol et": "refresh",
        "Arka planda çalışmaya devam et": "monitor",
        "Kapatınca sistem tepsisine küçült": "tray",
        "Açılışta karşılama rehberini göster": "info-outline",
        "Windows ile başlat": "windows-white",
        "Varsayılan indirme klasörü": "folder",
        "Aynı anda indirilecek dosya sayısı": "download-tray",
        "İndirme tamamlanınca klasörü aç": "folder",
        "Yarım kalan indirmeleri otomatik devam ettir": "refresh",
        "Dosya çakışması": "copy",
        "Varsayılan mimari": "cpu",
        "Varsayılan dil": "globe",
        "Varsayılan edition": "windows-outline",
        "ISO çalışma klasörü": "folder",
        "ISO çıktı klasörü": "folder",
        "ISO tamamlandığında klasörü aç": "folder",
        "Geçici dosyaları otomatik temizle": "trash",
        "Veri kaynağı": "globe",
        "Program açılışında güncelle": "refresh",
        "Otomatik güncelleme sıklığı": "clock",
        "Yeni build bildirimi": "bell",
        "Yalnızca takip listesinden bildirim al": "list",
        "Takip edilen Windows sürümleri": "windows-outline",
        "Takip edilen kanallar": "boxes",
        "Belirli KB veya build ailesi": "search",
        "Karşılama rehberi": "info-outline",
        "İndirme hız sınırı": "download-tray",
        "Gece indirme zamanlaması": "clock",
        "Zamanlama başlangıcı": "clock",
        "Zamanlama bitişi": "clock",
        "Tema": "monitor",
        "Build bildirimi denemesi": "bell",
        "Güncelleme denetimi": "refresh",
        "Log klasörünü aç": "doc",
        "Veri klasörünü aç": "folder",
        "İndirme geçmişini temizle": "trash",
        "Ayarları sıfırla": "undo",
    }

    CATEGORIES = [
        "Genel",
        "İndirme",
        "UUP / ISO",
        "Windows Sürüm Takibi",
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
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        head = QHBoxLayout()
        head.setSpacing(16)
        header_tile = QLabel()
        header_tile.setObjectName("stHeaderTile")
        header_tile.setFixedSize(64, 64)
        header_tile.setAlignment(Qt.AlignCenter)
        header_tile.setPixmap(icons.pixmap("gear", self.BLUE, 34, bg="#FFFFFF"))
        head.addWidget(header_tile, 0, Qt.AlignTop)
        head_text = QVBoxLayout()
        head_text.setSpacing(2)
        title = QLabel("Ayarlar")
        title.setObjectName("stTitle")
        subtitle = QLabel("Programın açılış, indirme ve güncelleme davranışını kendinize göre düzenleyin.")
        subtitle.setObjectName("stSubtitle")
        subtitle.setWordWrap(True)
        head_text.addWidget(title)
        head_text.addWidget(subtitle)
        head.addLayout(head_text, 1)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(18)

        nav = QFrame()
        nav.setObjectName("settingsNav")
        nav.setFixedWidth(232)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(12, 12, 12, 12)
        nl.setSpacing(6)

        for index, name in enumerate(self.CATEGORIES):
            btn = QPushButton(name)
            btn.setObjectName("settingsNavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIconSize(QSize(36, 22))
            btn.clicked.connect(lambda checked=False, i=index: self._show_category(i))
            nl.addWidget(btn)
            self._category_buttons.append(btn)
        nl.addStretch()
        body.addWidget(nav)

        content = QFrame()
        content.setObjectName("settingsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._scrollable(self._general_page()))
        self.stack.addWidget(self._scrollable(self._downloads_page()))
        self.stack.addWidget(self._scrollable(self._uup_page()))
        self.stack.addWidget(self._scrollable(self._tracker_page()))
        self.stack.addWidget(self._scrollable(self._advanced_page()))
        content_layout.addWidget(self.stack, 1)

        footer = QFrame()
        footer.setObjectName("settingsFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 16, 24, 16)
        footer_layout.setSpacing(12)
        footer_layout.addStretch()
        self.reset_button = QPushButton("Varsayılanlara Dön")
        self.reset_button.setObjectName("stGhostButton")
        self.reset_button.setIcon(icons.icon("undo", self.BLUE, 18, stroke=2.0))
        self.reset_button.setIconSize(QSize(18, 18))
        self.reset_button.setCursor(Qt.PointingHandCursor)
        self.reset_button.clicked.connect(self._reset_settings)
        footer_layout.addWidget(self.reset_button)
        self.save_button = QPushButton("Değişiklikleri Kaydet")
        self.save_button.setObjectName("stPrimaryButton")
        self.save_button.setIcon(icons.icon("save", "#FFFFFF", 18, stroke=2.0))
        self.save_button.setIconSize(QSize(18, 18))
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.clicked.connect(self.save_settings)
        footer_layout.addWidget(self.save_button)
        content_layout.addWidget(footer)

        body.addWidget(content, 1)
        root.addLayout(body, 1)

        self._show_category(0)
        self.setStyleSheet(self._styles_with_arrows())

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setObjectName("settingsScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    def _page_shell(self, title: str, description: str):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = QFrame()
        card.setObjectName("settingsCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 26, 28, 22)
        cl.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(16)
        tile = QLabel()
        tile.setObjectName("stPageTile")
        tile.setFixedSize(60, 60)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap(self.PAGE_ICONS.get(title, "gear"), self.BLUE, 32, bg="#EAF2FE"))
        header.addWidget(tile, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        h = QLabel(title)
        h.setObjectName("settingsSectionTitle")
        d = QLabel(description)
        d.setObjectName("settingsSectionDescription")
        d.setWordWrap(True)
        text.addWidget(h)
        text.addWidget(d)
        header.addLayout(text, 1)
        cl.addLayout(header)
        cl.addSpacing(4)
        layout.addWidget(card)
        return page, layout, card, cl

    def _row(self, title: str, description: str, widget):
        frame = QFrame()
        frame.setObjectName("settingRow")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(18, 16, 22, 16)
        lay.setSpacing(18)
        tile = QLabel()
        tile.setObjectName("settingIcon")
        tile.setFixedSize(54, 54)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap(self.ROW_ICONS.get(title, "gear-outline"), self.BLUE, 28, bg="#EAF2FE", stroke=1.8))
        lay.addWidget(tile, 0, Qt.AlignVCenter)
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
            lay.addWidget(widget, 0, Qt.AlignVCenter)
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
            "Uygulamanın temel davranışlarını ve tercihlerinizi bu bölümden yönetebilirsiniz.",
        )
        self.open_last_page = ToggleSwitch()
        cl.addWidget(self._row("Son kullanılan sayfayı aç", "Program yeniden başlatıldığında en son kullandığınız bölümü açar.", self.open_last_page))
        self.check_tracker_on_start = ToggleSwitch()
        cl.addWidget(self._row("Açılışta güncellemeleri kontrol et", "Windows Sürüm Takibi verilerini program açılırken kontrol eder.", self.check_tracker_on_start))
        self.run_in_background = ToggleSwitch()
        cl.addWidget(self._row("Arka planda çalışmaya devam et", "Etkinleştirildiğinde program kapalı olsa bile sistem tepsisinde çalışmaya devam eder.", self.run_in_background))
        self.minimize_to_tray = ToggleSwitch()
        cl.addWidget(self._row("Kapatınca sistem tepsisine küçült", "Etkinleştirildiğinde pencereyi kapatmak programdan çıkmak yerine sistem tepsisine küçültür.", self.minimize_to_tray))
        self.start_with_windows = ToggleSwitch()
        cl.addWidget(self._row("Windows ile başlat", "Programın Windows başlangıcında açılması için tercih olarak kaydedilir.", self.start_with_windows))
        guide_button = QPushButton("Yeniden Göster")
        guide_button.setObjectName("secondaryButton")
        guide_button.setCursor(Qt.PointingHandCursor)
        guide_button.clicked.connect(self._show_welcome_guide)
        cl.addWidget(self._row("Karşılama rehberi", "Ara → İndir → USB'ye yaz tanıtımını yeniden açar.", guide_button))
        self.show_welcome_on_start = ToggleSwitch()
        cl.addWidget(self._row("Açılışta karşılama rehberini göster", "Etkinleştirildiğinde rehber her program açılışında gösterilir.", self.show_welcome_on_start))
        self.check_app_updates = ToggleSwitch()
        cl.addWidget(self._row("Güncelleme denetimi", "Program açılırken yeni bir sürüm olup olmadığına bakar; varsa yan menüde haber verir.", self.check_app_updates))
        test_button = QPushButton("Bildirimi Dene")
        test_button.setObjectName("secondaryButton")
        test_button.setCursor(Qt.PointingHandCursor)
        test_button.clicked.connect(lambda: self.window().send_test_notification() if hasattr(self.window(), "send_test_notification") else None)
        cl.addWidget(self._row("Build bildirimi denemesi", "Yeni build bildirimlerinin Windows'ta nasıl görüneceğini bir örnekle gösterir.", test_button))
        self.theme_combo = ModernComboBox()
        self.theme_combo.addItems(["Açık", "Koyu", "Sistem"])
        self.theme_combo.setMinimumWidth(200)
        cl.addWidget(self._row("Tema", "Açık, koyu ya da Windows ayarını izleyen görünüm. Değişiklik program yeniden başlatılınca uygulanır.", self.theme_combo))
        self.language_combo = ModernComboBox()
        self.language_combo.addItems(["Otomatik (Windows dili)", "Türkçe", "English"])
        self.language_combo.setMinimumWidth(200)
        cl.addWidget(self._row("Dil", "Arayüz dili (Türkçe / English). Değişiklik program yeniden başlatılınca uygulanır.", self.language_combo))
        layout.addStretch()
        return page

    def _show_welcome_guide(self):
        window = self.window()
        if hasattr(window, "show_welcome_guide_if_needed"):
            window.show_welcome_guide_if_needed(force=True)

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
        self.max_concurrent.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.max_concurrent.lineEdit().setTextMargins(10, 0, 0, 0)
        cl.addWidget(self._row("Aynı anda indirilecek dosya sayısı", "İndirme Yöneticisi aynı anda en fazla bu kadar bağlantı çalıştırır.", self.max_concurrent))
        self.speed_limit = ModernComboBox()
        self.SPEED_LIMITS = [("Sınırsız", 0), ("512 KB/sn", 512), ("1 MB/sn", 1024), ("2 MB/sn", 2048), ("5 MB/sn", 5120), ("10 MB/sn", 10240)]
        self.speed_limit.addItems([label for label, _ in self.SPEED_LIMITS])
        self.speed_limit.setMinimumWidth(200)
        cl.addWidget(self._row("İndirme hız sınırı", "Tüm indirmelerin toplam hızını sınırlar; internetin başka işlere de yetmesini sağlar.", self.speed_limit))
        self.schedule_enabled = ToggleSwitch()
        cl.addWidget(self._row("Gece indirme zamanlaması", "Açıkken yeni indirmeler yalnızca aşağıdaki saat aralığında başlar; diğer saatlerde kuyrukta bekler.", self.schedule_enabled))
        hours = [f"{h:02d}:00" for h in range(24)]
        self.schedule_start = ModernComboBox()
        self.schedule_start.addItems(hours)
        self.schedule_start.setMinimumWidth(140)
        cl.addWidget(self._row("Zamanlama başlangıcı", "İndirmelerin başlamasına izin verilen ilk saat.", self.schedule_start))
        self.schedule_end = ModernComboBox()
        self.schedule_end.addItems(hours)
        self.schedule_end.setMinimumWidth(140)
        cl.addWidget(self._row("Zamanlama bitişi", "Bu saatten sonra yeni indirme başlatılmaz; çalışan indirmeler tamamlanır.", self.schedule_end))
        self.open_download_folder = ToggleSwitch()
        cl.addWidget(self._row("İndirme tamamlanınca klasörü aç", "Tamamlanan indirme klasörünün otomatik açılması için tercih.", self.open_download_folder))
        self.resume_incomplete = ToggleSwitch()
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
        cl.addWidget(self._row("Varsayılan mimari", "UUP ISO Oluşturucu ilk açıldığında seçilecek mimari.", self.default_arch))
        self.default_language = ModernComboBox()
        self.default_language.addItems(["Dil: Sistem varsayılanı", "Dil: Türkçe", "Dil: English (United States)", "Dil: Deutsch", "Dil: Français"])
        self.default_language.setMinimumWidth(300)
        cl.addWidget(self._row("Varsayılan dil", "UUP ISO Oluşturucu ilk açıldığında seçilecek dil.", self.default_language))
        self.default_edition = ModernComboBox()
        self.default_edition.addItems(["Edition: Windows 11 Pro", "Edition: Windows 11"])
        self.default_edition.setMinimumWidth(260)
        cl.addWidget(self._row("Varsayılan edition", "ISO oluşturma işleminde varsayılan Windows edition seçimi.", self.default_edition))
        work_box, self.iso_work_folder = self._folder_editor()
        cl.addWidget(self._row("ISO çalışma klasörü", "Dönüştürme sırasında geçici çalışma dosyalarının tutulacağı klasör.", work_box))
        output_box, self.iso_output_folder = self._folder_editor()
        cl.addWidget(self._row("ISO çıktı klasörü", "Tamamlanan ISO dosyalarının varsayılan olarak kaydedileceği klasör.", output_box))
        self.auto_create_iso = ToggleSwitch()
        cl.addWidget(self._row(
            "İndirme bitince ISO'yu otomatik oluştur",
            "Açıkken UUP dosyaları inince ISO kendiliğinden hazırlanır (yönetici izni istenir). Kapalıyken İndirme Yöneticisi'ndeki ISO Oluşturma bölümünden düğmeyle başlatırsınız.",
            self.auto_create_iso,
        ))
        self.open_iso_folder = ToggleSwitch()
        cl.addWidget(self._row("ISO tamamlandığında klasörü aç", "ISO başarıyla oluşturulduğunda çıktı klasörünü açar.", self.open_iso_folder))
        self.clean_temp_files = ToggleSwitch()
        cl.addWidget(self._row("Geçici dosyaları otomatik temizle", "ISO işlemi tamamlandıktan sonra geçici çalışma dosyalarını temizlemek için tercih.", self.clean_temp_files))
        layout.addStretch()
        return page

    def _tracker_page(self):
        page, layout, card, cl = self._page_shell(
            "Windows Sürüm Takibi",
            "Build Tracker veri kaynağı ve otomatik yenileme davranışını yönetin.",
        )
        self.tracker_source = QLineEdit()
        self.tracker_source.setReadOnly(True)
        self.tracker_source.setMinimumWidth(420)
        cl.addWidget(self._row("Veri kaynağı", "Programın build verilerini aldığı sabit kaynak adresi.", self.tracker_source))
        self.tracker_refresh_start = ToggleSwitch()
        cl.addWidget(self._row("Program açılışında güncelle", "Program başlatıldığında Build Tracker verilerini otomatik kontrol eder.", self.tracker_refresh_start))
        self.tracker_interval = ModernComboBox()
        self.tracker_interval.addItems(["Güncelleme Sıklığı: 30 dakika", "Güncelleme Sıklığı: 1 saat", "Güncelleme Sıklığı: 2 saat", "Güncelleme Sıklığı: 6 saat"])
        self.tracker_interval.setMinimumWidth(280)
        cl.addWidget(self._row("Otomatik güncelleme sıklığı", "Program açıkken Build Tracker verilerinin ne sıklıkta kontrol edileceği.", self.tracker_interval))

        self.tracker_notifications = ToggleSwitch()
        cl.addWidget(self._row(
            "Yeni build bildirimi",
            "Takip edilen kanallarda yeni kayıt bulunduğunda Windows masaüstü bildirimi gösterir.",
            self.tracker_notifications,
        ))

        self.watchlist_enabled = ToggleSwitch()
        cl.addWidget(self._row(
            "Yalnızca takip listesinden bildirim al",
            "Etkinleştirildiğinde yeni kayıt seçilen sürüm, kanal, KB veya build ölçütlerinden en az biriyle eşleşmelidir.",
            self.watchlist_enabled,
        ))

        version_box = QWidget()
        version_outer = QVBoxLayout(version_box)
        version_outer.setContentsMargins(0, 0, 0, 0)
        version_outer.setSpacing(7)
        version_layout = QGridLayout()
        version_layout.setContentsMargins(0, 0, 0, 0)
        version_layout.setSpacing(7)
        self.tracked_version_checks: dict[str, WatchChoiceButton] = {}
        for index, version in enumerate(("26H1", "26H2", "25H2", "24H2", "Future Platforms")):
            check = WatchChoiceButton(version, "version")
            self.tracked_version_checks[version] = check
            version_layout.addWidget(check, index // 3, index % 3)
        version_outer.addLayout(version_layout)
        version_actions = QHBoxLayout()
        version_actions.setContentsMargins(0, 0, 0, 0)
        version_actions.addWidget(self._selection_action("Tüm sürümleri seç", self.tracked_version_checks, True))
        version_actions.addWidget(self._selection_action("Sürüm seçimini temizle", self.tracked_version_checks, False))
        version_actions.addStretch()
        version_outer.addLayout(version_actions)
        cl.addWidget(self._row(
            "Takip edilen Windows sürümleri",
            "Takip etmek istediğiniz sürüm kartlarına tıklayın; ✓ işaretli kartlar bildirim listesine eklenir.",
            version_box,
        ))

        channel_box = QWidget()
        channel_outer = QVBoxLayout(channel_box)
        channel_outer.setContentsMargins(0, 0, 0, 0)
        channel_outer.setSpacing(7)
        channel_layout = QGridLayout()
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.setSpacing(7)
        self.notification_channel_checks: dict[str, WatchChoiceButton] = {}
        for index, channel in enumerate(("GA / Retail", "Release Preview", "Beta", "Experimental", "Dev", "Canary")):
            check = WatchChoiceButton(channel, "channel")
            self.notification_channel_checks[channel] = check
            channel_layout.addWidget(check, index // 3, index % 3)
        channel_outer.addLayout(channel_layout)
        channel_actions = QHBoxLayout()
        channel_actions.setContentsMargins(0, 0, 0, 0)
        channel_actions.addWidget(self._selection_action("Tüm kanalları seç", self.notification_channel_checks, True))
        channel_actions.addWidget(self._selection_action("Kanal seçimini temizle", self.notification_channel_checks, False))
        channel_actions.addStretch()
        channel_outer.addLayout(channel_actions)
        cl.addWidget(self._row(
            "Takip edilen kanallar",
            "Takip etmek istediğiniz kanal kartlarına tıklayın; renkli ve ✓ işaretli kartlar bildirim listesine eklenir.",
            channel_box,
        ))

        self.tracked_terms = QLineEdit()
        self.tracked_terms.setMinimumWidth(390)
        self.tracked_terms.setPlaceholderText("Örnek: KB5120996, 26300, 28120")
        cl.addWidget(self._row(
            "Belirli KB veya build ailesi",
            "Tam KB numaralarını veya 26300 gibi build ailesini virgülle ayırarak yazın.",
            self.tracked_terms,
        ))
        button_row = QHBoxLayout()
        clear_cache = QPushButton("Build Tracker Önbelleğini Temizle")
        clear_cache.setObjectName("secondaryButton")
        clear_cache.clicked.connect(self._clear_tracker_cache)
        button_row.addWidget(clear_cache)
        button_row.addStretch()
        cl.addLayout(button_row)
        layout.addStretch()
        return page

    @staticmethod
    def _selection_action(text: str, choices: dict, checked: bool) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("watchSelectionAction")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda: [choice.setChecked(checked) for choice in choices.values()])
        return button

    def _advanced_page(self):
        page, layout, card, cl = self._page_shell(
            "Gelişmiş Ayarlar",
            "Program verilerini, günlükleri ve önbelleği yönetin.",
        )
        buttons = [
            ("Log klasörünü aç", "Program günlük dosyalarının bulunduğu klasörü açar.", self._open_logs),
            ("Sorun bildirim paketi oluştur", "Günlük dosyalarını ve sistem bilgisini tek bir ZIP dosyasında toplar (kişisel dosya içermez).", self._create_support_bundle),
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
            active = i == index
            btn.setIcon(icons.icon(
                self.NAV_ICONS[i], "#FFFFFF" if active else "#23406B", 22,
                bg=self.BLUE if active else "#FFFFFF", stroke=1.9,
            ))

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

        self._set_combo(self.theme_combo, {"light": "Açık", "dark": "Koyu", "system": "Sistem"}.get(s.get("appearance", {}).get("theme", "light"), "Açık"))
        self._set_combo(self.language_combo, {"auto": "Otomatik (Windows dili)", "tr": "Türkçe", "en": "English"}.get(g.get("language", "auto"), "Otomatik (Windows dili)"))
        self.open_last_page.setChecked(bool(g["open_last_page"]))
        self.check_app_updates.setChecked(bool(g.get("check_app_updates", True)))
        self.check_tracker_on_start.setChecked(bool(g["check_tracker_on_start"]))
        self.run_in_background.setChecked(bool(g["run_in_background"]))
        self.minimize_to_tray.setChecked(bool(g["minimize_to_tray"]))
        self.start_with_windows.setChecked(bool(g["start_with_windows"]))
        self.show_welcome_on_start.setChecked(bool(g.get("show_welcome_on_start", False)))

        self.download_folder.setText(str(d["default_folder"]))
        self.max_concurrent.setValue(int(d["max_concurrent"]))
        self.open_download_folder.setChecked(bool(d["open_folder_on_complete"]))
        limit_value = int(d.get("speed_limit_kbps", 0) or 0)
        self.speed_limit.setCurrentIndex(next((i for i, (_, v) in enumerate(self.SPEED_LIMITS) if v == limit_value), 0))
        self.schedule_enabled.setChecked(bool(d.get("schedule_enabled", False)))
        self._set_combo(self.schedule_start, str(d.get("schedule_start", "01:00")))
        self._set_combo(self.schedule_end, str(d.get("schedule_end", "07:00")))
        self.resume_incomplete.setChecked(bool(d["resume_incomplete"]))
        self._set_combo(self.duplicate_policy, f"Dosya Çakışması: {d['duplicate_policy']}")

        self._set_combo(self.default_arch, f"Mimari: {u['default_architecture']}")
        self._set_combo(self.default_language, f"Dil: {u['default_language']}")
        self._set_combo(self.default_edition, f"Edition: {u['default_edition']}")
        self.iso_work_folder.setText(str(u["work_folder"]))
        self.iso_output_folder.setText(str(u["output_folder"]))
        self.open_iso_folder.setChecked(bool(u["open_iso_folder_on_complete"]))
        self.auto_create_iso.setChecked(bool(u.get("auto_create_iso", True)))
        self.clean_temp_files.setChecked(bool(u["clean_temp_files"]))

        self.tracker_source.setText(str(b["source_url"]))
        self.tracker_refresh_start.setChecked(bool(b["refresh_on_start"]))
        minutes = int(b["refresh_interval_minutes"])
        label = {30: "30 dakika", 60: "1 saat", 120: "2 saat", 360: "6 saat"}.get(minutes, "1 saat")
        self._set_combo(self.tracker_interval, f"Güncelleme Sıklığı: {label}")
        self.tracker_notifications.setChecked(bool(b.get("notifications_enabled", True)))
        self.watchlist_enabled.setChecked(bool(b.get("watchlist_enabled", False)))
        selected_versions = set(b.get("tracked_versions", []))
        for version, check in self.tracked_version_checks.items():
            check.setChecked(version in selected_versions)
        self.tracked_terms.setText(", ".join(str(value) for value in b.get("tracked_terms", [])))
        selected_channels = set(b.get("notification_channels", []))
        for channel, check in self.notification_channel_checks.items():
            check.setChecked(channel in selected_channels)

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
                "check_app_updates": self.check_app_updates.isChecked(),
                "show_welcome_on_start": self.show_welcome_on_start.isChecked(),
                "language": {"Otomatik (Windows dili)": "auto", "Türkçe": "tr", "English": "en"}.get(self.language_combo.currentText(), "auto"),
            },
            "downloads": {
                "default_folder": self.download_folder.text().strip(),
                "max_concurrent": self.max_concurrent.value(),
                "open_folder_on_complete": self.open_download_folder.isChecked(),
                "resume_incomplete": self.resume_incomplete.isChecked(),
                "duplicate_policy": self._strip_prefix(self.duplicate_policy.currentText()),
                "speed_limit_kbps": self.SPEED_LIMITS[max(0, self.speed_limit.currentIndex())][1],
                "schedule_enabled": self.schedule_enabled.isChecked(),
                "schedule_start": self.schedule_start.currentText() or "01:00",
                "schedule_end": self.schedule_end.currentText() or "07:00",
            },
            "uup_iso": {
                "default_architecture": self._strip_prefix(self.default_arch.currentText()),
                "default_language": self._strip_prefix(self.default_language.currentText()),
                "default_edition": self._strip_prefix(self.default_edition.currentText()),
                "work_folder": self.iso_work_folder.text().strip(),
                "output_folder": self.iso_output_folder.text().strip(),
                "open_iso_folder_on_complete": self.open_iso_folder.isChecked(),
                "clean_temp_files": self.clean_temp_files.isChecked(),
                "auto_create_iso": self.auto_create_iso.isChecked(),
            },
            "build_tracker": {
                "source_url": "https://bunyaminkaya.com/windows-build-tracker/",
                "refresh_on_start": self.tracker_refresh_start.isChecked(),
                "refresh_interval_minutes": interval_map.get(interval_text, 60),
                "notifications_enabled": self.tracker_notifications.isChecked(),
                "watchlist_enabled": self.watchlist_enabled.isChecked(),
                "tracked_versions": [
                    version for version, check in self.tracked_version_checks.items()
                    if check.isChecked()
                ],
                "tracked_terms": [
                    term.strip().upper()
                    for term in self.tracked_terms.text().replace(";", ",").split(",")
                    if term.strip()
                ],
                "notification_channels": [
                    channel for channel, check in self.notification_channel_checks.items()
                    if check.isChecked()
                ],
            },
            "advanced": self._settings.get("advanced", {}),
            "iso_center": SettingsService.load().get("iso_center", {}),
            "onboarding": SettingsService.load().get("onboarding", {}),
            "appearance": {"theme": {"Açık": "light", "Koyu": "dark", "Sistem": "system"}.get(self.theme_combo.currentText(), "light")},
        }
        theme_changed = self._settings["appearance"]["theme"] != SettingsService.load().get("appearance", {}).get("theme", "light")
        language_changed = self._settings["general"]["language"] != SettingsService.load().get("general", {}).get("language", "auto")
        self._apply_startup_preference(self.start_with_windows.isChecked())
        SettingsService.save(self._settings)
        DownloadManager.instance().apply_settings(self._settings["downloads"])
        self.settings_saved.emit(self._settings)
        message = "Ayarlar başarıyla kaydedildi ve uygulanabilir değişiklikler hemen etkinleştirildi."
        if theme_changed:
            message += "\n\nTema değişikliği için programı kapatıp yeniden açın."
        if language_changed:
            message += "\n\nDil değişikliği için programı kapatıp yeniden açın."
        show_information(self, "Ayarlar", message)

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

    def _create_support_bundle(self):
        """Log dosyaları + kısa sistem özeti içeren ZIP üretir (yalnızca yardımcı işlev)."""
        import platform
        import zipfile
        from datetime import datetime
        from app.version import APP_VERSION
        try:
            target_dir = Path.home() / "Desktop"
            if not target_dir.exists():
                target_dir = Path.home()
            target = target_dir / f"WUBC_sorun_paketi_{datetime.now():%Y%m%d_%H%M%S}.zip"
            info = (
                f"Program sürümü: {APP_VERSION}\n"
                f"Sistem: {platform.platform()}\n"
                f"Python: {platform.python_version()}\n"
                f"Oluşturulma: {datetime.now():%d.%m.%Y %H:%M:%S}\n"
            )
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("sistem_bilgisi.txt", info)
                for log_file in sorted(Path(LOG_DIR).glob("*.log*")):
                    if log_file.is_file():
                        bundle.write(log_file, f"logs/{log_file.name}")
            show_information(self, "Sorun bildirim paketi", f"Paket oluşturuldu:\n{target}\n\nBu dosyayı sorun bildirirken ekleyebilirsiniz.")
            self._open_path(target.parent)
        except Exception as exc:
            show_information(self, "Sorun bildirim paketi", f"Paket oluşturulamadı:\n{exc}")

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

    @classmethod
    def _styles_with_arrows(cls) -> str:
        import os, tempfile
        d = tempfile.gettempdir()
        paths = {}
        for key, name in (("%UP%", "chevron-down"), ("%DOWN%", "chevron-down")):
            try:
                pm = icons.pixmap(name, "#4B5E7C", 10, stroke=2.2)
                if key == "%UP%":
                    pm = pm.transformed(__import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform().scale(1, -1))
                f = os.path.join(d, "wubc_spin_%s.png" % ("up" if key == "%UP%" else "down"))
                pm.save(f, "PNG")
                paths[key] = f.replace("\\", "/")
            except Exception:
                paths[key] = ""
        css = cls._styles()
        for k, v in paths.items():
            css = css.replace(k, v)
        return css

    @staticmethod
    def _styles() -> str:
        return """
            QLabel#stTitle { font-size: 30px; font-weight: 700; color: #0A1F44; }
            QLabel#stSubtitle { font-size: 14px; color: #5F7090; }
            QLabel#stHeaderTile {
                background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 18px;
            }

            QFrame#settingsNav, QFrame#settingsContent {
                background: #FFFFFF;
                border: 1px solid #DCE5F1;
                border-radius: 14px;
            }
            QPushButton#settingsNavButton {
                text-align: left;
                padding: 0 8px 0 10px;
                border: none;
                border-radius: 11px;
                color: #1B2B48;
                background: transparent;
                font-size: 13px;
                font-weight: 500;
                min-height: 46px;
                max-height: 46px;
            }
            QPushButton#settingsNavButton:hover { background: #EEF4FD; }
            QPushButton#settingsNavButton:checked {
                background: #1768E0; color: #FFFFFF; font-weight: 700;
            }

            QScrollArea#settingsScroll { background: transparent; border: none; }

            QFrame#settingsCard { background: transparent; border: none; }
            QLabel#stPageTile { background: #EAF2FE; border: 1px solid #D7E6FB; border-radius: 18px; }
            QLabel#settingsSectionTitle { color: #0A1F44; font-size: 22px; font-weight: 700; }
            QLabel#settingsSectionDescription { color: #5F7090; font-size: 14px; }

            QFrame#settingRow {
                background: #FFFFFF;
                border: 1px solid #E0E8F3;
                border-radius: 13px;
            }
            QLabel#settingIcon { background: #EAF2FE; border-radius: 27px; }
            QLabel#settingTitle { color: #0F2347; font-size: 14px; font-weight: 700; }
            QLabel#settingDescription { color: #7686A0; font-size: 12px; }

            QFrame#settingsFooter {
                background: #F9FBFE;
                border: none;
                border-top: 1px solid #E3EAF4;
                border-bottom-left-radius: 13px;
                border-bottom-right-radius: 13px;
            }
            QPushButton#stPrimaryButton {
                background: #1768E0; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 0 24px; font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
            }
            QPushButton#stPrimaryButton:hover { background: #1259C4; }
            QPushButton#stGhostButton {
                background: #FFFFFF; color: #1768E0; border: 1px solid #A9C2EA; border-radius: 10px;
                padding: 0 22px; font-size: 13px; font-weight: 600; min-height: 44px; max-height: 44px;
            }
            QPushButton#stGhostButton:hover { background: #F2F7FF; }

            QPushButton#watchChoice {
                background: #FFFFFF; color: #42546B; border: 1px solid #C9D6E8;
                border-radius: 9px; padding: 7px 12px; font-weight: 600; min-height: 20px;
            }
            QPushButton#watchChoice:hover { background: #EEF4FF; border-color: #6F9FE5; color: #174F9F; }
            QPushButton#watchChoice:checked {
                background: #1768E0; color: #FFFFFF; border: 1px solid #1768E0;
            }
            QPushButton#watchChoice:checked:hover { background: #1259C4; border-color: #1259C4; }
            QPushButton#watchSelectionAction {
                background: transparent; color: #1768E0; border: none; padding: 2px 5px;
                min-height: 18px; font-size: 11px; font-weight: 600;
            }
            QPushButton#watchSelectionAction:hover { color: #0F4DAA; text-decoration: underline; }
            QPushButton#secondaryButton {
                background: #FFFFFF;
                color: #1768E0;
                border: 1px solid #A9C2EA;
                border-radius: 10px;
                padding: 0 18px;
                font-size: 12px;
                font-weight: 600;
                min-height: 40px;
                max-height: 40px;
            }
            QPushButton#secondaryButton:hover { background: #F2F7FF; border-color: #7FA6E4; }

            QLineEdit {
                background: #FFFFFF; color: #14213D; border: 1px solid #D0DCEC; border-radius: 10px;
                padding: 0 12px; font-size: 13px; min-height: 40px; max-height: 40px;
                selection-background-color: #1768E0;
            }
            QLineEdit:focus { border: 1px solid #1768E0; }
            QLineEdit:read-only { background: #F5F8FC; color: #4B5E7C; }
            QSpinBox {
                background: #FFFFFF; color: #14213D; border: 1px solid #D0DCEC; border-radius: 10px;
                padding: 0 12px; font-size: 13px; min-height: 40px; max-height: 40px;
            }
            QSpinBox:focus { border: 1px solid #1768E0; }
            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border; width: 22px; border: none; background: transparent;
            }
            QSpinBox::up-button { subcontrol-position: top right; margin: 4px 6px 0 0; }
            QSpinBox::down-button { subcontrol-position: bottom right; margin: 0 6px 4px 0; }
            QSpinBox::up-arrow { image: url(%UP%); width: 10px; height: 10px; }
            QSpinBox::down-arrow { image: url(%DOWN%); width: 10px; height: 10px; }
            QComboBox#modernComboBox {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 10px;
                padding: 0 28px 0 12px; font-size: 13px; color: #1B2B48;
                min-height: 40px; max-height: 40px;
            }
            QComboBox#modernComboBox[popupOpen="true"] { border: 1px solid #1768E0; }
        """
