from __future__ import annotations

from datetime import date
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QMessageBox, QPlainTextEdit, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .localization import fa, money, parse_money, short_date
from .storage import (
    CHECK, DIRECTION_NAMES, INCOMING, INSTALLMENT, KIND_NAMES, MAX_INSTALLMENTS,
    OUTGOING, Entry, EntryDetails, Loan, LoanDetails, Store, lead_time, status_label,
)
from .widgets import (
    FA_LOCALE, RIGHT, AmountField, DateField, LeadField, button, confirm, field, label,
    panel, scroll_contents,
)

log = logging.getLogger(__name__)


def notes_field(value: str):
    widget = QPlainTextEdit(value)
    widget.setPlaceholderText("یادداشت اختیاری")
    widget.setFixedHeight(76)
    return widget


def confirm_delete_loan(parent, store: Store, loan_id: int, title: str) -> bool:
    if not confirm(
        parent, "حذف وام",
        f"وام «{title}» همراه با همهٔ اقساط و سوابق پرداخت آن برای همیشه حذف می‌شود.",
        action="حذف وام", destructive=True,
    ):
        return False
    return run_action(parent, lambda: store.delete_loan(loan_id))


def run_action(parent, action) -> bool:
    try:
        action()
    except ValueError as error:
        box = QMessageBox(QMessageBox.Icon.Warning, "اطلاعات را بررسی کنید", str(error), parent=parent)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.exec()
        return False
    except Exception:
        log.exception("Operation failed")
        QMessageBox.critical(parent, "خطا", "عملیات انجام نشد. دسترسی به فایل یا پوشهٔ داده‌ها را بررسی کنید.")
        return False
    return True


