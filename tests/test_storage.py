import csv
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shahtoot_finance.localization import monthly_dates, parse_date, short_date
from shahtoot_finance.storage import (
    CHECK, OUTGOING, EntryDetails, LoanDetails, Store, is_due, lead_time,
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

    def test_daily_reminders_are_persistent_and_stop_at_payment(self):
        due = date.today() - timedelta(days=2)
        start = due - timedelta(days=3)
        entry = self.store.create(self.check(due=due, lead=3))[0]
        self.assertEqual(self.store.collect_reminders(start - timedelta(days=1)), [])
        self.assertEqual([e.id for e in self.store.collect_reminders(start)], [entry.id])
        self.store.engine.dispose()
        reopened = Store(self.path)
        self.addCleanup(reopened.engine.dispose)
        self.assertEqual(reopened.collect_reminders(start), [])
        self.assertEqual([e.id for e in reopened.collect_reminders(start + timedelta(days=1))], [entry.id])
        self.assertEqual([e.id for e in reopened.collect_reminders(date.today())], [entry.id])
        reopened.settle(entry.id, date.today())
        self.assertEqual(reopened.collect_reminders(date.today() + timedelta(days=1)), [])

    def test_due_day_only_and_change_of_due_date(self):
        details = self.check(lead=0)
        entry = self.store.create(details)[0]
        self.assertFalse(is_due(entry, self.first_due - timedelta(days=1), 7))
        self.assertEqual(len(self.store.collect_reminders(self.first_due)), 1)
        self.store.edit(entry.id, replace(details, due_on=self.first_due - timedelta(days=1)))
        self.assertEqual(len(self.store.collect_reminders(self.first_due)), 1)

    def test_backup_copies_loans_and_csv_preserves_untrusted_text(self):
        loan_id = self.store.create_loan(self.loan, self.first_due, 2, 10_000_000)
        self.store.create(self.check(title="=1+2"))
        backup_path = self.path.with_name("backup.sqlite3")
        self.store.backup(backup_path)
        backup = Store(backup_path)
        self.addCleanup(backup.engine.dispose)
        self.store.delete_loan(loan_id)
        self.assertEqual(len(self.store.entries()), 1)
        self.assertEqual(len(backup.loan(loan_id).installments), 2)

        csv_path = self.path.with_suffix(".csv")
        self.store.export(csv_path, date.today())
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            header, check = csv.reader(file)
        self.assertIn("مبلغ (تومان)", header)
        self.assertEqual(check[3], "'=1+2")
        self.assertEqual(check[5], "2000000")


if __name__ == "__main__":
    unittest.main()
