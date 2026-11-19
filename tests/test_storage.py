import csv
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shahtoot_finance.localization import monthly_dates, parse_date, short_date
from shahtoot_finance.report import Totals, totals_for, week_start
from shahtoot_finance.storage import (
    CHECK, INCOMING, OUTGOING, EntryDetails, LoanDetails, PaymentEvidence, Store, is_due, lead_time,
)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "finance.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.engine.dispose)
        self.received = parse_date("1405/06/01")
        self.first_due = parse_date("1405/06/31")
        self.loan = LoanDetails("خرید تجهیزات", "بانک نمونه", 80_000_000, self.received, lead_days=3)

    def check(self, *, title="چک خرید", due=None, lead=None):
        return EntryDetails(CHECK, OUTGOING, title, "فروشنده", 2_000_000, due or self.first_due, lead_days=lead)

    def test_jalali_schedule_preserves_original_day_when_month_length_allows(self):
        dates = monthly_dates(self.first_due, 8)
        self.assertEqual(short_date(dates[1]), "۱۴۰۵/۰۷/۳۰")
        self.assertEqual(short_date(dates[7]), "۱۴۰۶/۰۱/۳۱")
        loan_id = self.store.create_loan(self.loan, self.first_due, 8, 10_000_000)
        loan = self.store.loan(loan_id)
        self.assertEqual([entry.due_on for entry in loan.installments], dates)
        self.assertEqual(lead_time(loan.installments[0], 7), 3)
        self.assertEqual(loan.installments[-1].installment_number, 8)

    def test_loan_creation_rolls_back_if_amount_invalid(self):
        with self.assertRaises(ValueError):
            self.store.create_loan(self.loan, self.first_due, 2, 0)
        self.assertEqual(self.store.loans(), [])
        self.assertEqual(self.store.entries(), [])

    def test_loan_updates_propagate_but_installment_override_takes_precedence(self):
        loan_id = self.store.create_loan(self.loan, self.first_due, 2, 10_000_000)
        first, second = self.store.loan(loan_id).installments
        self.store.edit(first.id, EntryDetails(
            first.kind, first.direction, first.title, first.party, first.amount, first.due_on,
            lead_days=1, notes="پرداخت از حساب شعبه",
        ))
        self.store.edit_loan(loan_id, replace(self.loan, title="تجهیزات شعبه", bank="بانک دوم", lead_days=0))
        self.assertEqual(self.store.get(first.id).notes, "پرداخت از حساب شعبه")
        self.assertEqual(lead_time(self.store.get(first.id), 7), 1)
        self.assertEqual(lead_time(self.store.get(second.id), 7), 0)
        self.assertEqual(self.store.get(second.id).title, "تجهیزات شعبه")
        self.assertEqual(self.store.get(second.id).bank, "بانک دوم")

    def test_three_hour_reminders_persist_across_midnight_and_stop_at_payment(self):
        due = date.today() - timedelta(days=2)
        start = datetime.combine(due - timedelta(days=3), time(23), timezone.utc)
        entry = self.store.create(self.check(due=due, lead=3))[0]
        self.assertEqual(self.store.collect_reminders(start - timedelta(days=1)), [])
        self.assertEqual([e.id for e in self.store.collect_reminders(start)], [entry.id])
        self.store.engine.dispose()
        reopened = Store(self.path)
        self.addCleanup(reopened.engine.dispose)
        self.assertEqual(reopened.collect_reminders(start + timedelta(hours=2, minutes=59)), [])
        self.assertEqual([e.id for e in reopened.collect_reminders(start + timedelta(hours=3))], [entry.id])
        self.assertEqual([e.id for e in reopened.collect_reminders(start + timedelta(days=5))], [entry.id])
        reopened.settle(entry.id, date.today())
        self.assertEqual(reopened.collect_reminders(start + timedelta(days=6), at_startup=True), [])

    def test_login_reminds_about_tomorrows_installment_and_restarts_interval(self):
        loan_id = self.store.create_loan(replace(self.loan, lead_days=1), self.first_due, 2, 10_000_000)
        first = self.store.loan(loan_id).installments[0]
        before_due = datetime.combine(first.due_on - timedelta(days=1), time(8), timezone.utc)
        self.assertEqual([e.id for e in self.store.collect_reminders(before_due)], [first.id])

        login = before_due + timedelta(hours=1)
        self.assertEqual(self.store.collect_reminders(login), [])
        self.assertEqual([e.id for e in self.store.collect_reminders(login, at_startup=True)], [first.id])
        self.assertEqual(self.store.collect_reminders(login + timedelta(hours=2)), [])
        self.assertEqual([e.id for e in self.store.collect_reminders(login + timedelta(hours=3))], [first.id])

    def test_two_hour_interval_persists_and_failed_dispatch_is_retried(self):
        entry = self.store.create(self.check(lead=1))[0]
        login = datetime.combine(entry.due_on - timedelta(days=1), time(8), timezone.utc)
        self.store.set_reminder_settings(7, 120)
        reopened = Store(self.path)
        self.addCleanup(reopened.engine.dispose)
        self.assertEqual(reopened.reminder_minutes(), 120)

        def failed_dispatch(entries):
            self.assertEqual([item.id for item in entries], [entry.id])
            raise OSError("tray unavailable")

        with self.assertRaises(OSError):
            reopened.collect_reminders(login, at_startup=True, deliver=failed_dispatch)
        delivered = []
        reopened.collect_reminders(login, deliver=delivered.extend)
        self.assertEqual([item.id for item in delivered], [entry.id])
        self.assertEqual(reopened.collect_reminders(login + timedelta(minutes=119, seconds=59)), [])
        self.assertEqual([item.id for item in reopened.collect_reminders(login + timedelta(hours=2))], [entry.id])
        reopened.settle(entry.id, date.today())
        self.assertEqual(reopened.collect_reminders(login + timedelta(hours=4), at_startup=True), [])

    def test_upgrade_preserves_previous_entries_and_rechecks_daily_reminders_at_login(self):
        entry = self.store.create(self.check(lead=1))[0]
        login = datetime.combine(entry.due_on - timedelta(days=1), time(8), timezone.utc)
        with self.store.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE reminder_deliveries")
            connection.exec_driver_sql(
                "CREATE TABLE reminders (entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE, "
                "due_on DATE NOT NULL, notified_on DATE NOT NULL, PRIMARY KEY (entry_id, due_on, notified_on))"
            )
            connection.exec_driver_sql("INSERT INTO reminders VALUES (?, ?, ?)", (entry.id, entry.due_on, login.date()))
        reopened = Store(self.path)
        self.addCleanup(reopened.engine.dispose)
        self.assertEqual(reopened.get(entry.id).amount, entry.amount)
        self.assertEqual([e.id for e in reopened.collect_reminders(login, at_startup=True)], [entry.id])
        self.assertEqual(reopened.collect_reminders(login), [])

    def test_due_day_only_and_change_of_due_date(self):
        details = self.check(lead=0)
        entry = self.store.create(details)[0]
        self.assertFalse(is_due(entry, self.first_due - timedelta(days=1), 7))
        now = datetime.combine(self.first_due, time(10), timezone.utc)
        self.assertEqual(self.store.collect_reminders(now - timedelta(days=1), at_startup=True), [])
        self.assertEqual(len(self.store.collect_reminders(now)), 1)
        self.store.edit(entry.id, replace(details, due_on=self.first_due - timedelta(days=1)))
        self.assertEqual(len(self.store.collect_reminders(now)), 1)

    def test_backup_copies_loans_and_csv_preserves_untrusted_text(self):
        loan_id = self.store.create_loan(self.loan, self.first_due, 2, 10_000_000)
        self.store.create(self.check(title="=1+2"))
        when = datetime.combine(self.first_due, time(10), timezone.utc)
        self.assertEqual(len(self.store.collect_reminders(when)), 2)
        backup_path = self.path.with_name("backup.sqlite3")
        self.store.backup(backup_path)
        backup = Store(backup_path)
        self.addCleanup(backup.engine.dispose)
        self.store.delete_loan(loan_id)
        self.assertEqual(len(self.store.entries()), 1)
        self.assertEqual(len(backup.loan(loan_id).installments), 2)
        self.assertEqual(len(self.store.collect_reminders(when, at_startup=True)), 1)

        csv_path = self.path.with_suffix(".csv")
        self.store.export(csv_path, date.today())
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            header, check = csv.reader(file)
        self.assertIn("مبلغ (تومان)", header)
        self.assertEqual(check[3], "'=1+2")
        self.assertEqual(check[5], "2000000")

    def test_report_filters_open_entries_including_both_ends_and_totals_by_direction(self):
        start = self.first_due
        end = start + timedelta(days=29)
        self.store.create_loan(self.loan, start, 1, 10_000_000)
        self.store.create(replace(self.check(due=end), bank=self.loan.bank))
        self.store.create(replace(self.check(due=end), direction=INCOMING))
        self.store.create(self.check(due=start - timedelta(days=1)))
        self.store.create(self.check(due=end + timedelta(days=1)))
        paid = self.store.create(self.check(due=start))[0]
        self.store.settle(paid.id, date.today())

        entries = self.store.report_entries(start, end)
        self.assertEqual([entry.due_on for entry in entries], [start, end, end])
        self.assertEqual(totals_for(entries), Totals(10_000_000, 2_000_000, 2_000_000))
        self.assertEqual(totals_for(entries).outgoing, 12_000_000)
        self.assertEqual(len(self.store.report_entries(start, end, self.loan.bank)), 2)
        self.assertEqual(len(self.store.report_entries(start, end, "")), 1)
        self.assertEqual(self.store.report_banks(), ["", self.loan.bank])
        self.assertEqual(week_start(date(2026, 11, 20)), date(2026, 11, 14))
        self.assertEqual(week_start(date(2026, 11, 21)), date(2026, 11, 21))
        with self.assertRaises(ValueError):
            self.store.report_entries(end, start)

    def test_payment_evidence_upgrade_edit_backup_and_reversal(self):
        entry = self.store.create(self.check())[0]
        self.store.settle(entry.id, date.today())
        with self.store.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE settlement_proofs")
        reopened = Store(self.path)
        self.addCleanup(reopened.engine.dispose)
        self.assertEqual(reopened.get(entry.id).settled_on, date.today())
        self.assertEqual(reopened.payment_evidence(entry.id), PaymentEvidence())

        evidence = PaymentEvidence("001234567", b"receipt image bytes")
        reopened.settle(entry.id, date.today(), evidence=evidence)
        reopened.settle(entry.id, date.today())
        self.assertEqual(reopened.payment_evidence(entry.id), evidence)
        backup_path = self.path.with_name("with-receipts.sqlite3")
        reopened.backup(backup_path)
        backup = Store(backup_path)
        self.addCleanup(backup.engine.dispose)
        self.assertEqual(backup.payment_evidence(entry.id), evidence)
        reopened.settle(entry.id, date.today(), evidence=PaymentEvidence("0059"))
        self.assertEqual(reopened.payment_evidence(entry.id), PaymentEvidence("0059"))
        reopened.settle(entry.id, None)
        self.assertIsNone(reopened.get(entry.id).settled_on)
        self.assertEqual(reopened.payment_evidence(entry.id), PaymentEvidence())


if __name__ == "__main__":
    unittest.main()
