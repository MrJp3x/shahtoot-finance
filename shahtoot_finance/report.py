from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from itertools import groupby
from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QHeaderView,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .dialogs import run_action
from .localization import DATE_MAX, fa, money, short_date
from .storage import DIRECTION_NAMES, INCOMING, INSTALLMENT, KIND_NAMES, Entry, Store
from .widgets import DateField, button, label, panel


@dataclass(frozen=True)
class Totals:
    installments: int
    checks: int
    incoming: int

    @property
    def outgoing(self):
        return self.installments + self.checks


def totals_for(entries: Iterable[Entry]) -> Totals:
    installments = checks = incoming = 0
    for entry in entries:
        if entry.direction == INCOMING:
            incoming += entry.amount
        elif entry.kind == INSTALLMENT:
            installments += entry.amount
        else:
            checks += entry.amount
    return Totals(installments, checks, incoming)


def week_start(day: date) -> date:
    return day - timedelta(days=(day.weekday() - 5) % 7)


def report_table(columns, *, selectable=False):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(
        QAbstractItemView.SelectionMode.SingleSelection if selectable else QAbstractItemView.SelectionMode.NoSelection,
    )
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(31)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def set_rows(table, rows):
    table.clearSelection()
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(f"<span>{escape(value)}</span>")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, col, item)