class FormDialog(QDialog):
    def __init__(self, parent, title: str, *, width=550, height=600):
        super().__init__(parent)
        self.setObjectName("formDialog")
        self.setWindowTitle(title)
        available = self.screen().availableGeometry()
        self.resize(min(width, available.width() - 40), min(height, available.height() - 90))
        body = QVBoxLayout(self)
        body.setContentsMargins(21, 17, 21, 16)
        body.setSpacing(12)
        body.addWidget(label(title, "heading"))
        scroller, contents = scroll_contents()
        self.form = QFormLayout(contents)
        self.form.setContentsMargins(1, 1, 7, 8)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(8)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setLabelAlignment(RIGHT)
        body.addWidget(scroller, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = button("انصراف")
        cancel.clicked.connect(self.reject)
        save = button("ذخیره", "primary")
        save.clicked.connect(self.save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        body.addLayout(actions)

    def row(self, title, widget):
        caption = label(title, wrap=True)
        caption.setBuddy(widget)
        self.form.addRow(caption, widget)

    def save(self):
        if run_action(self, self.persist):
            self.accept()


class LoanForm(FormDialog):
    def __init__(self, parent, store: Store, loan: Loan | None = None):
        super().__init__(parent, "ویرایش وام" if loan else "ثبت وام", height=665 if loan is None else 506)
        self.store, self.loan = store, loan
        self.loan_id: int | None = loan.id if loan else None
        self.title = field(loan.title if loan else "", "مثلاً تسهیلات خرید تجهیزات")
        self.bank = field(loan.bank if loan else "", "نام بانک", limit=80)
        self.reference = field(loan.reference if loan else "", "اختیاری", limit=80)
        self.principal = AmountField(loan.principal if loan else None)
        self.received = DateField(loan.received_on if loan else date.today())
        self.lead = LeadField(loan.lead_days if loan else None, "پیش‌فرض برنامه")
        self.notes = notes_field(loan.notes if loan else "")
        self.row("عنوان وام", self.title)
        self.row("بانک", self.bank)
        self.row("شمارهٔ قرارداد", self.reference)
        self.row("اصل وام (تومان)", self.principal)
        self.row("تاریخ دریافت", self.received)
        if loan is None:
            self.first_due = DateField()
            self.count = QSpinBox()
            self.count.setLocale(FA_LOCALE)
            self.count.setRange(1, MAX_INSTALLMENTS)
            self.count.setGroupSeparatorShown(True)
            self.count.setValue(12)
            self.amount = AmountField()
            self.row("سررسید نخستین قسط", self.first_due)
            self.row("تعداد اقساط ماهانه", self.count)
            self.row("مبلغ هر قسط (تومان)", self.amount)
        self.row("شروع یادآوری", self.lead)
        self.row("یادداشت وام", self.notes)
        self.title.setFocus()

    def persist(self):
        details = LoanDetails(
            self.title.text(), self.bank.text(), parse_money(self.principal.text()),
            self.received.value(), self.reference.text(), self.lead.value(), self.notes.toPlainText(),
        )
        if self.loan is None:
            self.loan_id = self.store.create_loan(
                details, self.first_due.value(), self.count.value(), parse_money(self.amount.text()),
            )
        else:
            self.store.edit_loan(self.loan.id, details)


class EntryForm(FormDialog):
    def __init__(self, parent, store: Store, entry: Entry | None = None):
        linked = entry is not None and entry.loan_id is not None
        kind = entry.kind if entry else CHECK
        super().__init__(parent, f"{'ویرایش' if entry else 'ثبت'} {KIND_NAMES[kind]}", height=410 if linked else 615)
        self.store, self.entry = store, entry
        self.entry_id = entry.id if entry else None
        self.direction = QComboBox()
        self.direction.addItem("پرداختی", OUTGOING)
        self.direction.addItem("دریافتی", INCOMING)
        self.direction.setCurrentIndex(self.direction.findData(entry.direction if entry else OUTGOING))
        self.direction.setEnabled(entry is None or entry.settled_on is None)
        self.title = field(entry.title if entry else "", "مثلاً خرید مواد اولیه")
        self.party = field(entry.party if entry else "", "نام دریافت‌کننده یا صادرکننده")
        self.reference = field(entry.reference if entry else "", "اختیاری", limit=80)
        self.bank = field(entry.bank if entry else "", "اختیاری", limit=80)
        self.amount = AmountField(entry.amount if entry else None)
        self.due = DateField(entry.due_on if entry else None)
        self.lead = LeadField(entry.lead_days if entry else None, "تنظیم وام" if linked else "پیش‌فرض برنامه")
        self.notes = notes_field(entry.notes if entry else "")
        if not linked:
            self.row("نوع چک" if kind == CHECK else "جهت", self.direction)
            self.row("عنوان", self.title)
            self.row("طرف حساب", self.party)
            self.row("بانک", self.bank)
            self.row("شمارهٔ چک" if kind == CHECK else "شمارهٔ مرجع", self.reference)
            self.title.setFocus()
        else:
            self.amount.setFocus()
        self.row("مبلغ (تومان)", self.amount)
        self.row("تاریخ سررسید", self.due)
        self.row("شروع یادآوری", self.lead)
        self.row("یادداشت", self.notes)

    def persist(self):
        details = EntryDetails(
            self.entry.kind if self.entry else CHECK, self.direction.currentData(),
            self.title.text(), self.party.text(), parse_money(self.amount.text()), self.due.value(),
            self.reference.text(), self.bank.text(), self.lead.value(), self.notes.toPlainText(),
        )
        if self.entry is None:
            self.entry_id = self.store.create(details)[0].id
        else:
            self.store.edit(self.entry.id, details)


class SettleForm(FormDialog):
    def __init__(self, parent, store, entry):
        title = "ثبت وصول چک" if entry.direction == INCOMING else "ثبت پرداخت"
        super().__init__(parent, title, width=403, height=204)
        self.store, self.entry = store, entry
        self.day = DateField(date.today(), maximum=date.today())
        self.row("تاریخ تسویه", self.day)

    def persist(self):
        self.store.settle(self.entry.id, self.day.value())


class EntryDetail(QDialog):
    def __init__(self, parent, store: Store, entry_id: int):
        super().__init__(parent)
        self.store, self.entry_id = store, entry_id
        self.changed = False
        available = self.screen().availableGeometry()
        self.resize(min(552, available.width() - 40), min(530, available.height() - 90))
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 17, 20, 17)
        self.rebuild()

    def rebuild(self):
        while self.body.count():
            self.body.takeAt(0).widget().deleteLater()
        entry = self.store.get(self.entry_id)
        title = KIND_NAMES[entry.kind]
        if entry.installment_number is not None:
            title = f"قسط {fa(entry.installment_number)} از {fa(entry.installment_total)}"
        self.setWindowTitle(title)
        scroller, contents = scroll_contents()
        content = QVBoxLayout(contents)
        content.setContentsMargins(0, 0, 5, 0)
        content.setSpacing(10)
        content.addWidget(label(f"{title} · {entry.title}", "heading", wrap=True))
        summary, layout = panel()
        fields = (
            ("وضعیت", status_label(entry, date.today(), self.store.reminder_days())),
            ("مبلغ", f"{money(entry.amount)} تومان"),
            ("سررسید", short_date(entry.due_on)),
            ("تاریخ تسویه", short_date(entry.settled_on) if entry.settled_on else ""),
            ("نوع چک", DIRECTION_NAMES[entry.direction] if entry.kind == CHECK else ""),
            ("طرف حساب", entry.party if entry.loan_id is None else ""),
            ("بانک", entry.bank),
            ("شمارهٔ مرجع", f"\u2066{entry.reference}\u2069" if entry.reference else ""),
            ("شروع یادآوری", lead_label(lead_time(entry, self.store.reminder_days()))),
            ("یادداشت", entry.notes),
        )
        for caption, value in fields:
            if value:
                layout.addWidget(label(f"{caption}  •  {value}", wrap=True))
        content.addWidget(summary)
        content.addStretch()
        scroller.setMinimumHeight(185)
        self.body.addWidget(scroller, 1)
        actions = QHBoxLayout()
        action_box = QWidget()
        action_box.setLayout(actions)
        edit = button("ویرایش")
        edit.clicked.connect(self.edit)
        actions.addWidget(edit)
        if entry.loan_id is None:
            delete = button("حذف", "danger")
            delete.clicked.connect(self.delete)
            actions.addWidget(delete)
        actions.addStretch()
        paid = button(
            "بازگرداندن تسویه" if entry.settled_on else
            ("ثبت وصول" if entry.direction == INCOMING else "ثبت پرداخت"),
            "" if entry.settled_on else "primary",
        )
        paid.clicked.connect(self.toggle_paid)
        actions.addWidget(paid)
        self.body.addWidget(action_box)

    def edit(self):
        if EntryForm(self, self.store, self.store.get(self.entry_id)).exec():
            self.changed = True
            self.rebuild()

    def toggle_paid(self):
        entry = self.store.get(self.entry_id)
        if entry.settled_on:
            if not confirm(self, "بازگرداندن تسویه", "این مورد دوباره باز می‌شود و در سررسیدها دیده خواهد شد."):
                return
            changed = run_action(self, lambda: self.store.settle(entry.id, None))
        else:
            changed = SettleForm(self, self.store, entry).exec()
        if changed:
            self.changed = True
            self.rebuild()

    def delete(self):
        if confirm(self, "حذف سند", "این سند و سابقهٔ یادآوری آن برای همیشه حذف می‌شود."):
            if run_action(self, lambda: self.store.delete(self.entry_id)):
                self.changed = True
                self.accept()


def lead_label(days: int):
    return "روز سررسید" if days == 0 else f"{fa(days)} روز قبل از سررسید"


class LoanDetail(QDialog):
    def __init__(self, parent, store: Store, loan_id: int):
        super().__init__(parent)
        self.store, self.loan_id = store, loan_id
        self.changed = False
        self.setWindowTitle("جزئیات وام")
        available = self.screen().availableGeometry()
        self.resize(min(776, available.width() - 40), min(682, available.height() - 90))
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 17, 20, 17)
        self.body.setSpacing(9)

        self.title = label("", "heading", wrap=True)
        self.body.addWidget(self.title)
        info, info_box = panel(spacing=4)
        self.loan_meta = label("", wrap=True)
        self.loan_amount = label("", "money", wrap=True)
        self.notes = label("", "muted", wrap=True)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        note_scroll, notes_container = scroll_contents()
        notes_box = QVBoxLayout(notes_container)
        notes_box.setContentsMargins(0, 0, 4, 0)
        notes_box.addWidget(self.notes)
        note_scroll.setFixedHeight(59)
        self.note_scroll = note_scroll
        info_box.addWidget(self.loan_meta)
        info_box.addWidget(self.loan_amount)
        info_box.addWidget(note_scroll)
        self.body.addWidget(info)
        self.schedule_title = label("", "heading")
        self.body.addWidget(self.schedule_title)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["قسط", "سررسید", "مبلغ (تومان)", "وضعیت", "تاریخ تسویه"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(37)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellActivated.connect(self.open_installment)
        self.body.addWidget(self.table, 1)

        actions = QHBoxLayout()
        edit = button("ویرایش وام")
        edit.clicked.connect(self.edit)
        actions.addWidget(edit)
        delete = button("حذف وام", "danger")
        delete.clicked.connect(self.delete)
        actions.addWidget(delete)
        actions.addStretch()
        selected = button("باز کردن قسط انتخاب‌شده", "primary")
        selected.clicked.connect(lambda: self.open_installment(self.table.currentRow()))
        actions.addWidget(selected)
        self.body.addLayout(actions)
        self.refresh()

    def refresh(self):
        loan = self.store.loan(self.loan_id)
        row = self.table.currentRow()
        self.title.setText(loan.title)
        today = date.today()
        default = self.store.reminder_days()
        lead = loan.lead_days if loan.lead_days is not None else default
        reference = f"  •  قرارداد \u2066{loan.reference}\u2069" if loan.reference else ""
        self.loan_meta.setText(f"{loan.bank}  •  دریافت در {short_date(loan.received_on)}{reference}")
        outstanding = sum(entry.amount for entry in loan.installments if entry.settled_on is None)
        self.loan_amount.setText(
            f"اصل وام {money(loan.principal)} تومان  •  اقساط باز {money(outstanding)} تومان"
            f"  •  یادآوری {lead_label(lead)}"
        )
        self.notes.setText(f"یادداشت وام  •  {loan.notes}")
        self.note_scroll.setVisible(bool(loan.notes))
        paid = sum(entry.settled_on is not None for entry in loan.installments)
        self.schedule_title.setText(f"جدول اقساط  ·  {fa(paid)} از {fa(len(loan.installments))} پرداخت شده")
        self.table.setRowCount(len(loan.installments))
        for i, entry in enumerate(loan.installments):
            values = (
                fa(entry.installment_number), short_date(entry.due_on), money(entry.amount),
                status_label(entry, today, default),
                short_date(entry.settled_on) if entry.settled_on else "—",
            )
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setData(Qt.ItemDataRole.UserRole, entry.id)
                self.table.setItem(i, col, cell)
        if self.table.rowCount():
            self.table.selectRow(min(max(row, 0), self.table.rowCount() - 1))

    def open_installment(self, row: int, _column=0):
        if row < 0:
            return
        entry_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        detail = EntryDetail(self, self.store, entry_id)
        detail.exec()
        if detail.changed:
            self.changed = True
            self.refresh()

    def edit(self):
        if LoanForm(self, self.store, self.store.loan(self.loan_id)).exec():
            self.changed = True
            self.refresh()

    def delete(self):
        if confirm_delete_loan(self, self.store, self.loan_id, self.title.text()):
            self.changed = True
            self.accept()
