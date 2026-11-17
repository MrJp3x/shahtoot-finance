from datetime import date
import re

from PySide6.QtCore import QLocale, QRectF, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QValidator
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QCalendarWidget, QComboBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .localization import ASCII_DIGITS, DATE_MAX, DATE_MIN, JALALI, MAX_AMOUNT, fa, parse_date, qdate, short_date
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


class AmountValidator(QValidator):
    def validate(self, text, position):
        translated = text.translate(ASCII_DIGITS).replace("٬", ",")
        digits = translated.replace(",", "")
        if not re.fullmatch(r"[0-9]*", digits) or len(digits) > len(str(MAX_AMOUNT)):
            return QValidator.State.Invalid, text, position
        if not digits:
            return QValidator.State.Intermediate, "", 0
        formatted = re.sub(r"(?<=[0-9])(?=(?:[0-9]{3})+$)", ",", digits)
        digits_after_cursor = len(translated[position:].replace(",", ""))
        cursor = len(formatted)
        while digits_after_cursor:
            cursor -= 1
            digits_after_cursor -= formatted[cursor] != ","
        return QValidator.State.Acceptable, formatted, cursor


class AmountField(QLineEdit):
    def __init__(self, amount: int | None = None):
        super().__init__(f"{amount:,}" if amount is not None else "")
        self.setPlaceholderText("0")
        self.setAlignment(RIGHT)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setValidator(AmountValidator(self))

    def keyPressEvent(self, event):
        if self.isReadOnly():
            super().keyPressEvent(event)
            return
        start = self.selectionStart() if self.hasSelectedText() else self.cursorPosition()
        end = start + len(self.selectedText())
        current = self.text()
        key = event.key()
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if event.matches(QKeySequence.StandardKey.Paste):
            inserted = QApplication.clipboard().text().strip()
            if not inserted:
                event.accept()
                return
        elif modifiers == Qt.KeyboardModifier.NoModifier and key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            inserted = ""
            if start == end:
                if key == Qt.Key.Key_Backspace:
                    start = max(0, start - (2 if current[max(0, start - 1):start] == "," else 1))
                else:
                    end += 2 if current[end:end + 1] == "," else 1
        elif not modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier) and re.fullmatch(
            r"[0-9]", event.text().translate(ASCII_DIGITS),
        ):
            inserted = event.text()
        else:
            super().keyPressEvent(event)
            return

        candidate = current[:start] + inserted + current[end:]
        state, formatted, cursor = self.validator().validate(candidate, start + len(inserted))
        if state != QValidator.State.Invalid and formatted != current:
            # Insert the formatted value in one native edit so Qt can undo the change.
            self.selectAll()
            self.insert(formatted)
            self.setCursorPosition(cursor)
        event.accept()


def confirm(parent, title, message, *, action="تأیید", destructive=False) -> bool:
    dialog = QDialog(parent)
    dialog.setObjectName("confirmationDialog")
    dialog.setWindowTitle(title)
    dialog.setFixedWidth(410)
    body = QVBoxLayout(dialog)
    body.setContentsMargins(24, 22, 24, 20)
    body.setSpacing(12)
    body.addWidget(label(title, "heading", wrap=True))
    body.addWidget(label(message, "muted", wrap=True))
    body.addSpacing(6)

    actions = QHBoxLayout()
    actions.setSpacing(8)
    actions.addStretch()
    cancel = button("انصراف")
    cancel.clicked.connect(dialog.reject)
    cancel.setDefault(True)
    accept = button(action, "destructive" if destructive else "primary")
    accept.setAutoDefault(False)
    accept.clicked.connect(dialog.accept)
    actions.addWidget(cancel)
    actions.addWidget(accept)
    body.addLayout(actions)
    cancel.setFocus()
    return dialog.exec() == QDialog.DialogCode.Accepted


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
        self.custom.setGroupSeparatorShown(True)
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
        self.edit = field(short_date(value) if value else "", "۱۴۰۵/۰۸/۲۶", limit=25)
        self.edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
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