class DueReport(QWidget):
    entry_requested = Signal(int)

    def __init__(self, store: Store, today: date):
        super().__init__()
        self.store = store
        self.today = today
        self.follow_today = True
        self.start, self.end = self.default_range(today)
        self.bank_filter: str | None = None
        self.entries: list[Entry] = []

        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        filters, filter_layout = panel()
        form = QFormLayout()
        self.start_date = DateField(self.start)
        self.start_date.edit.setAccessibleName("تاریخ شروع گزارش")
        self.end_date = DateField(self.end)
        self.end_date.edit.setAccessibleName("تاریخ پایان گزارش")
        dates = QHBoxLayout()
        dates.addWidget(self.start_date, 1)
        dates.addWidget(label("تا", "muted"))
        dates.addWidget(self.end_date, 1)
        form.addRow(label("بازهٔ سررسید"), dates)
        self.bank = QComboBox()
        self.bank.setAccessibleName("بانک")
        bank_and_actions = QHBoxLayout()
        bank_and_actions.addWidget(self.bank, 1)
        reset = button("۳۰ روز آینده")
        reset.clicked.connect(self.reset_filters)
        apply = button("نمایش گزارش", "primary")
        apply.clicked.connect(self.apply_filters)
        bank_and_actions.addWidget(reset)
        bank_and_actions.addWidget(apply)
        form.addRow(label("بانک"), bank_and_actions)
        filter_layout.addLayout(form)
        body.addWidget(filters)

        figures = QHBoxLayout()
        outgoing, outgoing_layout = panel()
        outgoing_layout.addWidget(label("جمع پرداختی (تومان)", "muted"))
        self.outgoing = label("", "statValue", wrap=True)
        self.outgoing_detail = label("", "small", wrap=True)
        outgoing_layout.addWidget(self.outgoing)
        outgoing_layout.addWidget(self.outgoing_detail)
        incoming, incoming_layout = panel()
        incoming_layout.addWidget(label("جمع دریافتی (تومان)", "muted"))
        self.incoming = label("", "statValue", wrap=True)
        incoming_layout.addWidget(self.incoming)
        incoming_layout.addStretch()
        figures.addWidget(outgoing, 1)
        figures.addWidget(incoming, 1)
        body.addLayout(figures)

        body.addWidget(label("جمع هفتگی (تومان)", "heading"))
        self.weekly = report_table(["بازهٔ هفته", "اقساط", "چک‌های پرداختی", "جمع پرداختی", "جمع دریافتی"])
        self.weekly.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        body.addWidget(self.weekly)

        details_heading = QHBoxLayout()
        self.items_caption = label("", "heading")
        details_heading.addWidget(self.items_caption)
        details_heading.addStretch()
        self.open_button = button("باز کردن سند")
        self.open_button.clicked.connect(lambda: self.open_entry(self.items.currentRow()))
        details_heading.addWidget(self.open_button)
        body.addLayout(details_heading)
        self.empty = label("در این بازه سندِ تسویه‌نشده‌ای پیدا نشد.", "muted", wrap=True)
        body.addWidget(self.empty)
        self.items = report_table(["سررسید", "نوع", "عنوان", "بانک", "مبلغ (تومان)"], selectable=True)
        self.items.setMinimumHeight(220)
        self.items.cellActivated.connect(self.open_entry)
        self.items.itemSelectionChanged.connect(lambda: self.open_button.setEnabled(bool(self.items.selectedItems())))
        body.addWidget(self.items)

    @staticmethod
    def default_range(today):
        return today, min(today + timedelta(days=29), DATE_MAX)

    def set_date_fields(self):
        self.start_date.edit.setText(short_date(self.start))
        self.end_date.edit.setText(short_date(self.end))

    def refresh(self, today):
        if self.follow_today and today != self.today:
            self.start, self.end = self.default_range(today)
            self.set_date_fields()
        self.today = today
        selected = self.bank.currentData()
        banks = self.store.report_banks()
        if self.bank_filter is not None and self.bank_filter not in banks:
            banks.append(self.bank_filter)
        self.bank.clear()
        self.bank.addItem("همهٔ بانک‌ها", None)
        for bank in banks:
            self.bank.addItem(bank or "بدون بانک", bank)
        self.bank.setCurrentIndex(max(0, self.bank.findData(selected)))
        self.render(self.store.report_entries(self.start, self.end, self.bank_filter))

    def apply_filters(self):
        def apply():
            start, end = self.start_date.value(), self.end_date.value()
            bank = self.bank.currentData()
            entries = self.store.report_entries(start, end, bank)
            self.follow_today = (start, end) == self.default_range(self.today)
            self.start, self.end, self.bank_filter = start, end, bank
            self.render(entries)

        run_action(self, apply)

    def reset_filters(self):
        self.follow_today = True
        self.start, self.end = self.default_range(self.today)
        self.bank_filter = None
        self.set_date_fields()
        self.bank.setCurrentIndex(0)
        self.refresh(self.today)

    def render(self, entries):
        self.entries = entries
        totals = totals_for(entries)
        self.outgoing.setText(money(totals.outgoing))
        self.outgoing_detail.setText(f"اقساط {money(totals.installments)}  ·  چک‌ها {money(totals.checks)}")
        self.incoming.setText(money(totals.incoming))
        self.items_caption.setText(f"سررسیدهای باز · {fa(len(entries))} سند")
        weekly_totals = {
            start: totals_for(week_entries) for start, week_entries in groupby(entries, key=lambda entry: week_start(entry.due_on))
        }
        weeks = []
        for ordinal in range(week_start(self.start).toordinal(), self.end.toordinal() + 1, 7):
            start = date.fromordinal(ordinal)
            week = weekly_totals.get(start, Totals(0, 0, 0))
            first = short_date(max(start, self.start))
            last = short_date(min(start + timedelta(days=6), self.end))
            weeks.append((f"{first} تا {last}", money(week.installments), money(week.checks), money(week.outgoing), money(week.incoming)))
        set_rows(self.weekly, weeks)
        self.weekly.setFixedHeight(self.weekly.horizontalHeader().sizeHint().height() + 31 * min(len(weeks), 5) + 4)
        set_rows(self.items, [
            (short_date(entry.due_on), f"{KIND_NAMES[entry.kind]} {DIRECTION_NAMES[entry.direction]}",
             entry.title, entry.bank or "—", money(entry.amount))
            for entry in entries
        ])
        self.empty.setVisible(not entries)
        self.items.setVisible(bool(entries))
        self.open_button.setVisible(bool(entries))
        self.open_button.setEnabled(False)
        if entries:
            self.items.setCurrentCell(0, 0)

    def open_entry(self, row, _column=0):
        if 0 <= row < len(self.entries):
            self.entry_requested.emit(self.entries[row].id)
