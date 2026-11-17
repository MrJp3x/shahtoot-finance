import sys

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

NAVY = "#15294b"
BLUE = "#345ca0"
INK = "#182b48"
MUTED = "#50647f"
BORDER = "#dce4ef"
BACKGROUND = "#f4f7fb"

STYLE = """
QWidget { color: #182b48; }
QMainWindow, QDialog, QWidget#surface { background: #f4f7fb; }
QWidget#workspace { background: #f4f7fb; }
QFrame#rail { background: #15294b; border: none; }
QLabel#brand { color: #ffffff; font-size: 18px; font-weight: 700; }
QLabel#railCaption { color: #bdcbe2; font-size: 12px; }
QFrame#railLine { background: #30476c; border: none; }
QPushButton[role="nav"] {
    background: transparent; border: 1px solid transparent; border-radius: 9px;
    color: #dbe5f5; padding: 10px 13px; text-align: right; font-weight: 600;
}
QPushButton[role="nav"]:hover { background: #203858; color: white; }
QPushButton[role="nav"]:checked { background: #2a4470; color: white; border-color: #466392; }
QPushButton[role="nav"]:focus { border-color: #8eaedb; }
QFrame#topbar { background: white; border: none; border-bottom: 1px solid #e0e7f0; }
QFrame#hero { background: #19355e; border: 1px solid #274775; border-radius: 16px; }
QLabel#heroTitle { color: white; font-size: 30px; font-weight: 700; }
QLabel#heroCopy { color: #d6e3f8; font-size: 14px; }
QLabel#heroDate { color: #e7effd; background: #274875; border: 1px solid #3e5e8d;
  border-radius: 10px; padding: 8px 13px; font-weight: 600; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; }
QLabel#heading { font-size: 18px; font-weight: 700; }
QLabel#cardTitle { font-size: 17px; font-weight: 700; }
QLabel#statValue { font-size: 25px; font-weight: 700; }
QLabel#muted { color: #50647f; }
QLabel#small { color: #50647f; font-size: 12px; }
QLabel#money { color: #19355e; font-weight: 700; }
QFrame[role="panel"] { background: white; border: 1px solid #dce4ef; border-radius: 13px; }
QPushButton {
    background: white; border: 1px solid #d4deec; border-radius: 8px;
    padding: 7px 13px; font-weight: 600; min-height: 23px;
}
QPushButton:hover { background: #f0f5fd; border-color: #9cb4d8; }
QPushButton:pressed { background: #e6eefb; }
QPushButton:focus, QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #4979bb;
}
QPushButton[role="primary"] { background: #234573; border-color: #234573; color: white; }
QPushButton[role="primary"]:hover { background: #31588d; border-color: #31588d; }
QPushButton[role="primary"]:focus { border-color: #6b9ada; }
QPushButton[role="link"] { background: transparent; color: #345ca0; border-color: transparent; }
QPushButton[role="link"]:hover { background: #eaf1fc; }
QPushButton[role="danger"] { color: #a12e43; }
QPushButton[role="danger"]:hover { background: #fff0f3; border-color: #e1aab5; }
QPushButton:disabled { color: #6a7890; background: #eaf0f7; border-color: #dce4ef; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
    background: white; border: 1px solid #d4deec; border-radius: 8px;
    padding: 7px 10px; min-height: 22px; selection-background-color: #d9e7fa;
    selection-color: #15294b;
}
QComboBox::drop-down { width: 25px; border: none; }
QComboBox QAbstractItemView { background: white; selection-background-color: #e6effd; selection-color: #15294b; }
QLineEdit:disabled, QComboBox:disabled { background: #eaf0f7; color: #62728b; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: #eef3f9; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #bccade; border-radius: 4px; min-height: 26px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QTableWidget {
    background: white; alternate-background-color: #f6f8fc; border: 1px solid #dce4ef;
    border-radius: 9px; gridline-color: #edf1f6; selection-color: #162c50;
    selection-background-color: #e2edff;
}
QHeaderView::section { background: #eaf0f8; color: #243f66; border: none; padding: 10px; font-weight: 700; }
QProgressBar {
    background: #e7eef8; border: none; border-radius: 3px; min-height: 6px; max-height: 6px;
}
QProgressBar::chunk { background: #4a75b0; border-radius: 3px; }
QLabel[badge] { border-radius: 7px; padding: 4px 8px; font-size: 12px; font-weight: 600; }
QLabel[badge="open"] { background: #eaf0fa; color: #35547d; }
QLabel[badge="soon"] { background: #fff2d9; color: #75480d; }
QLabel[badge="today"] { background: #ffe7ca; color: #78420c; }
QLabel[badge="late"] { background: #fce8ed; color: #942d44; }
QLabel[badge="settled"] { background: #e0f3e9; color: #1e6245; }
QStatusBar { background: #edf2fa; color: #425979; }
"""


def apply_theme(app):
    app.setStyle("Fusion")
    font = QFont()
    if sys.platform == "win32":
        font.setFamilies(["Segoe UI", "Tahoma"])
    elif sys.platform == "darwin":
        font.setFamilies(["Geeza Pro", "Arial"])
    font.setPixelSize(14)
    app.setFont(font)
    app.setStyleSheet(STYLE)


def brand_icon(*, alert=False) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 64, size / 64)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(NAVY))
        painter.drawRoundedRect(0, 0, 64, 64, 15, 15)
        painter.setBrush(QColor("#e1edff"))
        for x, y in ((21, 26), (33, 26), (15, 37), (27, 37), (39, 37), (21, 48), (33, 48)):
            painter.drawEllipse(x, y, 10, 10)
        painter.setBrush(QColor("#8cb4eb"))
        leaf = QPainterPath(QPointF(31, 24))
        leaf.cubicTo(32, 15, 39, 9, 48, 10)
        leaf.cubicTo(47, 18, 40, 23, 31, 24)
        painter.drawPath(leaf)
        if alert:
            painter.setPen(QPen(QColor(NAVY), 2))
            painter.setBrush(QColor("#f6b75f"))
            painter.drawEllipse(45, 2, 17, 17)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def symbol(name: str, color=MUTED, size=18) -> QIcon:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 1.65)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    if name in {"calendar", "check", "loan"}:
        painter.drawRoundedRect(3, 5, 18, 15, 2, 2)
    if name == "calendar":
        painter.drawLine(3, 10, 21, 10)
        painter.drawLine(8, 3, 8, 7)
        painter.drawLine(16, 3, 16, 7)
        painter.drawLine(8, 15, 11, 15)
    elif name == "check":
        painter.drawLine(6, 10, 18, 10)
        painter.drawLine(6, 15, 10, 15)
        painter.drawLine(14, 16, 18, 14)
    elif name == "loan":
        painter.drawLine(3, 11, 21, 11)
        painter.drawLine(7, 16, 11, 16)
    elif name == "home":
        for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
            painter.drawRoundedRect(x, y, 7, 7, 1, 1)
    elif name == "settings":
        for x, y in ((8, 6), (15, 12), (10, 18)):
            painter.drawLine(4, y, x - 2, y)
            painter.drawLine(x + 2, y, 20, y)
            painter.drawEllipse(x - 2, y - 2, 4, 4)
    elif name == "plus":
        painter.drawLine(5, 12, 19, 12)
        painter.drawLine(12, 5, 12, 19)
    elif name == "arrow":
        painter.drawLine(15, 6, 9, 12)
        painter.drawLine(9, 12, 15, 18)
    painter.end()
    return QIcon(pixmap)
