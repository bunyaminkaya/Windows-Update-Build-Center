from __future__ import annotations

import platform
import webbrowser
from urllib.parse import quote

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
    QTextEdit,
    QLineEdit,
    QButtonGroup,
    QCheckBox,
)

from app.version import APP_NAME, APP_VERSION
from app.paths import ICON_DIR
from ui.widgets.message_dialog import show_information, show_warning


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 24)
        root.setSpacing(16)

        subtitle = QLabel(
            "Windows Update & Build Center hakkında ürün, geliştirici ve iletişim bilgileri."
        )
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(subtitle)

        # Ürün kimliği / hero
        hero = QFrame()
        hero.setObjectName("aboutHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(18)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(10)
        brand_logo = QLabel()
        brand_logo.setObjectName("aboutBrandBanner")
        brand_logo.setMinimumHeight(112)
        brand_logo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        banner_path = ICON_DIR / "brand_banner.png"
        if banner_path.exists():
            brand_logo.setPixmap(
                QPixmap(str(banner_path)).scaled(
                    590, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        description = QLabel(
            "Resmi Microsoft güncellemelerini, Windows build kayıtlarını ve UUP paketlerini "
            "tek merkezden bulmak, takip etmek ve güvenli biçimde indirmek için geliştirilmiştir."
        )
        description.setObjectName("aboutDescription")
        description.setWordWrap(True)
        brand_box.addWidget(brand_logo)
        brand_box.addWidget(description)
        hero_layout.addLayout(brand_box, 1)

        version_box = QFrame()
        version_box.setObjectName("versionBox")
        version_box.setMinimumWidth(170)
        vb = QVBoxLayout(version_box)
        vb.setContentsMargins(16, 14, 16, 14)
        vb.setSpacing(4)
        vkey = QLabel("GÜNCEL SÜRÜM")
        vkey.setObjectName("versionKey")
        version = QLabel(APP_VERSION)
        version.setObjectName("versionValue")
        status = QLabel("Kararlı")
        status.setObjectName("versionStatus")
        vb.addWidget(vkey)
        vb.addWidget(version)
        vb.addWidget(status)
        vb.addStretch()
        hero_layout.addWidget(version_box)

        root.addWidget(hero)

        content = QHBoxLayout()
        content.setSpacing(14)

        # Geliştirici kartı
        developer_card = QFrame()
        developer_card.setObjectName("aboutCard")
        dev = QVBoxLayout(developer_card)
        dev.setContentsMargins(20, 20, 20, 20)
        dev.setSpacing(14)

        dev_title = QLabel("Geliştirici")
        dev_title.setObjectName("sectionTitle")
        dev.addWidget(dev_title)

        dev_name = QLabel("Bünyamin KAYA")
        dev_name.setObjectName("developerName")
        dev_role = QLabel("Geliştirici • bunyaminkaya.com")
        dev_role.setObjectName("developerRole")
        dev.addWidget(dev_name)
        dev.addWidget(dev_role)

        contact_grid = QGridLayout()
        contact_grid.setHorizontalSpacing(14)
        contact_grid.setVerticalSpacing(10)
        self._add_contact(contact_grid, 0, "Web Sitesi", "bunyaminkaya.com")
        self._add_contact(contact_grid, 1, "E-posta", "bunyaminkaya@gmail.com")
        self._add_contact(contact_grid, 2, "Program", APP_NAME)
        self._add_contact(contact_grid, 3, "Sürüm", APP_VERSION)
        dev.addLayout(contact_grid)
        dev.addStretch()

        actions = QHBoxLayout()
        actions.setSpacing(10)
        web_btn = QPushButton("Web Sitesini Aç")
        web_btn.setObjectName("primaryButton")
        web_btn.clicked.connect(lambda: webbrowser.open("https://bunyaminkaya.com"))
        mail_btn = QPushButton("E-posta Gönder")
        mail_btn.clicked.connect(lambda: webbrowser.open("mailto:bunyaminkaya@gmail.com"))
        actions.addWidget(web_btn)
        actions.addWidget(mail_btn)
        actions.addStretch()
        dev.addLayout(actions)
        content.addWidget(developer_card, 3)

        # Ürün kabiliyetleri kartı
        product_card = QFrame()
        product_card.setObjectName("aboutCard")
        prod = QVBoxLayout(product_card)
        prod.setContentsMargins(20, 20, 20, 20)
        prod.setSpacing(12)

        prod_title = QLabel("Program Özellikleri")
        prod_title.setObjectName("sectionTitle")
        prod.addWidget(prod_title)

        features = [
            ("Microsoft Güncelleme Merkezi", "KB ve build numarasıyla resmi güncellemeleri bulur ve indirir."),
            ("Windows Build Tracker", "Windows build ve KB kayıtlarını güncel kaynaktan takip eder."),
            ("UUP Merkezi", "UUP paketlerini bulur, indirir ve ISO hazırlama sürecini yönetir."),
            ("İndirme Yöneticisi", "İndirmeleri kuyruk, hız, durum ve ilerleme bilgileriyle yönetir."),
        ]
        for name, desc in features:
            prod.addWidget(self._feature_card(name, desc))
        prod.addStretch()
        content.addWidget(product_card, 4)

        root.addLayout(content, 1)

        # Kullanıcı geri bildirimi
        feedback_card = QFrame()
        feedback_card.setObjectName("feedbackCard")
        feedback_layout = QVBoxLayout(feedback_card)
        feedback_layout.setContentsMargins(20, 18, 20, 18)
        feedback_layout.setSpacing(12)

        feedback_header = QHBoxLayout()
        feedback_title_box = QVBoxLayout()
        feedback_title_box.setSpacing(3)
        feedback_title = QLabel("Geri Bildirim Gönder")
        feedback_title.setObjectName("sectionTitle")
        feedback_subtitle = QLabel(
            "Bir hata mı buldunuz, öneriniz mi var? Türü seçin, mesajınızı yazın ve gönderin."
        )
        feedback_subtitle.setObjectName("feedbackSubtitle")
        feedback_subtitle.setWordWrap(True)
        feedback_title_box.addWidget(feedback_title)
        feedback_title_box.addWidget(feedback_subtitle)
        feedback_header.addLayout(feedback_title_box, 1)

        self.feedback_counter = QLabel("0 / 1500")
        self.feedback_counter.setObjectName("feedbackCounter")
        feedback_header.addWidget(self.feedback_counter, 0, Qt.AlignBottom)
        feedback_layout.addLayout(feedback_header)

        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        self.feedback_type_group = QButtonGroup(self)
        self.feedback_type_group.setExclusive(True)
        self.feedback_type_buttons = []
        for index, label in enumerate(("Hata Bildirimi", "Öneri", "Tavsiye")):
            button = QPushButton(label)
            button.setObjectName("feedbackTypeButton")
            button.setCheckable(True)
            button.setProperty("feedbackType", True)
            if index == 0:
                button.setChecked(True)
            self.feedback_type_group.addButton(button)
            self.feedback_type_buttons.append(button)
            type_row.addWidget(button)
        type_row.addStretch()
        feedback_layout.addLayout(type_row)

        self.feedback_message = QTextEdit()
        self.feedback_message.setObjectName("feedbackMessage")
        self.feedback_message.setPlaceholderText(
            "Kısaca ne olduğunu veya ne önerdiğinizi yazın...\n\n"
            "Örnek: Windows Build Tracker ekranında şu işlemi yaparken..."
        )
        self.feedback_message.setMaximumHeight(135)
        self.feedback_message.textChanged.connect(self._feedback_text_changed)
        feedback_layout.addWidget(self.feedback_message)

        feedback_bottom = QHBoxLayout()
        feedback_bottom.setSpacing(10)

        self.feedback_contact = QLineEdit()
        self.feedback_contact.setObjectName("feedbackContact")
        self.feedback_contact.setPlaceholderText("E-posta adresiniz (isteğe bağlı)")
        self.feedback_contact.setMaximumWidth(320)
        feedback_bottom.addWidget(self.feedback_contact)

        self.feedback_system_info = QCheckBox("Program ve sistem bilgilerini otomatik ekle")
        self.feedback_system_info.setChecked(True)
        self.feedback_system_info.setToolTip(
            "Sürüm, Windows sürümü ve mimari bilgisi mesaja eklenir; kişisel dosyalar gönderilmez."
        )
        feedback_bottom.addWidget(self.feedback_system_info)
        feedback_bottom.addStretch()

        clear_feedback = QPushButton("Temizle")
        clear_feedback.setObjectName("secondaryButton")
        clear_feedback.clicked.connect(self._clear_feedback)
        send_feedback = QPushButton("Geri Bildirimi Gönder")
        send_feedback.setObjectName("primaryButton")
        send_feedback.clicked.connect(self._send_feedback)
        feedback_bottom.addWidget(clear_feedback)
        feedback_bottom.addWidget(send_feedback)
        feedback_layout.addLayout(feedback_bottom)

        privacy_note = QLabel(
            "Gönder düğmesi, mesajınızı varsayılan e-posta uygulamanızda hazırlar. "
            "Siz onaylayana kadar hiçbir bilgi gönderilmez."
        )
        privacy_note.setObjectName("feedbackPrivacy")
        privacy_note.setWordWrap(True)
        feedback_layout.addWidget(privacy_note)

        root.addWidget(feedback_card)

        footer = QFrame()
        footer.setObjectName("aboutFooterCard")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.setSpacing(8)
        copyright_label = QLabel("© Bünyamin KAYA")
        copyright_label.setObjectName("aboutFooter")
        site_label = QLabel("bunyaminkaya.com")
        site_label.setObjectName("aboutFooterAccent")
        fl.addWidget(copyright_label)
        fl.addWidget(QLabel("•"))
        fl.addWidget(site_label)
        fl.addStretch()
        build_label = QLabel(f"{APP_NAME}  {APP_VERSION}")
        build_label.setObjectName("aboutFooter")
        fl.addWidget(build_label)
        root.addWidget(footer)

        self.setStyleSheet("""
            QFrame#aboutHero {
                background: #F7FAFF;
                border: 1px solid #CFE0F6;
                border-radius: 14px;
            }
            QFrame#aboutCard {
                background: #FFFFFF;
                border: 1px solid #DCE5F0;
                border-radius: 12px;
            }
            QFrame#aboutLogoBox {
                background: #2167D5;
                border: none;
                border-radius: 18px;
            }
            QLabel#aboutLogoText {
                color: #FFFFFF;
                font-size: 25px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#aboutAppName {
                color: #0B1736;
                font-size: 26px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#aboutTagline {
                color: #2167D5;
                font-size: 13px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#aboutDescription {
                color: #65728A;
                font-size: 13px;
                background: transparent;
            }
            QFrame#versionBox {
                background: #FFFFFF;
                border: 1px solid #D6E3F3;
                border-radius: 10px;
            }
            QLabel#versionKey {
                color: #7B8DA5;
                font-size: 10px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#versionValue {
                color: #0B1736;
                font-size: 24px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#versionStatus {
                color: #218A50;
                font-size: 12px;
                font-weight: 700;
                background: #EAF8F0;
                border-radius: 6px;
                padding: 4px 8px;
            }
            QLabel#developerName {
                color: #0B1736;
                font-size: 20px;
                font-weight: 800;
                background: transparent;
            }
            QLabel#developerRole {
                color: #65728A;
                font-size: 12px;
                background: transparent;
            }
            QLabel#aboutInfoKey {
                color: #7B8DA5;
                font-size: 11px;
                font-weight: 600;
                background: transparent;
            }
            QLabel#aboutInfoValue {
                color: #14213D;
                font-size: 13px;
                font-weight: 650;
                background: transparent;
            }
            QFrame#featureCard {
                background: #F7FAFF;
                border: 1px solid #E0E9F5;
                border-radius: 9px;
            }
            QLabel#featureTitle {
                color: #10264A;
                font-size: 13px;
                font-weight: 750;
                background: transparent;
            }
            QLabel#featureDesc {
                color: #6F7F95;
                font-size: 11px;
                background: transparent;
            }
            QFrame#aboutFooterCard {
                background: #F7FAFF;
                border: 1px solid #DCE5F0;
                border-radius: 9px;
            }
            QLabel#aboutFooter {
                color: #7B8DA5;
                font-size: 11px;
                background: transparent;
            }
            QLabel#aboutFooterAccent {
                color: #2167D5;
                font-size: 11px;
                font-weight: 700;
                background: transparent;
            }

            QFrame#feedbackCard {
                background: #FFFFFF;
                border: 1px solid #DCE5F0;
                border-radius: 12px;
            }
            QLabel#feedbackSubtitle {
                color: #65728A;
                font-size: 12px;
                background: transparent;
            }
            QLabel#feedbackCounter {
                color: #7B8DA5;
                font-size: 11px;
                background: transparent;
            }
            QPushButton#feedbackTypeButton {
                background: #F7FAFF;
                color: #3F5876;
                border: 1px solid #D4E0EF;
                border-radius: 8px;
                padding: 7px 14px;
                font-weight: 650;
            }
            QPushButton#feedbackTypeButton:hover {
                background: #EDF4FF;
                border-color: #AFC8EA;
            }
            QPushButton#feedbackTypeButton:checked {
                background: #2167D5;
                color: #FFFFFF;
                border-color: #2167D5;
            }
            QTextEdit#feedbackMessage {
                background: #FBFDFF;
                color: #14213D;
                border: 1px solid #C9D5E4;
                border-radius: 9px;
                padding: 10px;
                selection-background-color: #2167D5;
            }
            QTextEdit#feedbackMessage:focus {
                border: 1px solid #2167D5;
                background: #FFFFFF;
            }
            QLineEdit#feedbackContact {
                background: #FFFFFF;
                color: #14213D;
                border: 1px solid #C9D5E4;
                border-radius: 8px;
                padding: 8px 10px;
            }
            QLabel#feedbackPrivacy {
                color: #8290A3;
                font-size: 10px;
                background: #F7FAFF;
                border-radius: 7px;
                padding: 7px 9px;
            }
        """)


    def _selected_feedback_type(self) -> str:
        checked = self.feedback_type_group.checkedButton()
        return checked.text() if checked else "Hata Bildirimi"

    def _feedback_text_changed(self) -> None:
        text = self.feedback_message.toPlainText()
        if len(text) > 1500:
            cursor = self.feedback_message.textCursor()
            cursor.setPosition(1500)
            cursor.movePosition(cursor.End, cursor.KeepAnchor)
            cursor.removeSelectedText()
            text = self.feedback_message.toPlainText()
        self.feedback_counter.setText(f"{len(text)} / 1500")

    def _clear_feedback(self) -> None:
        self.feedback_message.clear()
        self.feedback_contact.clear()
        if self.feedback_type_buttons:
            self.feedback_type_buttons[0].setChecked(True)
        self.feedback_system_info.setChecked(True)

    def _send_feedback(self) -> None:
        message = self.feedback_message.toPlainText().strip()
        if not message:
            show_warning(
                self,
                "Geri Bildirim",
                "Göndermek istediğiniz mesajı kısaca yazın.",
            )
            self.feedback_message.setFocus()
            return

        feedback_type = self._selected_feedback_type()
        contact = self.feedback_contact.text().strip()
        subject = f"{APP_NAME} {APP_VERSION} - {feedback_type}"

        lines = [
            f"Geri Bildirim Türü: {feedback_type}",
            "",
            message,
        ]

        if contact:
            lines.extend(["", f"İletişim E-postası: {contact}"])

        if self.feedback_system_info.isChecked():
            lines.extend([
                "",
                "--- Otomatik Sistem Bilgileri ---",
                f"Program: {APP_NAME}",
                f"Sürüm: {APP_VERSION}",
                f"İşletim Sistemi: {platform.system()} {platform.release()}",
                f"Sistem Mimarisi: {platform.machine() or 'Bilinmiyor'}",
            ])

        body = "\r\n".join(lines)
        mailto = (
            "mailto:bunyaminkaya@gmail.com"
            f"?subject={quote(subject)}"
            f"&body={quote(body)}"
        )

        opened = webbrowser.open(mailto)
        if opened:
            show_information(
                self,
                "Geri Bildirim Hazırlandı",
                "Mesajınız e-posta uygulamanızda hazırlandı. Göndermeden önce son kez kontrol edebilirsiniz.",
            )
        else:
            show_warning(
                self,
                "E-posta Uygulaması Açılamadı",
                "Varsayılan e-posta uygulaması açılamadı. Geri bildiriminizi bunyaminkaya@gmail.com adresine gönderebilirsiniz.",
            )

    @staticmethod
    def _add_contact(grid: QGridLayout, row: int, key: str, value: str) -> None:
        key_label = QLabel(key)
        key_label.setObjectName("aboutInfoKey")
        value_label = QLabel(value)
        value_label.setObjectName("aboutInfoValue")
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(key_label, row, 0)
        grid.addWidget(value_label, row, 1)

    @staticmethod
    def _feature_card(title: str, description: str) -> QFrame:
        card = QFrame()
        card.setObjectName("featureCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("featureTitle")
        desc_label = QLabel(description)
        desc_label.setObjectName("featureDesc")
        desc_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(desc_label)
        return card
