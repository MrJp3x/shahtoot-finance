from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_ID, APP_NAME, VERSION
from .localization import fa, short_date
from .platform_services import (
    IS_WINDOWS, SingleInstance, registered_startup_command, set_startup, startup_command, taskbar_ready,
)
from .receipts import read_receipt
from .storage import CHECK, KIND_NAMES, OUTGOING, EntryDetails, LoanDetails, PaymentEvidence, Store
from .theme import apply_theme, brand_icon
from .window import MainWindow

log = logging.getLogger(__name__)


class DesktopApp(QObject):
    def __init__(
        self, app: QApplication, store: Store, serve_in_tray: bool, manage_startup: bool,
        startup_error: str, *, launched_at_login=False,
    ):
        super().__init__(app)
        self.app = app
        self.store = store
        self.login_reminder_pending = launched_at_login
        self.login_reminder_checked = False
        self.window = MainWindow(
            store, background_available=serve_in_tray, manage_startup=manage_startup, startup_error=startup_error,
        )
        self.window.data_changed.connect(self.check_reminders)
        self.window.test_requested.connect(self.test_notification)
        self.tray = None
        if serve_in_tray:
            app.setQuitOnLastWindowClosed(False)
            self.tray = QSystemTrayIcon(app.windowIcon(), self)
            menu = QMenu(self.window)
            menu.addAction("باز کردن حسابداری شاهتوت", self.show_window)
            menu.addAction("سررسیدها", self.window.show_due)
            menu.addSeparator()
            menu.addAction("خروج کامل", self.quit)
            self.tray.setContextMenu(menu)
            self.tray.setToolTip(APP_NAME)
            self.tray.activated.connect(self.tray_activated)
            self.tray.messageClicked.connect(self.window.show_due)
            self.tray.show()
            self.normal_icon = app.windowIcon()
            self.alert_icon = brand_icon(alert=True)
        self.timer = QTimer(self)
        self.timer.setInterval(15_000)
        self.timer.timeout.connect(self.check_reminders)
        self.timer.start()

    def show_window(self):
        if self.window.isMinimized():
            self.window.showNormal()
        else:
            self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def quit(self):
        if self.tray:
            self.tray.hide()
        self.app.quit()

    def test_notification(self):
        if self.tray and taskbar_ready() and QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(
                APP_NAME, "اعلان آزمایشی حسابداری شاهتوت", QSystemTrayIcon.MessageIcon.Information,
            )
            self.window.statusBar().showMessage("اعلان آزمایشی به سیستم ارسال شد.", 5000)
        else:
            self.window.statusBar().showMessage("ناحیهٔ اعلان سیستم در دسترس نیست.", 5000)

    def request_login_reminder(self):
        if not self.login_reminder_checked and not self.login_reminder_pending:
            self.login_reminder_pending = True
            self.check_reminders()

    def check_reminders(self):
        try:
            now = datetime.now().astimezone()
            today = now.date()
            if self.window.today != today:
                self.window.refresh()
            if self.tray is None or not taskbar_ready() or not QSystemTrayIcon.isSystemTrayAvailable():
                return
            due_count = self.store.reminder_count(today)
            self.tray.setIcon(self.alert_icon if due_count else self.normal_icon)
            suffix = f" · {fa(due_count)} مورد برای پیگیری" if due_count else ""
            self.tray.setToolTip(f"{APP_NAME}{suffix}")
            if not QSystemTrayIcon.supportsMessages():
                return
            self.store.collect_reminders(
                now, at_startup=self.login_reminder_pending, deliver=lambda entries: self.show_reminders(entries, today),
            )
            self.login_reminder_checked = self.login_reminder_checked or self.login_reminder_pending
            self.login_reminder_pending = False
        except Exception:
            log.exception("Could not check reminders")

    def show_reminders(self, entries, today):
        near_dates = {today: "امروز", today + timedelta(days=1): "فردا"}
        upcoming = sorted(entries, key=lambda entry: (entry.due_on not in near_dates, entry.due_on))
        lines = []
        for entry in upcoming[:3]:
            due = near_dates.get(entry.due_on, short_date(entry.due_on))
            lines.append(f"{KIND_NAMES[entry.kind]} {entry.title[:40]} · سررسید {due}")
        if len(upcoming) > 3:
            lines.append(f"{fa(len(upcoming) - 3)} مورد دیگر در بخش سررسیدها")
        self.tray.showMessage(
            f"{fa(len(upcoming))} سررسید برای پیگیری",
            "\n".join(lines), QSystemTrayIcon.MessageIcon.Warning,
        )


