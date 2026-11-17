from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QMainWindow, QMenu, QProgressBar, QVBoxLayout, QWidget,
)

from . import APP_NAME
from .dialogs import EntryDetail, EntryForm, LoanDetail, LoanForm, confirm_delete_loan, lead_label, run_action
from .localization import fa, long_date, money, normalized, short_date
from .platform_services import set_startup, startup_enabled
from .storage import (
    CHECK, DIRECTION_NAMES, INCOMING, INSTALLMENT, KIND_NAMES, Entry, Loan, Store,
    is_due, status, status_label,
)
from .theme import BLUE, symbol
from .widgets import Card, LeadField, button, field, label, panel, scroll_contents

PAGES = {
    "home": ("نمای کلی", "home"),
    "loans": ("وام‌ها", "loan"),
    "checks": ("چک‌ها", "check"),
    "due": ("سررسیدها", "calendar"),
    "settings": ("تنظیمات", "settings"),
}


def when(day: date, today: date) -> str:
    remaining = (day - today).days
    if remaining == 0:
        return "امروز"
    if remaining > 0:
        return f"{fa(remaining)} روز مانده"
    return f"{fa(-remaining)} روز گذشته"


def badge(text: str, state: str):
    widget = label(text)
    widget.setProperty("badge", state)
    return widget


def includes(query: str, *fields) -> bool:
    if not query:
        return True
    value = normalized(" ".join(fields))
    return all(term in value for term in query.split())


