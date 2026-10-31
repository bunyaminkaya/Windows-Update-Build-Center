from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QPushButton, QTableWidget

from ui import icons
from ui.widgets.message_dialog import show_error, show_success, show_information

_EXPORT_BUTTON_QSS = """
QPushButton#exportButton {
    background: #FFFFFF; color: #1768E0; border: 1px solid #CBD9EC; border-radius: 10px;
    padding: 0 18px; font-size: 13px; font-weight: 700; min-height: 42px; max-height: 42px;
}
QPushButton#exportButton:hover { background: #F1F6FD; border-color: #9DB9E6; }
QPushButton#exportButton:disabled { color: #9AA8BF; background: #F4F7FB; border: 1px solid #E5ECF5; }
"""


def make_export_button(text: str = "  Dışa Aktar") -> QPushButton:
    """Sayfa başlıklarında kullanılan ortak 'Dışa Aktar' düğmesi (yalnızca görünüm)."""
    button = QPushButton(text)
    button.setObjectName("exportButton")
    icon = QIcon(icons.pixmap("save", "#1768E0", 36, stroke=2.0))
    button.setIcon(icon)
    button.setIconSize(QSize(18, 18))
    button.setCursor(Qt.PointingHandCursor)
    button.setStyleSheet(_EXPORT_BUTTON_QSS)
    button.setToolTip("Tablodaki kayıtları Excel ile açılabilen CSV dosyasına kaydeder")
    return button


def table_rows(table: QTableWidget, skip_columns=()) -> tuple[list[str], list[list[str]]]:
    columns = [c for c in range(table.columnCount()) if c not in skip_columns]
    headers = []
    for c in columns:
        item = table.horizontalHeaderItem(c)
        headers.append(item.text() if item else f"Sütun {c + 1}")
    rows = []
    for r in range(table.rowCount()):
        row = []
        for c in columns:
            item = table.item(r, c)
            row.append((item.text() if item else "").replace("\r", " ").replace("\n", " ").strip())
        rows.append(row)
    return headers, rows


def export_table_csv(parent, table: QTableWidget, base_name: str, skip_columns=()) -> bool:
    """Tablonun görünen satırlarını CSV'ye yazar. Excel (TR) için ';' ayracı + UTF-8 BOM."""
    headers, rows = table_rows(table, skip_columns)
    if not rows:
        show_information(parent, "Dışa aktarma", "Dışa aktarılacak kayıt bulunmuyor.")
        return False
    suggested = f"{base_name}_{datetime.now():%Y%m%d_%H%M}.csv"
    start_dir = str(Path.home() / "Documents") if (Path.home() / "Documents").exists() else str(Path.home())
    path, _ = QFileDialog.getSaveFileName(
        parent, "CSV olarak kaydet", str(Path(start_dir) / suggested), "CSV dosyaları (*.csv)"
    )
    if not path:
        return False
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(headers)
            writer.writerows(rows)
    except Exception as exc:
        show_error(parent, "Dışa aktarma başarısız", f"Dosya kaydedilemedi:\n{exc}")
        return False
    show_success(parent, "Dışa aktarma tamamlandı", f"{len(rows)} kayıt kaydedildi.\n\n{path}")
    return True