def register_startup(store: Store) -> str:
    if not IS_WINDOWS:
        return ""
    configured = store.setting("startup_configured", 0)
    try:
        registered = registered_startup_command()
        if (registered is None and not configured) or (registered is not None and registered != startup_command()):
            set_startup(True)
    except (OSError, ValueError):
        log.exception("Could not register Windows startup")
        return "اجرای خودکار فعال نشد. تنظیم اجرای پس‌زمینه را در برنامه بررسی کنید."
    if not configured:
        store.set_setting("startup_configured", 1)
    return ""


def configure_logging(path: Path):
    logger = logging.getLogger()
    handler = RotatingFileHandler(path, maxBytes=500_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def smoke_test(app: QApplication) -> int:
    with TemporaryDirectory(prefix="shahtoot-smoke-") as folder:
        store = Store(Path(folder) / "finance.sqlite3")
        try:
            today = date.today()
            store.create_loan(LoanDetails("وام آزمایشی", "بانک نمونه", 100_000, today), today, 2, 50_000)
            check = store.create(EntryDetails(CHECK, OUTGOING, "چک آزمایشی", "فروشنده", 10_000, today))[0]
            now = datetime.now().astimezone()
            if len(store.collect_reminders(now)) != 2 or store.collect_reminders(now):
                raise RuntimeError("Smoke test did not produce one reminder per due entry in the interval")
            sample = QImage(4, 4, QImage.Format.Format_RGB32)
            sample.fill(Qt.GlobalColor.white)
            receipt = Path(folder) / "receipt.jpg"
            if not sample.save(str(receipt)):
                raise RuntimeError("JPEG receipt support is missing from the app")
            evidence = PaymentEvidence("001234", read_receipt(receipt))
            store.settle(check.id, today, evidence=evidence)
            if store.payment_evidence(check.id) != evidence:
                raise RuntimeError("Receipt data could not be read back")
            window = MainWindow(store, background_available=False)
            window.show()
            app.processEvents()
            for page in ("loans", "checks", "due", "report", "settings"):
                window.go(page)
                app.processEvents()
            window.close()
            return 0
        finally:
            store.engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--background", action="store_true", help="Start in the system tray")
    parser.add_argument("--data-dir", type=Path, help="Use a separate data directory")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    apply_theme(app)
    app.setWindowIcon(brand_icon())
    if args.smoke_test:
        return smoke_test(app)

    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    instance = None
    store = None
    try:
        if args.data_dir is None and not location:
            raise OSError("Application data directory is unavailable")
        data_dir = (args.data_dir or Path(location)).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        instance = SingleInstance(data_dir)
        if not instance.acquire():
            if not instance.request_activation(at_login=args.background) and not args.background:
                QMessageBox.warning(None, APP_NAME, "برنامه در حال اجراست. آن را از کنار ساعت باز کنید.")
            return 0

        configure_logging(data_dir / "app.log")
        store = Store(data_dir / "finance.sqlite3")
        tray_available = IS_WINDOWS or QSystemTrayIcon.isSystemTrayAvailable()
        manage_startup = IS_WINDOWS and args.data_dir is None
        error = register_startup(store) if manage_startup and not args.background else ""
        desktop = DesktopApp(app, store, tray_available, manage_startup, error, launched_at_login=args.background)
        instance.activated.connect(desktop.show_window)
        instance.login_requested.connect(desktop.request_login_reminder)
        if not args.background or not tray_available:
            desktop.show_window()
        QTimer.singleShot(8000 if args.background else 1300, desktop.check_reminders)
        return app.exec()
    except Exception:
        log.exception("Application startup failed")
        QMessageBox.critical(None, APP_NAME, "برنامه باز نشد. دسترسی نوشتن به پوشهٔ داده‌ها را بررسی کنید.")
        return 1
    finally:
        if store is not None:
            store.engine.dispose()
        if instance is not None:
            instance.close()