class MainWindow(QMainWindow):
    data_changed = Signal()
    test_requested = Signal()

    def __init__(
        self, store: Store, *, background_available: bool, manage_startup: bool = False, startup_error: str = "",
    ):
        super().__init__()
        self.store = store
        self.background_available = background_available
        self.manage_startup = manage_startup
        self.startup_error = startup_error
        self.page = "home"
        self.today = date.today()
        self.default_days = store.reminder_days()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(790, 510)
        self.resize(1170, 790)
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self.sidebar())
        workspace = QWidget()
        workspace.setObjectName("workspace")
        work = QVBoxLayout(workspace)
        work.setContentsMargins(0, 0, 0, 0)
        work.setSpacing(0)
        work.addWidget(self.toolbar())
        self.scroller, self.contents = scroll_contents()
        self.body = QVBoxLayout(self.contents)
        self.body.setContentsMargins(22, 19, 22, 22)
        self.body.setSpacing(12)
        work.addWidget(self.scroller, 1)
        shell.addWidget(workspace, 1)
        self.statusBar().setSizeGripEnabled(False)
        if startup_error:
            self.statusBar().showMessage(startup_error)
        self.refresh()

    def sidebar(self):
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(180)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(13, 24, 13, 18)
        layout.setSpacing(7)
        logo = label("")
        logo.setPixmap(self.windowIcon().pixmap(38, 38))
        layout.addWidget(logo)
        layout.addWidget(label("حسابداری شاهتوت", "brand"))
        layout.addSpacing(13)
        divider = QFrame()
        divider.setObjectName("railLine")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(6)
        self.page_buttons = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for page, (title, icon_name) in PAGES.items():
            destination = button(title, "nav", symbol(icon_name, "#c9d8ef"))
            destination.setIconSize(QSize(18, 18))
            destination.setCheckable(True)
            destination.clicked.connect(lambda _checked=False, target=page: self.go(target))
            group.addButton(destination)
            layout.addWidget(destination)
            self.page_buttons[page] = destination
        layout.addStretch()
        indicator = "●  یادآوری در پس‌زمینه" if self.background_available else "داده‌ها روی این دستگاه"
        layout.addWidget(label(indicator, "railCaption", wrap=True))
        return rail

    def toolbar(self):
        top = QFrame()
        top.setObjectName("topbar")
        bar = QHBoxLayout(top)
        bar.setContentsMargins(22, 11, 22, 11)
        bar.setSpacing(9)
        self.location = label("", "heading")
        bar.addWidget(self.location)
        bar.addStretch()
        self.search = field("", "جست‌وجوی عنوان، بانک یا شماره")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("جست‌وجو")
        self.search.setFixedWidth(202)
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search)
        self.add_check = button("ثبت چک", icon=symbol("plus", BLUE))
        self.add_check.clicked.connect(self.new_check)
        bar.addWidget(self.add_check)
        self.add_loan = button("ثبت وام", "primary", symbol("plus", "#ffffff"))
        self.add_loan.clicked.connect(self.new_loan)
        bar.addWidget(self.add_loan)
        return top

    def go(self, page: str):
        changed = self.page != page
        self.page = page
        if changed:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self.refresh()
        if changed:
            self.scroller.verticalScrollBar().setValue(0)

    def show_due(self):
        self.go("due")
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self, _query=""):
        self.today = date.today()
        self.default_days = self.store.reminder_days()
        self.page_buttons[self.page].setChecked(True)
        self.location.setText(PAGES[self.page][0])
        self.search.setVisible(self.page in {"loans", "checks", "due"})
        self.add_check.setVisible(self.page != "settings")
        self.add_loan.setVisible(self.page != "settings")
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()

        if self.page == "settings":
            self.settings_page()
        else:
            self.ledger_page()
        self.body.addStretch()

    def ledger_page(self):
        entries = self.store.entries()
        open_entries = [entry for entry in entries if entry.settled_on is None]
        due = [entry for entry in open_entries if is_due(entry, self.today, self.default_days)]
        checks = [entry for entry in entries if entry.kind == CHECK]
        installments = [entry for entry in open_entries if entry.kind == INSTALLMENT]
        query = normalized(self.search.text())
        if self.page == "home":
            self.overview(installments, checks, due)
        elif self.page == "loans":
            loans = self.store.loans()
            filtered = [loan for loan in loans if includes(query, loan.title, loan.bank, loan.reference, loan.notes)]
            standalone = [
                entry for entry in entries if entry.kind == INSTALLMENT and entry.loan_id is None
                and self.matches_entry(query, entry)
            ]
            self.section("پرونده‌های وام", len(filtered) + len(standalone))
            self.grid([self.loan_card(loan) for loan in filtered] + [self.entry_card(e) for e in standalone])
        elif self.page == "checks":
            filtered = [entry for entry in checks if self.matches_entry(query, entry)]
            filtered.sort(key=lambda entry: (entry.settled_on is not None, entry.due_on, entry.id))
            self.section("چک‌های ثبت‌شده", len(filtered))
            self.grid([self.entry_card(entry) for entry in filtered])
        else:
            filtered = [entry for entry in due if self.matches_entry(query, entry)]
            self.section("سررسیدهای باز", len(filtered))
            self.body.addWidget(label("موارد معوق تا زمان ثبت تسویه در این فهرست می‌مانند.", "muted", wrap=True))
            self.grid([self.entry_card(entry) for entry in filtered], "سررسیدی در بازهٔ یادآوری وجود ندارد.")

    def overview(self, installments, checks, due):
        hero, hero_layout = panel(margins=(19, 18, 19, 18), spacing=6)
        hero.setObjectName("hero")
        headline = QHBoxLayout()
        headline.addWidget(label("تعهدات مالی شاهتوت", "heroTitle"))
        headline.addStretch()
        headline.addWidget(label(long_date(self.today), "heroDate"))
        hero_layout.addLayout(headline)
        hero_layout.addWidget(label("پیگیری اقساط و چک‌ها در یک نگاه", "heroCopy"))
        self.body.addWidget(hero)

        open_checks = [entry for entry in checks if entry.settled_on is None]
        urgent = sum(entry.due_on <= self.today for entry in due)
        checks_payable = sum(entry.amount for entry in open_checks if entry.direction != INCOMING)
        stats = QWidget()
        row = QHBoxLayout(stats)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        metrics = (
            ("اقساط پرداخت‌نشده", len(installments), f"{money(sum(e.amount for e in installments))} تومان مانده", "loans"),
            ("چک‌های باز", len(open_checks), f"{money(checks_payable)} تومان پرداختی", "checks"),
            ("در بازهٔ یادآوری", len(due), f"{fa(urgent)} مورد امروز یا معوق", "due"),
        )
        for title, value, description, page in metrics:
            tile = Card(title)
            tile.add(label(title, "muted", wrap=True))
            tile.add(label(fa(value), "statValue"))
            tile.add(label(description, "small", wrap=True))
            tile.clicked.connect(lambda _checked=False, target=page: self.go(target))
            row.addWidget(tile, 1)
        self.body.addWidget(stats)

        upcoming = due or sorted(installments + open_checks, key=lambda entry: (entry.due_on, entry.id))
        self.section(
            "سررسیدهای نیازمند پیگیری" if due else "نزدیک‌ترین سررسیدها",
            len(upcoming), ("همهٔ سررسیدها", "due") if due else None,
        )
        self.grid(
            [self.entry_card(entry) for entry in upcoming[:4]],
            "با ثبت نخستین وام یا چک، سررسیدهای آن اینجا نمایش داده می‌شود.",
        )
        loans = self.store.loans()
        if loans:
            self.section("وام‌ها", len(loans), ("همهٔ وام‌ها", "loans"))
            self.grid([self.loan_card(loan) for loan in loans[:4]])

    def section(self, title, total, action=None):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 2, 0, 0)
        row.addWidget(label(title, "heading"))
        row.addWidget(badge(fa(total), "open"))
        row.addStretch()
        if action:
            link = button(action[0], "link", symbol("arrow", BLUE))
            link.clicked.connect(lambda: self.go(action[1]))
            row.addWidget(link)
        self.body.addWidget(bar)

    def grid(self, cards, empty="موردی برای نمایش وجود ندارد."):
        if not cards:
            blank, layout = panel(margins=(18, 18, 18, 18))
            layout.addWidget(label(empty, "muted", wrap=True))
            self.body.addWidget(blank)
            return
        area = QWidget()
        grid = QGridLayout(area)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for i, card in enumerate(cards):
            grid.addWidget(card, i // 2, i % 2)
        self.body.addWidget(area)

    def matches_entry(self, query, entry):
        return includes(query, entry.title, entry.party, entry.bank, entry.reference, entry.notes, short_date(entry.due_on))

    def entry_card(self, entry: Entry):
        kind = KIND_NAMES[entry.kind]
        if entry.kind == CHECK:
            kind = f"{kind} {DIRECTION_NAMES[entry.direction]}"
        elif entry.installment_number is not None:
            kind = f"قسط {fa(entry.installment_number)} از {fa(entry.installment_total)}"
        state = status(entry, self.today, self.default_days)
        card = Card(f"{kind} {entry.title}")
        self.card_head(card, kind, status_label(entry, self.today, self.default_days), state)
        card.add(label(entry.title, "cardTitle", wrap=True))
        elapsed = "" if entry.settled_on else f"  •  {when(entry.due_on, self.today)}"
        card.add(label(f"{short_date(entry.due_on)}{elapsed}  •  {entry.party}", "small", wrap=True))
        card.add(label(f"{money(entry.amount)} تومان", "money"))
        card.clicked.connect(lambda: self.open_entry(entry.id))
        return card

    def loan_card(self, loan: Loan):
        outstanding = [entry for entry in loan.installments if entry.settled_on is None]
        settled = len(loan.installments) - len(outstanding)
        nearest = min(outstanding, key=lambda entry: entry.due_on, default=None)
        state = status(nearest, self.today, self.default_days) if nearest else "settled"
        state_text = status_label(nearest, self.today, self.default_days) if nearest else "تسویه‌شده"
        card = Card(f"وام {loan.title}")
        self.card_head(card, loan.bank, state_text, state)
        card.add(label(loan.title, "cardTitle", wrap=True))
        caption = f"{fa(settled)} از {fa(len(loan.installments))} قسط پرداخت شده"
        if nearest:
            caption += f"  •  سررسید {short_date(nearest.due_on)}"
        card.add(label(caption, "small", wrap=True))
        progress = QProgressBar()
        progress.setRange(0, max(1, len(loan.installments)))
        progress.setValue(settled)
        progress.setTextVisible(False)
        progress.setAccessibleName(caption)
        card.add(progress)
        card.clicked.connect(lambda: self.open_loan(loan.id))
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(lambda point: self.loan_menu(card, point, loan.id, loan.title))
        return card

    def loan_menu(self, card, point, loan_id, title):
        menu = QMenu(self)
        menu.setObjectName("loanMenu")
        remove = menu.addAction("حذف وام")
        selected = menu.exec(card.mapToGlobal(point))
        menu.deleteLater()
        if selected == remove and confirm_delete_loan(self, self.store, loan_id, title):
            self.notify_change()
            self.statusBar().showMessage("وام حذف شد.", 5000)

    @staticmethod
    def card_head(card, caption, state_text, state):
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label(caption, "small", wrap=True), 1)
        row.addWidget(badge(state_text, state))
        card.add(header)

    def notify_change(self):
        self.refresh()
        self.data_changed.emit()

    def new_check(self):
        form = EntryForm(self, self.store)
        if form.exec():
            self.go("checks")
            self.notify_change()
            self.statusBar().showMessage("چک ذخیره شد.", 5000)

    def new_loan(self):
        form = LoanForm(self, self.store)
        if form.exec():
            self.go("loans")
            self.notify_change()
            self.statusBar().showMessage("وام و اقساط آن ذخیره شدند.", 5000)

    def open_entry(self, entry_id):
        detail = EntryDetail(self, self.store, entry_id)
        detail.exec()
        if detail.changed:
            self.notify_change()

    def open_loan(self, loan_id):
        detail = LoanDetail(self, self.store, loan_id)
        detail.exec()
        if detail.changed:
            self.notify_change()

    def settings_page(self):
        options, layout = panel(spacing=10)
        layout.addWidget(label("یادآوری و اجرای خودکار", "heading"))
        layout.addWidget(label("زمان پیش‌فرض برای سندهایی که یادآوری جداگانه ندارند.", "muted", wrap=True))
        row = QHBoxLayout()
        self.lead = LeadField(self.default_days, None)
        row.addWidget(self.lead)
        row.addStretch()
        save = button("ذخیرهٔ زمان", "primary")
        save.clicked.connect(self.save_default)
        row.addWidget(save)
        layout.addLayout(row)
        layout.addWidget(label(
            f"زمان فعلی  •  {lead_label(self.default_days)}. از شروع بازه تا ثبت تسویه، هر ۳ ساعت اعلان می‌آید.",
            "small", wrap=True,
        ))
        toggle = QCheckBox("اجرای پس‌زمینه هنگام ورود به ویندوز")
        toggle.setEnabled(self.manage_startup)
        if self.manage_startup:
            try:
                toggle.setChecked(startup_enabled())
            except OSError:
                layout.addWidget(label("خواندن تنظیم اجرای خودکار ویندوز ممکن نشد.", "small", wrap=True))
        if self.startup_error:
            layout.addWidget(label(self.startup_error, "small", wrap=True))
        toggle.toggled.connect(self.save_startup)
        layout.addWidget(toggle)
        test = button("آزمایش اعلان سیستم", icon=symbol("calendar"))
        test.setEnabled(self.background_available)
        test.clicked.connect(self.test_requested.emit)
        layout.addWidget(test, 0, Qt.AlignmentFlag.AlignRight)
        self.body.addWidget(options)

        files, files_body = panel(spacing=10)
        files_body.addWidget(label("داده‌ها", "heading"))
        files_body.addWidget(label(
            "نسخهٔ پشتیبان تمام وام‌ها، چک‌ها و سوابق را ذخیره می‌کند. خروجی CSV برای بررسی اقساط و چک‌هاست.",
            "muted", wrap=True,
        ))
        tools = QHBoxLayout()
        backup = button("ذخیرهٔ نسخهٔ پشتیبان")
        backup.clicked.connect(self.backup)
        export = button("خروجی CSV")
        export.clicked.connect(self.export)
        tools.addWidget(backup)
        tools.addWidget(export)
        tools.addStretch()
        files_body.addLayout(tools)
        path = label(str(self.store.path), "small", wrap=True)
        path.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        files_body.addWidget(path)
        self.body.addWidget(files)

    def save_default(self):
        if run_action(self, lambda: self.store.set_reminder_days(self.lead.value())):
            self.notify_change()
            self.statusBar().showMessage("زمان پیش‌فرض ذخیره شد.", 5000)

    def save_startup(self, enabled: bool):
        if run_action(self, lambda: set_startup(enabled)):
            self.startup_error = ""
            self.statusBar().showMessage("تنظیم اجرای خودکار ذخیره شد.", 5000)
        self.refresh()

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ نسخهٔ پشتیبان", f"shahtoot-{date.today()}.sqlite3", "SQLite (*.sqlite3)",
        )
        if path and run_action(self, lambda: self.store.backup(Path(path))):
            self.statusBar().showMessage("نسخهٔ پشتیبان ذخیره شد.", 5000)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "خروجی اسناد", f"shahtoot-{date.today()}.csv", "CSV (*.csv)",
        )
        if path and run_action(self, lambda: self.store.export(Path(path), date.today())):
            self.statusBar().showMessage("خروجی CSV ذخیره شد.", 5000)

    def closeEvent(self, event):
        if self.background_available:
            event.ignore()
            self.hide()
        else:
            super().closeEvent(event)
