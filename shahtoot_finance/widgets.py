from datetime import date

from PySide6.QtCore import QLocale, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QCalendarWidget, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .localization import DATE_MAX, DATE_MIN, JALALI, fa, parse_date, qdate, short_date
from .storage import MAX_LEAD_DAYS
from .theme import BORDER, symbol

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignAbsolute
FA_LOCALE = QLocale(QLocale.Language.Persian, QLocale.Country.Iran)


def label(text: str, style: str = "", *, wrap=False) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(style)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    widget.setAlignment(RIGHT)
    return widget


def button(text: str, role: str = "", icon=None) -> QPushButton:
    widget = QPushButton(text)
    widget.setProperty("role", role)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon is not None:
        widget.setIcon(icon)
    return widget


def panel(*, margins=(17, 15, 17, 15), spacing=8):
    widget = QFrame()
    widget.setProperty("role", "panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return widget, layout


def scroll_contents():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    contents = QWidget()
    contents.setObjectName("surface")
    scroll.setWidget(contents)
    return scroll, contents


def field(value="", placeholder="", limit=100) -> QLineEdit:
    widget = QLineEdit(value)
    widget.setPlaceholderText(placeholder)
    widget.setMaxLength(limit)
    widget.setAlignment(RIGHT)
    return widget


def numeric_field(value="", placeholder="") -> QLineEdit:
    widget = field(value, placeholder, limit=25)
    widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    return widget


def confirm(parent, title, message) -> bool:
    box = QMessageBox(QMessageBox.Icon.Warning, title, message, parent=parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    yes = box.addButton("تأیید", QMessageBox.ButtonRole.AcceptRole)
    no = box.addButton("انصراف", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(no)
    box.exec()
    return box.clickedButton() == yes


class LeadField(QWidget):
    def __init__(self, value: int | None, inherited_label: str | None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.choices = QComboBox()
        if inherited_label:
            self.choices.addItem(inherited_label, None)
        self.choices.addItem("روز سررسید", 0)
        for days in (1, 2, 3, 7, 14, 30):
            self.choices.addItem(f"{fa(days)} روز قبل", days)
        self.choices.addItem("تعداد روز دلخواه", -1)
        self.custom = QSpinBox()
        self.custom.setRange(0, MAX_LEAD_DAYS)
        self.custom.setSuffix(" روز")
        self.custom.setLocale(FA_LOCALE)
        self.custom.setAccessibleName("تعداد روز دلخواه پیش از سررسید")
        self.choices.currentIndexChanged.connect(self.update_custom)
        layout.addWidget(self.choices, 1)
        layout.addWidget(self.custom)
        index = self.choices.findData(value)
        self.choices.setCurrentIndex(index if index >= 0 else self.choices.findData(-1))
        if index < 0 and value is not None:
            self.custom.setValue(value)
        self.update_custom()

    def update_custom(self):
        self.custom.setVisible(self.choices.currentData() == -1)

    def value(self) -> int | None:
        picked = self.choices.currentData()
        return self.custom.value() if picked == -1 else picked


class DateField(QWidget):
    def __init__(self, value: date | None = None, *, maximum=DATE_MAX):
        super().__init__()
        self.maximum = maximum
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = numeric_field(short_date(value) if value else "", "۱۴۰۵/۰۸/۲۶")
        picker = button("", icon=symbol("calendar"))
        picker.setToolTip("تقویم شمسی")
        picker.setAccessibleName("باز کردن تقویم شمسی")
        picker.clicked.connect(self.choose)
        layout.addWidget(self.edit, 1)
        layout.addWidget(picker)
        self.setFocusProxy(self.edit)

    def value(self) -> date:
        day = parse_date(self.edit.text())
        if day > self.maximum:
            raise ValueError(f"تاریخ باید در {short_date(self.maximum)} یا پیش از آن باشد.")
        return day

    def choose(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("تقویم شمسی")
        body = QVBoxLayout(dialog)
        calendar = QCalendarWidget()
        calendar.setLocale(FA_LOCALE)
        calendar.setCalendar(JALALI)
        calendar.setDateRange(qdate(DATE_MIN), qdate(self.maximum))
        calendar.setFirstDayOfWeek(Qt.DayOfWeek.Saturday)
        calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        try:
            selected = self.value()
        except ValueError:
            selected = min(date.today(), self.maximum)
        calendar.setSelectedDate(qdate(selected))
        calendar.activated.connect(dialog.accept)
        body.addWidget(calendar)
        use = button("انتخاب تاریخ", "primary")
        use.clicked.connect(dialog.accept)
        body.addWidget(use)
        if dialog.exec():
            self.edit.setText(short_date(calendar.selectedDate().toPython()))


class Card(QAbstractButton):
    def __init__(self, accessible_name: str):
        super().__init__()
        self.setAccessibleName(accessible_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 13, 16, 13)
        self.body.setSpacing(7)

    def add(self, widget):
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.body.addWidget(widget)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = "#e6eefb" if self.isDown() else ("#fafdff" if self.underMouse() else "#ffffff")
        outline = "#4979bb" if self.hasFocus() else ("#9eb6d9" if self.underMouse() else BORDER)
        painter.setBrush(QColor(fill))
        painter.setPen(QPen(QColor(outline), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 13, 13)
