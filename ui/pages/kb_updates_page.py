from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRect, QRectF, QSize, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFontMetrics, QIcon, QPainter, QPainterPath, QTransform
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QStackedWidget,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.build_tracker_service import BuildTrackerRecord, BuildTrackerService
from services.settings_service import SettingsService
from services.build_watch_service import BuildWatchService
from services.local_build_service import LocalBuildService
from services.build_history_service import BuildHistoryService
from ui import icons, styles
from ui.widgets.message_dialog import show_error, show_information
from ui.widgets.modern_combo_box import ModernComboBox


class TrackerFetchWorker(QThread):
    loaded = Signal(object, str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            records, last_update = BuildTrackerService().fetch()
            self.loaded.emit(records, last_update)
        except Exception as exc:
            self.failed.emit(str(exc))


class KnownIssuesWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, record: BuildTrackerRecord, parent=None):
        super().__init__(parent)
        self.record = record

    def run(self) -> None:
        try:
            self.loaded.emit(BuildTrackerService().fetch_known_issues(self.record))
        except Exception as exc:
            self.failed.emit(str(exc))


class KnownIssuesDialog(QDialog):
    def __init__(self, record: BuildTrackerRecord, parent=None):
        super().__init__(parent)
        self.record = record
        self.worker = None
        self.setWindowTitle(f"Build {record.build_number} - Bilinen Sorunlar")
        self.resize(900, 680)
        root = QVBoxLayout(self)
        title = QLabel(f"Build {record.build_number} Bilinen Sorunlar")
        title.setObjectName("knownIssuesTitle")
        subtitle = QLabel(f"Windows 11 {record.windows_version or '—'} • {record.channel or '—'} • Microsoft kaynağı")
        subtitle.setObjectName("knownIssuesSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.loading = QLabel("Microsoft kaynağındaki bilinen sorunlar yükleniyor...")
        self.loading.setObjectName("knownIssuesEmpty")
        self.content_layout.addWidget(self.loading)
        self.content_layout.addStretch()
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)
        source = QPushButton("Microsoft Kaynağını Aç")
        source.setObjectName("primaryButton")
        source.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(record.microsoft_url)))
        root.addWidget(source, 0, Qt.AlignRight)
        self.setStyleSheet(styles.qss("""
            QDialog { background: #F5F8FC; }
            QLabel#knownIssuesTitle { color: #10213D; font-size: 23px; font-weight: 700; }
            QLabel#knownIssuesSubtitle, QLabel#knownIssuesEmpty { color: #6C7C93; }
            QFrame#knownIssueCard { background: white; border: 1px solid #DCE5F0; border-radius: 9px; }
            QLabel#issueHeading { color: #10213D; font-weight: 700; font-size: 14px; }
            QLabel#issueKey { color: #6C7C93; font-size: 11px; font-weight: 600; }
            QLabel#issueValue { color: #34465D; font-size: 12px; }
            QLabel#issueStatus { background: #FFF2CF; color: #9A5A08; border-radius: 6px; padding: 4px 8px; font-weight: 700; }
            QPushButton#primaryButton { background: @BLUE@; color: white; border: none; border-radius: 7px; padding: 9px 15px; font-weight: 600; }
        """))
        self.worker = KnownIssuesWorker(record, self)
        self.worker.loaded.connect(self._render)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _clear(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render(self, issues) -> None:
        self._clear()
        if not issues:
            empty = QLabel("Microsoft bu build için bilinen bir sorun yayımlamamış veya yapılandırılmış sorun bilgisi bulunamamıştır.")
            empty.setObjectName("knownIssuesEmpty")
            empty.setWordWrap(True)
            self.content_layout.addWidget(empty)
        for index, issue in enumerate(issues, 1):
            card = QFrame()
            card.setObjectName("knownIssueCard")
            layout = QVBoxLayout(card)
            heading = QLabel(f"Sorun {index}")
            heading.setObjectName("issueHeading")
            layout.addWidget(heading)
            for caption, value in (("Sorunun açıklaması", issue.description), ("Etkilenen sürümler", issue.affected_versions), ("Çözüm durumu", issue.status), ("Geçici çözüm", issue.workaround)):
                key = QLabel(caption)
                key.setObjectName("issueKey")
                label = QLabel(value or "—")
                label.setObjectName("issueStatus" if caption == "Çözüm durumu" else "issueValue")
                label.setWordWrap(True)
                layout.addWidget(key)
                layout.addWidget(label)
            self.content_layout.addWidget(card)
        self.content_layout.addStretch()

    def _failed(self, message: str) -> None:
        self._clear()
        label = QLabel("Microsoft kaynağı okunamadı. İnternet bağlantısını kontrol edip yeniden deneyin.\n" + message)
        label.setObjectName("knownIssuesEmpty")
        label.setWordWrap(True)
        self.content_layout.addWidget(label)
        self.content_layout.addStretch()


class NewUpdateCard(QFrame):
    clicked = Signal(object)

    def __init__(self, record: BuildTrackerRecord, parent=None):
        super().__init__(parent)
        self.record = record
        self.setObjectName("newUpdateCard")
        self.setProperty("channelStyle", _channel_style_key(record.channel))
        self.setCursor(Qt.PointingHandCursor)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        icon = QLabel("▣")
        icon.setObjectName("windowsTileIcon")
        icon.setFixedSize(42, 42)
        icon.setAlignment(Qt.AlignCenter)
        root.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(2)
        kb = QLabel(record.kb_number or f"Build {record.build_number}")
        kb.setObjectName("newUpdateTitle")
        version = QLabel(f"Windows 11 {record.windows_version or ''}".strip())
        version.setObjectName("newUpdateMeta")
        build = QLabel(f"OS Build {record.build_number}")
        build.setObjectName("newUpdateMeta")
        date = QLabel(_display_date(record.release_date))
        date.setObjectName("newUpdateDate")
        text.addWidget(kb)
        text.addWidget(version)
        text.addWidget(build)
        text.addWidget(date)
        root.addLayout(text, 1)

        badge = QLabel(record.channel or _kind_text(record))
        badge.setObjectName("updateKindBadge")
        badge.setProperty("kind", _kind_key(record))
        badge.setProperty("channelStyle", _channel_style_key(record.channel))
        badge.setAlignment(Qt.AlignCenter)
        root.addWidget(badge, 0, Qt.AlignTop)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.record)


def _display_date(value: str) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        return value


def _kind_key(record: BuildTrackerRecord) -> str:
    channel = (record.channel or "").lower()
    if "retail" in channel or channel == "ga" or "ga / retail" in channel:
        return "security"
    if "preview" in channel or "beta" in channel or "experimental" in channel:
        return "preview"
    if "dev" in channel or "canary" in channel:
        return "insider"
    return "neutral"


def _kind_text(record: BuildTrackerRecord) -> str:
    key = _kind_key(record)
    return {
        "security": "Güvenlik",
        "preview": "Önizleme",
        "insider": "Insider",
        "neutral": record.channel or "Build",
    }.get(key, "Build")


def _channel_style_key(channel: str) -> str:
    value = (channel or "").strip().lower()
    if "release preview" in value:
        return "release-preview"
    if "experimental" in value:
        return "experimental"
    if "beta" in value:
        return "beta"
    if "canary" in value:
        return "canary"
    if value == "dev" or value.startswith("dev "):
        return "dev"
    if "retail" in value or value == "ga":
        return "retail"
    return "neutral"


# bunyaminkaya.com Windows Sürüm Takibi kartlarının birebir renk paleti.
CHANNEL_COLORS = {
    "retail": ("#F7FAFF", "#1D4ED8"),
    "release-preview": ("#FFFBF2", "#B45309"),
    "beta": ("#F5FCF7", "#15803D"),
    "experimental": ("#FAF7FF", "#7C3AED"),
    "dev": ("#F7FAFF", "#1D4ED8"),
    "canary": ("#FFF8F8", "#DC2626"),
    "neutral": ("#FAFBFC", "#475569"),
}


def _comparison_key(record: BuildTrackerRecord) -> str:
    return "|".join((record.build_number, record.windows_version, record.channel, record.release_date))


class ComparisonDetailsWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, records: list[BuildTrackerRecord], parent=None):
        super().__init__(parent)
        self.records = list(records)

    def run(self) -> None:
        try:
            service = BuildTrackerService()
            result = {_comparison_key(record): service.fetch_change_details(record) for record in self.records}
            self.loaded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class BuildComparisonDialog(QDialog):
    def __init__(self, selected_records: list[BuildTrackerRecord], parent=None):
        super().__init__(parent)
        records = sorted(list(selected_records), key=lambda r: (r.release_date or "", r.build_number))
        self.records = records
        self.detail_labels: dict[str, dict[str, QLabel]] = {}
        self.worker: ComparisonDetailsWorker | None = None
        self.setWindowTitle("Build Değişikliklerini Karşılaştır")
        self.resize(1380 if len(records) == 3 else 1120, 780)
        self.setMinimumSize(980, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Build Değişikliklerini Karşılaştır")
        title.setObjectName("comparisonTitle")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        for column, record in enumerate(records):
            card = QFrame()
            card.setObjectName("comparisonCard")
            card.setProperty("channelStyle", _channel_style_key(record.channel))
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 14, 16, 16)
            layout.setSpacing(9)

            # Sütun başlığı her zaman build numarasıdır. KB yalnızca bilgi
            # alanında gösterilir; böylece üç sütunun kimliği karışmaz.
            heading = QLabel(f"Build {record.build_number}")
            heading.setObjectName("comparisonBuild")
            layout.addWidget(heading)
            metadata = QLabel(
                f"Windows 11 {record.windows_version or '—'}\n"
                f"Build: {record.build_number or '—'}\n"
                f"KB: {record.kb_number or '—'}\n"
                f"Kanal: {record.channel or '—'}\n"
                f"Yayın tarihi: {_display_date(record.release_date)}"
            )
            metadata.setObjectName("comparisonMetadata")
            layout.addWidget(metadata)

            key = _comparison_key(record)
            self.detail_labels[key] = {}
            for section_key, section_title in (
                ("added_features", "Eklenen Özellikler"),
                ("fixed_issues", "Düzeltilen Sorunlar"),
                ("known_issues", "Bilinen Sorunlar"),
            ):
                section = QLabel(section_title)
                section.setObjectName("comparisonSection")
                layout.addWidget(section)
                value = QLabel("Kaynak bilgileri okunuyor...")
                value.setObjectName("comparisonText")
                value.setWordWrap(True)
                value.setTextInteractionFlags(Qt.TextSelectableByMouse)
                layout.addWidget(value)
                self.detail_labels[key][section_key] = value
            layout.addStretch()
            grid.addWidget(card, 0, column)

        for column in range(len(records)):
            grid.setColumnStretch(column, 1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self.status = QLabel("İlgili makale ve Microsoft kaynakları kontrol ediliyor...")
        self.status.setObjectName("comparisonStatus")
        footer.addWidget(self.status, 1)
        close_button = QPushButton("Kapat")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self.setStyleSheet("""
            QDialog { background: #F5F8FC; }
            QLabel#comparisonTitle { color: #10213D; font-size: 22px; font-weight: 700; }
            QFrame#comparisonCard { background: #FFFFFF; border: 1px solid #DCE5F0; border-radius: 10px; }
            QFrame#comparisonCard[channelStyle="retail"], QFrame#comparisonCard[channelStyle="dev"] { background: #F7FAFF; border-color: #DBEAFE; }
            QFrame#comparisonCard[channelStyle="release-preview"] { background: #FFFBF2; border-color: #FDE7B2; }
            QFrame#comparisonCard[channelStyle="beta"] { background: #F5FCF7; border-color: #D6F1DE; }
            QFrame#comparisonCard[channelStyle="experimental"] { background: #FAF7FF; border-color: #EADCFF; }
            QFrame#comparisonCard[channelStyle="canary"] { background: #FFF8F8; border-color: #FEE2E2; }
            QLabel#comparisonBuild { color: #10213D; font-size: 18px; font-weight: 700; }
            QLabel#comparisonMetadata { color: #53657D; line-height: 1.4; }
            QLabel#comparisonSection { color: #13243B; font-size: 14px; font-weight: 700; margin-top: 8px; }
            QLabel#comparisonText { background: rgba(255,255,255,180); color: #34465D; border: 1px solid #E2E8F0; border-radius: 7px; padding: 9px; }
            QLabel#comparisonStatus { color: #6C7C93; }
        """)

        self.worker = ComparisonDetailsWorker(records, self)
        self.worker.loaded.connect(self._details_loaded)
        self.worker.failed.connect(self._details_failed)
        self.worker.start()

    @staticmethod
    def _format_items(items: list[str], empty_message: str) -> str:
        cleaned = [item.strip() for item in items if item and item.strip()]
        return "\n\n".join(f"• {item}" for item in cleaned) if cleaned else empty_message

    def _details_loaded(self, result) -> None:
        for key, details in dict(result or {}).items():
            labels = self.detail_labels.get(key)
            if not labels:
                continue
            labels["added_features"].setText(self._format_items(details.added_features, "Bu build için eklenen özellik bilgisi bulunamadı."))
            labels["fixed_issues"].setText(self._format_items(details.fixed_issues, "Kaynakta yapılandırılmış düzeltme bilgisi bulunamadı."))
            labels["known_issues"].setText(self._format_items(details.known_issues, "Kaynakta yayımlanmış bilinen sorun bilgisi bulunamadı."))
        self.status.setText("Karşılaştırma tamamlandı. Bilgiler ilgili makale ve resmî kaynaklardan alınmıştır.")

    def _details_failed(self, message: str) -> None:
        for labels in self.detail_labels.values():
            for label in labels.values():
                label.setText("Değişiklik ayrıntıları alınamadı.")
        self.status.setText(f"Kaynak bilgileri alınamadı: {message}")


class ChannelRowDelegate(QStyledItemDelegate):
    """Windows/Qt temasından bağımsız olarak satırları kanal rengiyle çizer."""

    def paint(self, painter, option, index) -> None:
        record = index.data(Qt.UserRole)
        channel = record.channel if isinstance(record, BuildTrackerRecord) else ""
        surface, accent = CHANNEL_COLORS[_channel_style_key(channel)]
        background = QColor(surface)
        if option.state & QStyle.State_Selected:
            # Kanal rengini koruyarak seçili satırı bir ton belirginleştir.
            tint = QColor(accent)
            background.setRed((background.red() * 88 + tint.red() * 12) // 100)
            background.setGreen((background.green() * 88 + tint.green() * 12) // 100)
            background.setBlue((background.blue() * 88 + tint.blue() * 12) // 100)

        # super().paint kullanılmıyor. Windows native/QSS stil motoru item arka
        # planını yeniden beyaza boyadığı için tüm hücreyi doğrudan çiziyoruz.
        painter.save()
        painter.fillRect(option.rect, background)

        separator = QColor(accent)
        separator.setAlpha(30)
        painter.setPen(separator)
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())

        text_color = QColor(accent) if index.column() in (4, 5) else QColor("#243750")
        painter.setPen(text_color)
        painter.setFont(option.font)
        text_rect = option.rect.adjusted(10, 0, -8, 0)
        text = option.fontMetrics.elidedText(
            str(index.data(Qt.DisplayRole) or ""),
            Qt.ElideRight,
            max(1, text_rect.width()),
        )
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()


_KIND_PILL = {
    "security": ("#E6F0FF", "#1768E0"),
    "preview": ("#F3E8FF", "#8B3FD9"),
    "insider": ("#EDE8FF", "#6744C6"),
    "neutral": ("#EDF2F8", "#53657D"),
}
_CHANNEL_PILL = {
    "retail": ("#E6F0FF", "#1D4ED8"),
    "release-preview": ("#FFEFD6", "#C2680C"),
    "beta": ("#E3F6EA", "#15803D"),
    "experimental": ("#F3E8FF", "#7C3AED"),
    "dev": ("#E6F0FF", "#1D4ED8"),
    "canary": ("#FEECEC", "#DC2626"),
    "neutral": ("#EDF2F8", "#53657D"),
}


class TrackerRowDelegate(QStyledItemDelegate):
    """Yeni tasarım: Windows ikonu, rozetli Tür/Kanal sütunları ve sağda ok.
    Yalnızca çizimdir; hücre verileri ve seçim davranışı değişmez."""

    def paint(self, painter, option, index) -> None:
        record = index.data(Qt.UserRole)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#EAF2FE"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor("#F6F9FE"))
        else:
            painter.fillRect(rect, QColor("#FFFFFF"))
        painter.setPen(QColor("#EDF1F6"))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        text = str(index.data(Qt.DisplayRole) or "")
        col = index.column()
        painter.setFont(option.font)
        if col == 0:
            pix = icons.pixmap("windows-color", "#1768E0", 26)
            painter.drawPixmap(rect.left() + 8, rect.center().y() - 13, pix)
            painter.setPen(QColor("#1B3D73"))
            painter.drawText(rect.adjusted(46, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter, text)
        elif col in (4, 5) and isinstance(record, BuildTrackerRecord):
            if col == 4:
                bg, fg = _KIND_PILL[_kind_key(record)]
            else:
                bg, fg = _CHANNEL_PILL[_channel_style_key(record.channel)]
            font = option.font
            font.setBold(True)
            font.setPointSizeF(max(8.0, font.pointSizeF() - 0.5))
            painter.setFont(font)
            fm = QFontMetrics(font)
            width = fm.horizontalAdvance(text) + 24
            pill = QRectF(rect.left() + 8, rect.center().y() - 12, width, 24)
            path = QPainterPath()
            path.addRoundedRect(pill, 12, 12)
            painter.fillPath(path, QColor(bg))
            painter.setPen(QColor(fg))
            painter.drawText(pill, Qt.AlignCenter, text)
        else:
            painter.setPen(QColor("#2A3A5C"))
            elided = option.fontMetrics.elidedText(text, Qt.ElideRight, max(1, rect.width() - 16))
            painter.drawText(rect.adjusted(8, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, elided)
        if col == index.model().columnCount() - 1:
            chevron = icons.pixmap("chevron-right", "#4B5E7C", 16, stroke=2.2)
            painter.drawPixmap(rect.right() - 30, rect.center().y() - 8, chevron)
        painter.restore()


class FilterPopup(QFrame):
    """"Filtreler" açılır paneli: mimari ve güncelleme türü onay kutularını barındırır."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("filterPopup")
        self.setStyleSheet(
            styles.qss("QFrame#filterPopup { background: #FFFFFF; border: 1px solid #D5E0EE; border-radius: 12px; }"
            "QLabel { color: #53657D; font-size: 11px; font-weight: 700; background: transparent; }"
            "QCheckBox { color: #243750; font-size: 13px; spacing: 8px; background: transparent; }"
            "QPushButton { background: @BLUE@; color: white; border: none; border-radius: 9px;"
            " padding: 0 16px; font-weight: 600; min-height: 36px; max-height: 36px; }"
            "QPushButton:hover { background: #135BC4; }")
        )
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 14, 16, 14)
        self.box.setSpacing(8)


class BuildTrackerTable(QTableWidget):
    """Build Tracker tablosu için yerleşik Qt sağ tık menüsü.

    QTableWidget bir QAbstractItemView olduğu için gerçek fare olayları viewport
    üzerinde oluşur. Bu nedenle ActionsContextMenu politikası doğrudan viewport'a
    uygulanır; menüyü Qt'nin kendisi oluşturup açar.
    """

    copy_kb_requested = Signal(int)
    copy_build_requested = Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.copy_kb_action = QAction("KB Numarasını Kopyala", self)
        self.copy_build_action = QAction("Build Numarasını Kopyala", self)
        self.copy_kb_action.triggered.connect(
            lambda _checked=False: self.copy_kb_requested.emit(self.currentRow())
        )
        self.copy_build_action.triggered.connect(
            lambda _checked=False: self.copy_build_requested.emit(self.currentRow())
        )

        # Sağ tık olayını alan gerçek widget viewport'tur. Qt'nin kendi
        # ActionsContextMenu mekanizması kullanıldığı için özel QMenu/eventFilter
        # koduna ihtiyaç yoktur.
        self.viewport().setContextMenuPolicy(Qt.ActionsContextMenu)
        self.viewport().addAction(self.copy_kb_action)
        self.viewport().addAction(self.copy_build_action)

        # Klavye Menü tuşu gibi durumlarda da tablo üzerinde aynı eylemler hazır olsun.
        self.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.addAction(self.copy_kb_action)
        self.addAction(self.copy_build_action)

        self._update_context_actions(-1)

    def _update_context_actions(self, row: int) -> None:
        kb_item = self.item(row, 0) if row >= 0 else None
        build_item = self.item(row, 2) if row >= 0 else None
        kb_value = (kb_item.text() if kb_item else "").strip()
        build_value = (build_item.text() if build_item else "").strip()
        self.copy_kb_action.setEnabled(bool(kb_value and kb_value != "—"))
        self.copy_build_action.setEnabled(bool(build_value and build_value != "—"))

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                row = item.row()
                self.setCurrentCell(row, item.column())
                self.selectRow(row)
                self._update_context_actions(row)
            else:
                self._update_context_actions(-1)
        super().mousePressEvent(event)


class KbUpdatesPage(QWidget):
    new_records_found = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[BuildTrackerRecord] = []
        self.filtered_records: list[BuildTrackerRecord] = []
        self.selected_record: BuildTrackerRecord | None = None
        self.last_update = ""
        self.worker: TrackerFetchWorker | None = None
        self._comparison_dialog: BuildComparisonDialog | None = None
        self._build_ui()
        self._apply_styles()

        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.timeout.connect(self.refresh)
        self.apply_settings(SettingsService.load())

        # Önbelleği anında göster; canlı kontrol ayarlardaki tercihe göre yapılır.
        self._load_cache_then_refresh()

    def _field_box(self, caption: str, combo) -> QFrame:
        box = QFrame()
        box.setObjectName("fldBox")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 7, 8, 5)
        lay.setSpacing(0)
        cap = QLabel(caption)
        cap.setObjectName("fldCaption")
        lay.addWidget(cap)
        combo.setMinimumWidth(110)
        lay.addWidget(combo)
        box.setMinimumHeight(56)
        box.setMaximumHeight(56)
        return box

    @staticmethod
    def _icon_btn_icon(name: str, color: str, size: int = 36) -> QIcon:
        return QIcon(icons.pixmap(name, color, size, stroke=2.0))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 22)
        root.setSpacing(14)

        # ── Başlık ──
        header = QHBoxLayout()
        header.setSpacing(14)
        tile = QLabel()
        tile.setObjectName("trkTile")
        tile.setFixedSize(60, 60)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap("windows-color", "#1768E0", 38))
        header.addWidget(tile, 0, Qt.AlignTop)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Windows Sürüm Takibi")
        title.setObjectName("trkTitle")
        subtitle = QLabel(
            "Windows sürümlerini ve build numaralarını izleyin, yeni yayınları takip edin."
        )
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        refresh_box = QVBoxLayout()
        refresh_box.setContentsMargins(0, 0, 0, 0)
        refresh_box.setSpacing(4)
        self.refresh_button = QPushButton("  Şimdi Güncelle")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.setIcon(self._icon_btn_icon("refresh", "#1768E0"))
        self.refresh_button.setIconSize(QSize(17, 17))
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self._manual_refresh)
        refresh_box.addWidget(self.refresh_button, 0, Qt.AlignRight)

        self.freshness = QLabel("Son güncelleme: —")
        self.freshness.setObjectName("freshnessInfo")
        self.freshness.setMinimumWidth(260)  # sağa yaslı kısa metin kırpılmasın
        self.freshness.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.freshness.setToolTip(
            "Kaynak: https://bunyaminkaya.com/windows-build-tracker/\n"
            "Program açılışında ve her saat otomatik olarak kontrol edilir."
        )
        refresh_box.addWidget(self.freshness, 0, Qt.AlignRight)
        header.addLayout(refresh_box)
        root.addLayout(header)

        # ── Arama satırı ──
        search_row = QHBoxLayout()
        search_row.setSpacing(12)
        self.search = QLineEdit()
        self.search.setObjectName("filterSearch")
        self.search.setPlaceholderText("Build veya KB arayın...")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(self._icon_btn_icon("search", "#4B5E7C"), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self.apply_filters)
        search_row.addWidget(self.search, 1)
        self.search_button = QPushButton("  Ara")
        self.search_button.setObjectName("primaryButton")
        self.search_button.setIcon(self._icon_btn_icon("search", "#FFFFFF"))
        self.search_button.setIconSize(QSize(18, 18))
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.setMinimumWidth(98)
        self.search_button.clicked.connect(self.apply_filters)
        search_row.addWidget(self.search_button)
        root.addLayout(search_row)

        # Bu bilgisayarın build'i ile en yeni yayının karşılaştırması (yalnızca bilgi).
        self.local_strip = QLabel("")
        self.local_strip.setObjectName("localBuildStrip")
        self.local_strip.setWordWrap(True)
        self.local_strip.setVisible(False)
        root.addWidget(self.local_strip)

        # Mockup'ta yer almayan ama çalışmaya devam eden "Yeni Güncellemeler" paneli (gizli).
        latest_box = QFrame()
        latest_box.setObjectName("latestPanel")
        latest_layout = QVBoxLayout(latest_box)
        latest_header = QHBoxLayout()
        latest_title = QLabel("Yeni Güncellemeler")
        self.latest_count = QLabel("Son yayınlanan build kayıtları")
        latest_header.addWidget(latest_title)
        latest_header.addWidget(self.latest_count)
        latest_layout.addLayout(latest_header)
        self.latest_cards_layout = QHBoxLayout()
        latest_layout.addLayout(self.latest_cards_layout)
        latest_box.setVisible(False)
        root.addWidget(latest_box)

        # ── Filtre çubuğu ──
        bar = QFrame()
        bar.setObjectName("filterBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(12)

        self.filters_button = QPushButton("  Filtreler")
        self.filters_button.setObjectName("filtersButton")
        self.filters_button.setIcon(self._icon_btn_icon("sliders", "#1768E0"))
        self.filters_button.setIconSize(QSize(20, 20))
        self.filters_button.setCursor(Qt.PointingHandCursor)
        self.filters_button.setFixedHeight(56)
        self.filters_button.clicked.connect(self._show_filter_popup)
        bl.addWidget(self.filters_button)
        chev = QLabel()
        chev.setPixmap(icons.pixmap("chevron-down", "#4B5E7C", 14, stroke=2.2))
        chev.setStyleSheet("background: transparent;")
        bl.addWidget(chev)

        self.version_combo = ModernComboBox()
        self.version_combo.addItems(["Tümü", "26H2", "26H1", "25H2", "24H2", "23H2", "Future Platforms"])
        self.version_combo.currentTextChanged.connect(self.apply_filters)
        bl.addWidget(self._field_box("Windows Sürümü", self.version_combo), 1)

        self.build_combo = ModernComboBox()
        self.build_combo.addItems(["Tümü"])
        self.build_combo.currentTextChanged.connect(self.apply_filters)
        bl.addWidget(self._field_box("Build", self.build_combo), 1)

        self.channel_combo = ModernComboBox()
        self.channel_combo.addItems(["Tümü"])
        self.channel_combo.currentTextChanged.connect(self.apply_filters)
        bl.addWidget(self._field_box("Kanal", self.channel_combo), 1)

        self.date_combo = ModernComboBox()
        self.date_combo.addItems(["Tümü", "Son 30 gün", "Son 90 gün", "Bu yıl"])
        self.date_combo.currentTextChanged.connect(self.apply_filters)
        bl.addWidget(self._field_box("Yayın Tarihi", self.date_combo), 1)

        self.list_view_button = QPushButton("  Liste")
        self.card_view_button = QPushButton("  Kart")
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for b in (self.list_view_button, self.card_view_button):
            b.setObjectName("trkViewButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(18, 18))
            b.setFixedHeight(46)
            b.setMinimumWidth(84)
            self._view_group.addButton(b)
            bl.addWidget(b)
        self.list_view_button.setChecked(True)
        self.list_view_button.clicked.connect(lambda: self._set_view_mode(False))
        self.card_view_button.clicked.connect(lambda: self._set_view_mode(True))
        self._set_view_icons(False)

        clear = QPushButton("  Temizle")
        clear.setObjectName("trkClearButton")
        clear.setIcon(self._icon_btn_icon("x", "#7C8BA5"))
        clear.setIconSize(QSize(16, 16))
        clear.setCursor(Qt.PointingHandCursor)
        clear.setFixedHeight(46)
        clear.setMinimumWidth(104)
        clear.clicked.connect(self._clear_filters)
        bl.addWidget(clear)
        root.addWidget(bar)

        # ── Filtreler açılır paneli (mimari / tür) ──
        self._filter_popup = FilterPopup(self)
        pl = self._filter_popup.box
        pl.addWidget(self._small_label("Mimari"))
        self.arch_x64 = QCheckBox("x64")
        self.arch_x64.setChecked(True)
        self.arch_arm64 = QCheckBox("ARM64")
        self.arch_arm64.setChecked(True)
        self.arch_x64.stateChanged.connect(self.apply_filters)
        self.arch_arm64.stateChanged.connect(self.apply_filters)
        pl.addWidget(self.arch_x64)
        pl.addWidget(self.arch_arm64)
        pl.addWidget(self._small_label("Güncelleme Türü"))
        self.type_security = QCheckBox("GA / Retail")
        self.type_preview = QCheckBox("Önizleme / Beta")
        self.type_insider = QCheckBox("Dev / Canary / Insider")
        for cb in (self.type_security, self.type_preview, self.type_insider):
            cb.setChecked(True)
            cb.stateChanged.connect(self.apply_filters)
            pl.addWidget(cb)
        self.apply_button = QPushButton("Filtreleri Uygula")
        self.apply_button.clicked.connect(self.apply_filters)
        pl.addWidget(self.apply_button)

        # ── Gövde ──
        body = QHBoxLayout()
        body.setSpacing(14)

        center = QFrame()
        center.setObjectName("listPanel")
        cp = QVBoxLayout(center)
        cp.setContentsMargins(0, 0, 0, 0)
        cp.setSpacing(0)

        list_header = QHBoxLayout()
        list_header.setContentsMargins(18, 14, 18, 8)
        list_header.setSpacing(10)
        hicon = QLabel()
        hicon.setPixmap(icons.pixmap("search", "#1768E0", 20, stroke=2.2))
        hicon.setStyleSheet("background: transparent;")
        list_header.addWidget(hicon)
        self.result_info = QLabel("Kayıtlar yükleniyor...")
        self.result_info.setObjectName("resultInfo")
        list_header.addWidget(self.result_info)
        list_header.addStretch()
        self.compare_button = QPushButton("Karşılaştırma için 2 veya 3 Build Seç")
        self.compare_button.setObjectName("trkCompareButton")
        self.compare_button.setEnabled(False)
        self.compare_button.setToolTip("Ctrl tuşuna basılı tutarak tablodan iki veya üç satır seçin.")
        self.compare_button.setCursor(Qt.PointingHandCursor)
        self.compare_button.clicked.connect(self._open_comparison)
        list_header.addWidget(self.compare_button)
        # Sıralama artık sütun başlıklarından yapılır; birleşik kutu mantık için gizli kalır.
        self.sort_combo = ModernComboBox()
        self.sort_combo.addItems(["Sıralama: Yayın Tarihi (En Yeni)", "Sıralama: Build (Yüksek)", "Sıralama: KB Numarası"])
        self.sort_combo.currentTextChanged.connect(self.apply_filters)
        self.sort_combo.currentTextChanged.connect(self._sync_sort_indicator)
        self.sort_combo.setVisible(False)
        list_header.addWidget(self.sort_combo)
        cp.addLayout(list_header)

        self.table = BuildTrackerTable(0, 6)
        self.table.setObjectName("buildTable")
        self.table.setHorizontalHeaderLabels(["KB Numarası", "Windows Sürümü", "Build No", "Yayın Tarihi", "Tür", "Kanal"])
        from ui.widgets.empty_state import attach_empty_state
        self._empty = attach_empty_state(self.table, "monitor", self._empty_text)
        self._empty.clicked.connect(self._empty_action)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setItemDelegate(TrackerRowDelegate(self.table))
        self.table.verticalHeader().setVisible(False)
        table_header = self.table.horizontalHeader()
        table_header.setStretchLastSection(False)
        table_header.setDefaultAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        table_header.setSectionsClickable(True)
        table_header.setSortIndicatorShown(True)
        table_header.setSectionResizeMode(0, QHeaderView.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.Fixed)
        table_header.setSectionResizeMode(3, QHeaderView.Fixed)
        table_header.setSectionResizeMode(4, QHeaderView.Fixed)
        table_header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(2, 112)
        self.table.setColumnWidth(3, 104)
        self.table.setColumnWidth(4, 108)
        self.table.setColumnWidth(5, 168)
        table_header.sectionClicked.connect(self._header_clicked)
        self.table.cellClicked.connect(self._table_clicked)
        self.table.itemSelectionChanged.connect(self._update_compare_button)

        # Qt'nin viewport üzerindeki yerleşik ActionsContextMenu sistemi.
        self.table.copy_kb_requested.connect(self._copy_kb_from_row)
        self.table.copy_build_requested.connect(self._copy_build_from_row)

        # Kart görünümü: aynı kayıtları NewUpdateCard kartlarıyla gösterir.
        self.card_scroll = QScrollArea()
        self.card_scroll.setObjectName("trkCardScroll")
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.NoFrame)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_host = QWidget()
        self.card_host.setObjectName("trkCardHost")
        self.card_grid = QGridLayout(self.card_host)
        self.card_grid.setContentsMargins(16, 6, 16, 16)
        self.card_grid.setSpacing(12)
        self.card_scroll.setWidget(self.card_host)
        self._card_mode = False

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.table)
        self.view_stack.addWidget(self.card_scroll)
        cp.addWidget(self.view_stack, 1)

        # Takip listesi özeti (işlev korunur; kartın altında ince şerit).
        self.watch_summary = QLabel("Takip listesi yükleniyor...")
        self.watch_summary.setObjectName("watchSummary")
        self.watch_summary.setWordWrap(True)
        cp.addWidget(self.watch_summary)
        body.addWidget(center, 1)

        # ── Sağ: Build Hakkında ──
        details = QFrame()
        details.setObjectName("detailsPanel")
        details.setFixedWidth(350)
        dp = QVBoxLayout(details)
        dp.setContentsMargins(18, 16, 18, 16)
        dp.setSpacing(10)

        dh = QHBoxLayout()
        dh.setSpacing(10)
        dicon = QLabel()
        dicon.setPixmap(icons.pixmap("windows-color", "#1768E0", 22))
        dicon.setStyleSheet("background: transparent;")
        dh.addWidget(dicon)
        dtitle = QLabel("Build Hakkında")
        dtitle.setObjectName("sectionTitle")
        dh.addWidget(dtitle, 1)
        dp.addLayout(dh)

        self.detail_title = QLabel("Bir güncelleme seçin")
        self.detail_title.setObjectName("detailTitle")
        self.detail_badge = QLabel("")
        self.detail_badge.setObjectName("updateKindBadge")
        detail_head = QHBoxLayout()
        detail_head.addWidget(self.detail_title, 1)
        detail_head.addWidget(self.detail_badge, 0, Qt.AlignVCenter)
        dp.addLayout(detail_head)

        self.detail_grid = QVBoxLayout()
        self.detail_grid.setSpacing(6)
        self.detail_labels: dict[str, QLabel] = {}
        for key, caption in (
            ("version", "Windows Sürümü"),
            ("build", "Build"),
            ("date", "Yayın Tarihi"),
            ("channel", "Kanal"),
            ("group", "Yayın Grubu"),
            ("kb", "KB Numarası"),
        ):
            row = QHBoxLayout()
            left = QLabel(caption)
            left.setObjectName("detailKey")
            value = QLabel("—")
            value.setObjectName("detailValue")
            value.setWordWrap(True)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(left)
            row.addStretch()
            row.addWidget(value)
            self.detail_grid.addLayout(row)
            self.detail_labels[key] = value
        dp.addLayout(self.detail_grid)

        sep = QFrame()
        sep.setObjectName("softSeparator")
        sep.setFrameShape(QFrame.HLine)
        dp.addWidget(sep)

        description_title = QLabel("Açıklama")
        description_title.setObjectName("panelTitle")
        self.detail_description = QLabel("Seçilen build kaydının açıklaması burada gösterilir.")
        self.detail_description.setObjectName("detailDescription")
        self.detail_description.setWordWrap(True)
        dp.addWidget(description_title)
        dp.addWidget(self.detail_description)

        article_title = QLabel("İlgili İçerik")
        article_title.setObjectName("panelTitle")
        self.article_link = QPushButton("İlgili yazıyı aç")
        self.article_link.setObjectName("secondaryButton")
        self.article_link.clicked.connect(self._open_article)
        dp.addWidget(article_title)
        dp.addWidget(self.article_link)

        self.known_issues_button = QPushButton("Bilinen Sorunları Gör")
        self.known_issues_button.setObjectName("secondaryButton")
        self.known_issues_button.setToolTip("Seçili build için Microsoft'un yayımladığı bilinen sorunları gösterir.")
        self.known_issues_button.clicked.connect(self._open_known_issues)
        dp.addWidget(self.known_issues_button)

        actions_title = QLabel("İşlemler")
        actions_title.setObjectName("panelTitle")
        dp.addWidget(actions_title)
        self.package_button = QPushButton("Microsoft Paketlerini Aç")
        self.package_button.setObjectName("primaryButton")
        self.package_button.clicked.connect(self._open_microsoft)
        dp.addWidget(self.package_button)

        dp.addStretch()
        note_row = QFrame()
        note_row.setObjectName("infoNote")
        nr = QHBoxLayout(note_row)
        nr.setContentsMargins(12, 10, 12, 10)
        nr.setSpacing(10)
        nicon = QLabel()
        nicon.setPixmap(icons.pixmap("info-fill", "#1768E0", 18))
        nicon.setStyleSheet("background: transparent; border: none;")
        nr.addWidget(nicon, 0, Qt.AlignTop)
        note = QLabel("İndirme işlemleri Microsoft'un resmi kaynakları üzerinden gerçekleştirilir.")
        note.setObjectName("infoNoteText")
        note.setWordWrap(True)
        nr.addWidget(note, 1)
        dp.addWidget(note_row)
        body.addWidget(details)

        root.addLayout(body, 1)
        self._sync_sort_indicator()

    # ── Yalnızca görünüm yardımcıları ──
    def _show_filter_popup(self) -> None:
        popup = self._filter_popup
        popup.adjustSize()
        popup.move(self.filters_button.mapToGlobal(self.filters_button.rect().bottomLeft()) + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(0, 6))
        popup.show()

    def _set_view_icons(self, card_mode: bool) -> None:
        self.list_view_button.setIcon(self._icon_btn_icon("list", "#4B5E7C" if card_mode else "#FFFFFF"))
        self.card_view_button.setIcon(self._icon_btn_icon("boxes", "#FFFFFF" if card_mode else "#4B5E7C"))

    def _set_view_mode(self, card_mode: bool) -> None:
        self._card_mode = bool(card_mode)
        self._set_view_icons(self._card_mode)
        self.view_stack.setCurrentIndex(1 if self._card_mode else 0)
        if self._card_mode:
            self._render_cards(self.filtered_records)

    def _render_cards(self, rows) -> None:
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for idx, record in enumerate(rows):
            card = NewUpdateCard(record)
            card.clicked.connect(self._select_record)
            self.card_grid.addWidget(card, idx // 2, idx % 2)
        self.card_grid.setRowStretch((len(rows) + 1) // 2, 1)
        self.card_grid.setColumnStretch(0, 1)
        self.card_grid.setColumnStretch(1, 1)

    _SORT_BY_COLUMN = {3: 0, 2: 1, 0: 2}

    def _header_clicked(self, column: int) -> None:
        index = self._SORT_BY_COLUMN.get(column)
        if index is not None:
            self.sort_combo.setCurrentIndex(index)

    def _sync_sort_indicator(self, *_args) -> None:
        column = {0: 3, 1: 2, 2: 0}.get(self.sort_combo.currentIndex(), 3)
        self.table.horizontalHeader().setSortIndicator(column, Qt.DescendingOrder)

    def _refresh_dynamic_filters(self) -> None:
        builds = sorted({(r.build_number or "").split(".")[0] for r in self.records if r.build_number}, key=lambda v: (len(v), v), reverse=True)
        channels = sorted({r.channel for r in self.records if r.channel})
        key = (tuple(builds), tuple(channels))
        if key == getattr(self, "_dynamic_key", None):
            return
        self._dynamic_key = key
        for combo, values in ((self.build_combo, builds), (self.channel_combo, channels)):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(["Tümü"] + values)
            combo.setCurrentIndex(max(0, combo.findText(current)))
            combo.blockSignals(False)

    @staticmethod
    def _small_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("filterLabel")
        return label

    def _load_cache_then_refresh(self) -> None:
        records, last_update, fetched_at = BuildTrackerService.load_cache()
        if records:
            self.records = records
            self.last_update = last_update
            self._update_freshness(fetched_at)
            self.apply_filters()
            self._update_local_strip()
        settings = SettingsService.load()
        general = settings.get("general", {})
        tracker = settings.get("build_tracker", {})
        if general.get("check_tracker_on_start", True) and tracker.get("refresh_on_start", True):
            self.refresh()

    def _empty_text(self):
        if self.worker is not None and self.worker.isRunning():
            return ("Kayıtlar yükleniyor…", "Build Tracker kaynağından güncel kayıtlar alınıyor.", None)
        if not self.records:
            if getattr(self, "_last_error", ""):
                return ("Build kayıtları alınamadı", "İnternet bağlantınızı kontrol edip yeniden deneyin. Ayrıntı için “Güncelleme başarısız” yazısının üzerine gelin.", "Şimdi Güncelle")
            return ("Henüz build kaydı yok", "Kayıtlar alınamadı ya da henüz yüklenmedi. Şimdi güncelleyerek yeniden deneyin.", "Şimdi Güncelle")
        return ("Bu filtrede kayıt yok", "Süzgeçleri değiştirmeyi veya temizlemeyi deneyin.", "Filtreleri Temizle")

    def _empty_action(self) -> None:
        if self.records:
            self._clear_filters()
        else:
            self._manual_refresh()

    def _manual_refresh(self) -> None:
        """Kullanıcı isteğiyle yenileme: hata olursa kısa bir uyarı penceresi gösterilir."""
        self._show_error_dialog = True
        self.refresh()

    def _update_local_strip(self) -> None:
        """Bu bilgisayardaki build ile kayıtlardaki en yeni yayını karşılaştırır (salt okunur)."""
        try:
            if not hasattr(self, "_local_build"):
                self._local_build = LocalBuildService.current()
            local = self._local_build
            info = LocalBuildService.compare(self.records, local)
            status = info.get("status")
            if local is None or status == "unknown":
                self.local_strip.setVisible(False)
                return
            name = f"{local.product} {local.display_version}".strip()
            latest = info["latest"]
            if status == "latest":
                text = f"Bu bilgisayar: {name} • Build {local.full} — güncel görünüyor (en yeni yayın {latest.build_number})."
            else:
                kb = f" ({latest.kb_number})" if latest.kb_number else ""
                text = (f"Bu bilgisayar: {name} • Build {local.full} — en yeni yayın {latest.build_number}{kb}; "
                        f"{info['behind']} yayın geride.")
            self.local_strip.setText(text)
            self.local_strip.setProperty("state", status)
            self.local_strip.style().unpolish(self.local_strip)
            self.local_strip.style().polish(self.local_strip)
            self.local_strip.setVisible(True)
        except Exception:
            self.local_strip.setVisible(False)

    def apply_settings(self, settings) -> None:
        tracker = dict((settings or {}).get("build_tracker", {}))
        self.watch_summary.setText("Takip Listesi: " + BuildWatchService.summary(tracker))
        self.watch_summary.setProperty("active", bool(tracker.get("watchlist_enabled", False)))
        self.watch_summary.style().unpolish(self.watch_summary)
        self.watch_summary.style().polish(self.watch_summary)
        minutes = int(tracker.get("refresh_interval_minutes", 60) or 60)
        minutes = max(30, minutes)
        self.auto_refresh_timer.setInterval(minutes * 60 * 1000)
        if not self.auto_refresh_timer.isActive():
            self.auto_refresh_timer.start()

    def refresh(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("  Güncelleniyor...")
        self.worker = TrackerFetchWorker(self)
        self.worker.loaded.connect(self._on_loaded)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_loaded(self, records, last_update: str) -> None:
        previous = {
            (r.build_number, r.windows_version, r.channel, r.release_date)
            for r in self.records
        }
        incoming = list(records)
        new_records = [
            record for record in incoming
            if (record.build_number, record.windows_version, record.channel, record.release_date)
            not in previous
        ] if previous else []
        self.records = incoming
        self._last_error = ""
        self.last_update = last_update
        self._update_freshness(datetime.now().isoformat(timespec="seconds"))
        self.freshness.setToolTip(
            "Canlı kontrol tamamlandı. "
            + (f"{len(set((r.build_number, r.windows_version, r.channel, r.release_date) for r in self.records) - previous)} yeni kayıt alındı.\n" if previous else "Kayıtlar canlı kaynaktan alındı.\n")
            + "Kaynak: https://bunyaminkaya.com/windows-build-tracker/"
        )
        self.apply_filters()
        self._update_local_strip()
        BuildHistoryService.record_success(self.records, new_records, last_update)
        if new_records:
            self.new_records_found.emit(new_records)

    def select_record(self, record: BuildTrackerRecord) -> None:
        """Bildirim tıklandığında ilgili kaydı görünür ve seçili hale getirir."""
        self.search.clear()
        self.version_combo.setCurrentIndex(0)
        self.date_combo.setCurrentIndex(0)
        self.build_combo.setCurrentIndex(0)
        self.channel_combo.setCurrentIndex(0)
        self.apply_filters()
        target = (record.build_number, record.windows_version, record.channel, record.release_date)
        for row in range(self.table.rowCount()):
            current = self._record_for_row(row)
            if current and (current.build_number, current.windows_version, current.channel, current.release_date) == target:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0), QAbstractItemView.PositionAtCenter)
                self._select_record(current)
                break

    def _on_failed(self, message: str) -> None:
        BuildHistoryService.record_failure(message)
        manual = getattr(self, "_show_error_dialog", False)
        self._show_error_dialog = False
        self._last_error = message
        if not self.records:
            # Açılışta pencere açılmaz: boş durum ekranı kısa açıklama ve yeniden deneme düğmesi verir.
            self.freshness.setToolTip("Canlı güncelleme alınamadı.\n" + message)
            self.freshness.setText("Güncelleme başarısız")
            self.result_info.setText("Kayıtlar alınamadı")
            if manual:
                show_error(self, "Windows Sürüm Takibi",
                           "Build kayıtları alınamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.\n\nAyrıntı: " + message[:300])
            try:
                self._empty._sync()
            except Exception:
                pass
        else:
            # Son başarılı güncelleme zamanı ekranda kalır; mevcut önbellek kullanılmaya devam eder.
            self.freshness.setToolTip(
                "Canlı güncelleme alınamadı. Son başarılı veriler gösteriliyor.\n" + message
            )
            self.freshness.setText("Güncelleme başarısız — önbellek gösteriliyor")

    def _on_finished(self) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("  Şimdi Güncelle")

    def _combo_value(self, text: str) -> str:
        return text.split(": ", 1)[1] if ": " in text else text

    def _update_freshness(self, fetched_at: str) -> None:
        stamp = ""
        if fetched_at:
            try:
                stamp = datetime.fromisoformat(fetched_at).strftime("%d.%m.%Y %H:%M")
            except Exception:
                stamp = fetched_at

        if stamp:
            self.freshness.setText(f"Son güncelleme: {stamp}")
        else:
            self.freshness.setText("Son güncelleme: —")

    def _clear_filters(self) -> None:
        self.search.clear()
        self.version_combo.setCurrentIndex(0)
        self.date_combo.setCurrentIndex(0)
        self.build_combo.setCurrentIndex(0)
        self.channel_combo.setCurrentIndex(0)
        self.arch_x64.setChecked(True)
        self.arch_arm64.setChecked(True)
        self.type_security.setChecked(True)
        self.type_preview.setChecked(True)
        self.type_insider.setChecked(True)
        self.apply_filters()

    def apply_filters(self, *_args) -> None:
        self._refresh_dynamic_filters()
        text = self.search.text().strip().lower()
        build_filter = self._combo_value(self.build_combo.currentText())
        channel_filter = self._combo_value(self.channel_combo.currentText())
        version = self._combo_value(self.version_combo.currentText())
        date_filter = self._combo_value(self.date_combo.currentText())
        allowed_kinds = set()
        if self.type_security.isChecked():
            allowed_kinds.add("security")
        if self.type_preview.isChecked():
            allowed_kinds.add("preview")
        if self.type_insider.isChecked():
            allowed_kinds.add("insider")
        allowed_kinds.add("neutral")

        now = datetime.now()
        rows = []
        for record in self.records:
            if text and text not in record.search_text:
                continue
            if version != "Tümü" and (record.windows_version or "") != version:
                continue
            if build_filter != "Tümü" and (record.build_number or "").split(".")[0] != build_filter:
                continue
            if channel_filter != "Tümü" and (record.channel or "") != channel_filter:
                continue
            if _kind_key(record) not in allowed_kinds:
                continue
            if date_filter != "Tümü" and record.release_date:
                try:
                    dt = datetime.strptime(record.release_date, "%Y-%m-%d")
                    days = (now - dt).days
                    if date_filter == "Son 30 gün" and days > 30:
                        continue
                    if date_filter == "Son 90 gün" and days > 90:
                        continue
                    if date_filter == "Bu yıl" and dt.year != now.year:
                        continue
                except Exception:
                    pass
            rows.append(record)

        sort_mode = self._combo_value(self.sort_combo.currentText())
        if sort_mode == "Build (Yüksek)":
            def build_key(r):
                try:
                    return tuple(int(x) for x in r.build_number.split("."))
                except Exception:
                    return (0,)
            rows.sort(key=build_key, reverse=True)
        elif sort_mode == "KB Numarası":
            rows.sort(key=lambda r: r.kb_number or "", reverse=True)
        else:
            rows.sort(key=lambda r: r.release_date or "", reverse=True)

        self.filtered_records = rows
        self._render_latest(rows)
        self._render_table(rows)

    def _render_latest(self, rows: list[BuildTrackerRecord]) -> None:
        while self.latest_cards_layout.count():
            item = self.latest_cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        latest = rows[:3]
        for record in latest:
            card = NewUpdateCard(record)
            card.clicked.connect(self._select_record)
            self.latest_cards_layout.addWidget(card, 1)
        if not latest:
            empty = QLabel("Filtrelere uygun yeni güncelleme bulunamadı.")
            empty.setObjectName("sectionHint")
            self.latest_cards_layout.addWidget(empty)
        self.latest_count.setText(f"{len(rows)} kayıt içinde en yeni {len(latest)} kayıt")

    def _render_table(self, rows: list[BuildTrackerRecord]) -> None:
        self.table.setRowCount(0)
        self.result_info.setText(f"Arama Sonuçları ({len(rows)})")
        for record in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                record.kb_number or "—",
                f"Windows 11 {record.windows_version or ''}".strip(),
                record.build_number,
                _display_date(record.release_date),
                _kind_text(record),
                record.channel or "—",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, record)
                _surface, accent = CHANNEL_COLORS[_channel_style_key(record.channel)]
                if col in (4, 5):
                    item.setForeground(QBrush(QColor(accent)))
                if col == 0:
                    item.setFont(self.table.font())
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 46)

        if rows:
            self.table.selectRow(0)
            self._select_record(rows[0])
        else:
            self._select_record(None)
        if self._card_mode:
            self._render_cards(rows)

    def _table_clicked(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        record = item.data(Qt.UserRole) if item else None
        if isinstance(record, BuildTrackerRecord):
            self._select_record(record)

    def _selected_comparison_records(self) -> list[BuildTrackerRecord]:
        records: list[BuildTrackerRecord] = []
        for model_index in self.table.selectionModel().selectedRows():
            record = self._record_for_row(model_index.row())
            if record is not None:
                records.append(record)
        return records

    def _update_compare_button(self) -> None:
        count = len(self._selected_comparison_records())
        self.compare_button.setEnabled(count in (2, 3))
        self.compare_button.setText(
            f"Seçilen {count} Build’i Karşılaştır" if count in (2, 3)
            else f"Karşılaştırma için 2 veya 3 Build Seç ({count}/3)"
        )

    def _open_comparison(self) -> None:
        records = self._selected_comparison_records()
        if len(records) not in (2, 3):
            show_information(
                self,
                "Build Karşılaştırma",
                "Ctrl tuşuna basılı tutarak tablodan iki veya üç build satırı seçin.",
            )
            return
        self._comparison_dialog = BuildComparisonDialog(records, self)
        self._comparison_dialog.exec()

    def _record_for_row(self, row: int) -> BuildTrackerRecord | None:
        if row < 0 or row >= self.table.rowCount():
            return None
        record_item = self.table.item(row, 0)
        record = record_item.data(Qt.UserRole) if record_item else None
        return record if isinstance(record, BuildTrackerRecord) else None

    def _copy_kb_from_row(self, row: int) -> None:
        record = self._record_for_row(row)
        if record is None:
            return
        value = (record.kb_number or "").strip()
        if value and value != "—":
            QApplication.clipboard().setText(value)

    def _copy_build_from_row(self, row: int) -> None:
        record = self._record_for_row(row)
        if record is None:
            return
        value = (record.build_number or "").strip()
        if value and value != "—":
            QApplication.clipboard().setText(value)

    def _select_record(self, record: BuildTrackerRecord | None) -> None:
        self.selected_record = record
        if record is None:
            self.detail_title.setText("Bir güncelleme seçin")
            self.detail_badge.setText("")
            for label in self.detail_labels.values():
                label.setText("—")
            self.detail_description.setText("Seçilen build kaydının açıklaması burada gösterilir.")
            self.article_link.setEnabled(False)
            self.known_issues_button.setEnabled(False)
            self.package_button.setEnabled(False)
            return

        self.detail_title.setText(f"Build {record.build_number}" if record.build_number else (record.kb_number or "—"))
        self.detail_badge.setText(_kind_text(record))
        self.detail_badge.setProperty("kind", _kind_key(record))
        self.detail_badge.setProperty("channelStyle", _channel_style_key(record.channel))
        self.detail_badge.style().unpolish(self.detail_badge)
        self.detail_badge.style().polish(self.detail_badge)
        self.detail_labels["version"].setText(f"Windows 11 {record.windows_version or '—'}")
        self.detail_labels["build"].setText(record.build_number or "—")
        self.detail_labels["date"].setText(_display_date(record.release_date))
        self.detail_labels["channel"].setText(record.channel or "—")
        self.detail_labels["group"].setText(record.release_group or "—")
        self.detail_labels["kb"].setText(record.kb_number or "—")
        self.detail_description.setText(record.description or "Bu build için açıklama bilgisi bulunmuyor.")
        self.article_link.setEnabled(bool(record.article_url))
        self.known_issues_button.setEnabled(bool(record.microsoft_url))
        self.package_button.setEnabled(bool(record.microsoft_url))

    def _open_known_issues(self) -> None:
        record = self.selected_record
        if not record or not record.microsoft_url:
            show_information(self, "Bilinen Sorunlar", "Bu build için Microsoft kaynak bağlantısı bulunmuyor.")
            return
        self._known_issues_dialog = KnownIssuesDialog(record, self)
        self._known_issues_dialog.exec()

    def _open_article(self) -> None:
        record = self.selected_record
        if not record or not record.article_url:
            show_information(self, "Windows Sürüm Takibi", "Bu kayıt için ilgili yazı bağlantısı bulunmuyor.")
            return
        QDesktopServices.openUrl(QUrl(record.article_url))

    def _open_microsoft(self) -> None:
        record = self.selected_record
        if not record or not record.microsoft_url:
            show_information(self, "Windows Sürüm Takibi", "Bu kayıt için Microsoft kaynak bağlantısı bulunmuyor.")
            return
        QDesktopServices.openUrl(QUrl(record.microsoft_url))

    def _sort_arrow_urls(self) -> tuple[str, str]:
        import os, tempfile
        out = []
        for name, flip in (("up", True), ("down", False)):
            try:
                pm = icons.pixmap("chevron-down", "#4B5E7C", 12, stroke=2.4)
                if flip:
                    pm = pm.transformed(QTransform().scale(1, -1))
                path = os.path.join(tempfile.gettempdir(), f"wubc_sort_{name}.png")
                pm.save(path, "PNG")
                out.append(path.replace("\\", "/"))
            except Exception:
                out.append("")
        return out[0], out[1]

    def _apply_styles(self) -> None:
        up_url, down_url = self._sort_arrow_urls()
        self.setStyleSheet(
            """
            QLabel { background: transparent; }
            QLabel#trkTile { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 16px; }
            QLabel#trkTitle { font-size: 30px; font-weight: 700; color: #0A1F44; }
            QLabel#freshnessInfo, QLabel#sectionHint { color: #7C8BA5; font-size: 11px; }
            QLabel#resultInfo { color: #14213D; font-size: 16px; font-weight: 700; }
            QLabel#watchSummary {
                background: #F6F9FE; color: #55708E; border: none; border-top: 1px solid #E3EAF4;
                border-bottom-left-radius: 14px; border-bottom-right-radius: 14px;
                padding: 8px 18px; font-size: 11px;
            }
            QLabel#localBuildStrip { background: #EAF2FE; color: #1D4F9E; border: 1px solid #CFE0FA; border-radius: 10px; padding: 9px 14px; font-size: 12px; font-weight: 600; }
            QLabel#localBuildStrip[state="latest"] { background: #EAF7EF; color: #247747; border-color: #CDEBD8; }
            QLabel#localBuildStrip[state="behind"] { background: #FFF6E5; color: #9A5B00; border-color: #F6DFAE; }
            QLabel#watchSummary[active="true"] { background: #EAF7EF; color: #247747; }
            QLabel#sectionTitle { font-weight: 700; color: #14213D; font-size: 16px; }
            QLabel#panelTitle { font-weight: 700; color: #14213D; font-size: 14px; }
            QFrame#listPanel, QFrame#detailsPanel, QFrame#filterBar {
                background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 14px;
            }
            QFrame#fldBox { background: #FFFFFF; border: 1px solid #DCE5F1; border-radius: 10px; }
            QFrame#fldBox:hover { border-color: #9DB9E6; }
            QLabel#fldCaption { color: #6C7C93; font-size: 10px; font-weight: 600; }
            QFrame#fldBox QComboBox#modernComboBox {
                background: transparent; border: none; padding: 0 22px 0 0;
                font-size: 13px; font-weight: 600; color: #14213D; min-height: 22px; max-height: 22px;
            }
            QPushButton#filtersButton {
                background: transparent; border: none; color: #14213D; font-size: 14px; font-weight: 700;
                padding: 0 4px 0 8px; text-align: left;
            }
            QPushButton#trkViewButton {
                background: #FFFFFF; color: #3A4D70; border: 1px solid #D5E0EE; border-radius: 10px;
                padding: 0 14px; font-size: 13px; font-weight: 600;
            }
            QPushButton#trkViewButton:checked { background: #1768E0; color: #FFFFFF; border: 1px solid #1768E0; }
            QPushButton#trkViewButton:hover:!checked { background: #F1F6FD; }
            QPushButton#trkClearButton {
                background: #FFFFFF; color: #6C7C93; border: 1px solid #E1E8F2; border-radius: 10px;
                padding: 0 14px; font-size: 13px; font-weight: 600;
            }
            QPushButton#trkClearButton:hover { background: #F6F9FE; color: #14213D; }
            QPushButton#trkCompareButton {
                background: #FFFFFF; color: #1768E0; border: 1px solid #CBD9EC; border-radius: 9px;
                padding: 0 12px; font-size: 12px; font-weight: 600; min-height: 34px; max-height: 34px;
            }
            QPushButton#trkCompareButton:hover { background: #F1F6FD; }
            QPushButton#trkCompareButton:disabled { color: #8A98B0; background: #F6F9FE; border: 1px solid #E1E8F2; }
            QFrame#newUpdateCard { background: #FFFFFF; border: 1px solid #DCE5F0; border-radius: 10px; }
            QFrame#newUpdateCard:hover { border-color: #77A7EE; background: #F8FBFF; }
            QFrame#newUpdateCard[channelStyle="retail"], QFrame#newUpdateCard[channelStyle="dev"] { background: #F7FAFF; border-color: #DBEAFE; }
            QFrame#newUpdateCard[channelStyle="release-preview"] { background: #FFFBF2; border-color: #FDE7B2; }
            QFrame#newUpdateCard[channelStyle="beta"] { background: #F5FCF7; border-color: #D6F1DE; }
            QFrame#newUpdateCard[channelStyle="experimental"] { background: #FAF7FF; border-color: #EADCFF; }
            QFrame#newUpdateCard[channelStyle="canary"] { background: #FFF8F8; border-color: #FEE2E2; }
            QLabel#windowsTileIcon { background: #EAF3FF; color: #2167D5; border-radius: 8px; font-size: 22px; font-weight: 700; }
            QLabel#newUpdateTitle { color: #10213D; font-weight: 700; font-size: 14px; }
            QLabel#newUpdateMeta { color: #53657D; font-size: 11px; }
            QLabel#newUpdateDate { color: #7E8EA3; font-size: 10px; }
            QLabel#updateKindBadge { padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 700; }
            QLabel#updateKindBadge[kind="security"] { background: #E6F0FF; color: #1768E0; }
            QLabel#updateKindBadge[kind="preview"] { background: #E3F6EA; color: #15803D; }
            QLabel#updateKindBadge[kind="insider"] { background: #EDE8FF; color: #6744C6; }
            QLabel#updateKindBadge[kind="neutral"] { background: #EDF2F8; color: #53657D; }
            QLabel#updateKindBadge[channelStyle="retail"], QLabel#updateKindBadge[channelStyle="dev"] { background: #E6F0FF; color: #1D4ED8; }
            QLabel#updateKindBadge[channelStyle="release-preview"] { background: #FFEFD6; color: #C2680C; }
            QLabel#updateKindBadge[channelStyle="beta"] { background: #E3F6EA; color: #15803D; }
            QLabel#updateKindBadge[channelStyle="experimental"] { background: #F3E8FF; color: #7C3AED; }
            QLabel#updateKindBadge[channelStyle="canary"] { background: #FEECEC; color: #DC2626; }
            QLabel#filterLabel { color: #53657D; font-size: 11px; font-weight: 600; margin-top: 4px; }
            QLineEdit#filterSearch {
                background: #FFFFFF; border: 1px solid #D0DCEC; border-radius: 12px;
                padding: 0 14px 0 6px; font-size: 14px; color: #14213D;
                min-height: 46px; max-height: 46px; selection-background-color: #1768E0;
            }
            QLineEdit#filterSearch:focus { border: 1px solid #1768E0; }
            QPushButton#primaryButton {
                background: #1768E0; color: white; border: none; border-radius: 12px;
                padding: 0 18px; font-size: 13px; font-weight: 700; min-height: 46px; max-height: 46px;
            }
            QPushButton#primaryButton:hover { background: #135BC4; }
            QPushButton#primaryButton:disabled { background: #A9C4EE; }
            QPushButton#secondaryButton {
                background: #FFFFFF; color: #1768E0; border: 1px solid #CBD9EC; border-radius: 12px;
                padding: 0 18px; font-size: 13px; font-weight: 600; min-height: 44px; max-height: 44px;
            }
            QPushButton#secondaryButton:hover { background: #F1F6FD; border-color: #9DB9E6; }
            QPushButton#secondaryButton:disabled { color: #8A98B0; background: #F6F9FE; border: 1px solid #E1E8F2; }
            QTableWidget#buildTable {
                background: #FFFFFF; border: none; gridline-color: transparent; outline: none;
                selection-background-color: #EAF2FE; selection-color: #10213D;
            }
            QTableWidget#buildTable QHeaderView::section {
                background: #F4F8FD; color: #3A4D70; border: none; padding: 11px 8px;
                font-size: 12px; font-weight: 700;
            }
            QTableWidget#buildTable QHeaderView::section:first { padding-left: 46px; }
            QTableWidget#buildTable QHeaderView::up-arrow { image: url(%UP%); width: 10px; height: 10px; }
            QTableWidget#buildTable QHeaderView::down-arrow { image: url(%DOWN%); width: 10px; height: 10px; }
            QScrollArea#trkCardScroll, QWidget#trkCardHost { background: #FFFFFF; border: none; }
            QLabel#detailTitle { color: #14213D; font-size: 20px; font-weight: 700; }
            QLabel#detailKey { color: #7C8BA5; font-size: 12px; }
            QLabel#detailValue { color: #14213D; font-size: 12px; font-weight: 500; }
            QLabel#detailDescription { color: #53657D; font-size: 12px; }
            QFrame#softSeparator { background: #E5EBF2; color: #E5EBF2; max-height: 1px; border: none; }
            QFrame#infoNote { background: #F2F7FF; border: 1px solid #D7E5F7; border-radius: 10px; }
            QLabel#infoNoteText { color: #55708E; font-size: 11px; }
            """.replace("%UP%", up_url).replace("%DOWN%", down_url)
        )
