from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile

from sqlalchemy import (
    CheckConstraint, Date, ForeignKey, Index, Integer, LargeBinary, String, Text,
    URL, create_engine, event, inspect, select,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, sessionmaker

from .localization import DATE_MAX, DATE_MIN, MAX_AMOUNT, monthly_dates, normalized, short_date

CHECK = "check"
INSTALLMENT = "installment"
OUTGOING = "outgoing"
INCOMING = "incoming"
DEFAULT_LEAD_DAYS = 7
MAX_LEAD_DAYS = 365
MAX_INSTALLMENTS = 120
DEFAULT_REMINDER_MINUTES = 180
MAX_REMINDER_MINUTES = 30 * 24 * 60
MAX_RECEIPT_BYTES = 10 * 1024 * 1024
DIRECTION_NAMES = {OUTGOING: "پرداختی", INCOMING: "دریافتی"}
KIND_NAMES = {CHECK: "چک", INSTALLMENT: "قسط"}


class Base(DeclarativeBase):
    pass


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint(f"principal BETWEEN 1 AND {MAX_AMOUNT}"),
        CheckConstraint(f"lead_days BETWEEN 0 AND {MAX_LEAD_DAYS}"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    bank: Mapped[str] = mapped_column(String(80))
    reference: Mapped[str] = mapped_column(String(80))
    received_on: Mapped[date] = mapped_column(Date)
    principal: Mapped[int] = mapped_column(Integer)
    lead_days: Mapped[int | None] = mapped_column()
    notes: Mapped[str] = mapped_column(Text)
    installments: Mapped[list[Entry]] = relationship(
        back_populates="loan", order_by="Entry.installment_number",
        cascade="all, delete-orphan", passive_deletes=True, lazy="raise",
    )


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (
        CheckConstraint("kind IN ('check','installment')"),
        CheckConstraint("direction IN ('outgoing','incoming')"),
        CheckConstraint(f"amount BETWEEN 1 AND {MAX_AMOUNT}"),
        CheckConstraint(f"lead_days BETWEEN 0 AND {MAX_LEAD_DAYS}"),
        Index("ix_entries_unsettled_due", "settled_on", "due_on"),
        Index("ix_entries_loan_number", "loan_id", "installment_number", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))
    direction: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(100))
    party: Mapped[str] = mapped_column(String(100))
    reference: Mapped[str] = mapped_column(String(80))
    bank: Mapped[str] = mapped_column(String(80))
    amount: Mapped[int] = mapped_column(Integer)
    due_on: Mapped[date] = mapped_column(Date)
    lead_days: Mapped[int | None] = mapped_column()
    notes: Mapped[str] = mapped_column(Text)
    settled_on: Mapped[date | None] = mapped_column(Date)
    installment_number: Mapped[int | None] = mapped_column()
    installment_total: Mapped[int | None] = mapped_column()
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"))
    loan: Mapped[Loan | None] = relationship(back_populates="installments", lazy="joined")


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"

    entry_id: Mapped[int] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), primary_key=True,
    )
    due_on: Mapped[date] = mapped_column(Date)
    notified_at: Mapped[int] = mapped_column(Integer)


class SettlementProof(Base):
    __tablename__ = "settlement_proofs"

    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id", ondelete="CASCADE"), primary_key=True)
    tracking_number: Mapped[str] = mapped_column(String(80))
    image: Mapped[bytes | None] = mapped_column(LargeBinary)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column()


@dataclass(frozen=True)
class EntryDetails:
    kind: str
    direction: str
    title: str
    party: str
    amount: int
    due_on: date
    reference: str = ""
    bank: str = ""
    lead_days: int | None = None
    notes: str = ""


@dataclass(frozen=True)
class LoanDetails:
    title: str
    bank: str
    principal: int
    received_on: date
    reference: str = ""
    lead_days: int | None = None
    notes: str = ""


@dataclass(frozen=True)
class PaymentEvidence:
    tracking_number: str = ""
    image: bytes | None = None


def lead_time(entry: Entry, default: int) -> int:
    if entry.lead_days is None and entry.loan is not None and entry.loan.lead_days is not None:
        return entry.loan.lead_days
    return default if entry.lead_days is None else entry.lead_days


def is_due(entry: Entry, today: date, default: int) -> bool:
    return entry.settled_on is None and (entry.due_on - today).days <= lead_time(entry, default)


def status(entry: Entry, today: date, default: int) -> str:
    if entry.settled_on is not None:
        return "settled"
    if entry.due_on < today:
        return "late"
    if entry.due_on == today:
        return "today"
    return "soon" if is_due(entry, today, default) else "open"


def status_label(entry: Entry, today: date, default: int) -> str:
    return {
        "late": "معوق",
        "today": "سررسید امروز",
        "soon": "نزدیک سررسید",
        "open": "باز",
        "settled": "وصول‌شده" if entry.direction == INCOMING else "پرداخت‌شده",
    }[status(entry, today, default)]


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(URL.create("sqlite", database=str(path)))
        event.listen(self.engine, "connect", self._configure_connection)
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            columns = inspect(connection).get_columns("entries")
            if "loan_id" not in {column["name"] for column in columns}:
                connection.exec_driver_sql(
                    "ALTER TABLE entries ADD COLUMN loan_id INTEGER REFERENCES loans(id) ON DELETE CASCADE"
                )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_entries_loan_number "
                "ON entries (loan_id, installment_number)"
            )
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _configure_connection(connection, _record):
        with connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")

    def entries(self) -> list[Entry]:
        with self.session() as db:
            return list(db.scalars(select(Entry).order_by(Entry.due_on, Entry.id)))

    def report_banks(self) -> list[str]:
        with self.session() as db:
            return list(db.scalars(select(Entry.bank).distinct().order_by(Entry.bank)))

    def report_entries(self, start: date, end: date, bank: str | None = None) -> list[Entry]:
        if end < start:
            raise ValueError("تاریخ پایان گزارش باید در تاریخ شروع یا پس از آن باشد.")
        query = select(Entry).where(Entry.settled_on.is_(None), Entry.due_on.between(start, end))
        if bank is not None:
            query = query.where(Entry.bank == bank)
        with self.session() as db:
            return list(db.scalars(query.order_by(Entry.due_on, Entry.id)))

    def get(self, entry_id: int) -> Entry:
        with self.session() as db:
            return self._required_entry(db, entry_id)

    def loans(self) -> list[Loan]:
        with self.session() as db:
            return list(db.scalars(select(Loan).options(selectinload(Loan.installments)).order_by(Loan.id.desc())))

    def loan(self, loan_id: int) -> Loan:
        with self.session() as db:
            return self._required_loan(db, loan_id)

    @staticmethod
    def _required_loan(db, loan_id: int) -> Loan:
        loan = db.get(Loan, loan_id, options=(selectinload(Loan.installments),))
        if loan is None:
            raise ValueError("وام مورد نظر پیدا نشد.")
        return loan

    @staticmethod
    def _apply_loan(loan: Loan, details: LoanDetails):
        if not details.title.strip() or not details.bank.strip():
            raise ValueError("عنوان وام و نام بانک را وارد کنید.")
        if not 1 <= details.principal <= MAX_AMOUNT:
            raise ValueError("مبلغ اصل وام معتبر نیست.")
        if not DATE_MIN <= details.received_on <= DATE_MAX:
            raise ValueError("تاریخ دریافت وام خارج از محدوده است.")
        if details.lead_days is not None and not 0 <= details.lead_days <= MAX_LEAD_DAYS:
            raise ValueError("فاصلهٔ یادآوری معتبر نیست.")
        for field in ("principal", "received_on", "lead_days"):
            setattr(loan, field, getattr(details, field))
        for field in ("title", "bank", "reference", "notes"):
            setattr(loan, field, getattr(details, field).strip())

    def create_loan(self, details: LoanDetails, first_due: date, count: int, amount: int) -> int:
        if not 1 <= count <= MAX_INSTALLMENTS:
            raise ValueError("تعداد اقساط معتبر نیست.")
        if not DATE_MIN <= details.received_on <= first_due <= DATE_MAX:
            raise ValueError("تاریخ نخستین قسط باید در تاریخ دریافت وام یا پس از آن باشد.")
        dates = monthly_dates(first_due, count)
        with self.session.begin() as db:
            loan = Loan()
            self._apply_loan(loan, details)
            loan.installments = []
            for number, due_on in enumerate(dates, 1):
                entry = Entry(installment_number=number, installment_total=count)
                self._apply(entry, EntryDetails(
                    INSTALLMENT, OUTGOING, loan.title, loan.bank, amount, due_on,
                    reference=loan.reference, bank=loan.bank,
                ))
                loan.installments.append(entry)
            db.add(loan)
            db.flush()
            return loan.id

    def edit_loan(self, loan_id: int, details: LoanDetails):
        with self.session.begin() as db:
            loan = self._required_loan(db, loan_id)
            if any(entry.due_on < details.received_on for entry in loan.installments):
                raise ValueError("تاریخ دریافت وام باید در تاریخ سررسید اقساط یا پیش از آن باشد.")
            self._apply_loan(loan, details)
            for entry in loan.installments:
                entry.title = loan.title
                entry.party = entry.bank = loan.bank
                entry.reference = loan.reference

    def delete_loan(self, loan_id: int):
        with self.session.begin() as db:
            db.delete(self._required_loan(db, loan_id))

    @staticmethod
    def _required_entry(db, entry_id: int) -> Entry:
        entry = db.get(Entry, entry_id)
        if entry is None:
            raise ValueError("سند مورد نظر پیدا نشد.")
        return entry

    @staticmethod
    def _apply(entry: Entry, details: EntryDetails):
        if details.kind not in KIND_NAMES or details.direction not in DIRECTION_NAMES:
            raise ValueError("نوع سند معتبر نیست.")
        if not details.title.strip() or not details.party.strip():
            raise ValueError("عنوان و طرف حساب را وارد کنید.")
        if not 1 <= details.amount <= MAX_AMOUNT:
            raise ValueError("مبلغ معتبر نیست.")
        if not DATE_MIN <= details.due_on <= DATE_MAX:
            raise ValueError("تاریخ سررسید خارج از محدوده است.")
        if details.lead_days is not None and not 0 <= details.lead_days <= MAX_LEAD_DAYS:
            raise ValueError("فاصلهٔ یادآوری معتبر نیست.")
        for field in ("kind", "direction", "amount", "due_on", "lead_days"):
            setattr(entry, field, getattr(details, field))
        for field in ("title", "party", "reference", "bank", "notes"):
            setattr(entry, field, getattr(details, field).strip())

    def create(self, details: EntryDetails, count: int = 1) -> list[Entry]:
        if not 1 <= count <= MAX_INSTALLMENTS or (count != 1 and details.kind != INSTALLMENT):
            raise ValueError("تعداد اقساط معتبر نیست.")
        dates = [details.due_on] if count == 1 else monthly_dates(details.due_on, count)
        with self.session.begin() as db:
            entries = []
            for number, due_on in enumerate(dates, 1):
                entry = Entry()
                self._apply(entry, replace(details, due_on=due_on))
                if count > 1:
                    entry.installment_number = number
                    entry.installment_total = count
                entries.append(entry)
            db.add_all(entries)
        return entries

    def edit(self, entry_id: int, details: EntryDetails):
        with self.session.begin() as db:
            entry = self._required_entry(db, entry_id)
            if entry.kind != details.kind:
                raise ValueError("نوع سند ثبت‌شده قابل تغییر نیست.")
            if entry.loan is not None:
                if details.due_on < entry.loan.received_on:
                    raise ValueError("سررسید قسط باید در تاریخ دریافت وام یا پس از آن باشد.")
                details = replace(
                    details, direction=OUTGOING, title=entry.loan.title, party=entry.loan.bank,
                    bank=entry.loan.bank, reference=entry.loan.reference,
                )
            if entry.settled_on is not None and entry.direction != details.direction:
                raise ValueError("برای تغییر جهت سند تسویه‌شده، ابتدا تسویه را برگردانید.")
            self._apply(entry, details)

    def payment_evidence(self, entry_id: int) -> PaymentEvidence:
        with self.session() as db:
            proof = db.get(SettlementProof, entry_id)
            return PaymentEvidence(proof.tracking_number, proof.image) if proof else PaymentEvidence()

    def settle(self, entry_id: int, day: date | None, *, evidence: PaymentEvidence | None = None):
        if day is not None and not DATE_MIN <= day <= min(date.today(), DATE_MAX):
            raise ValueError("تاریخ تسویه باید امروز یا پیش از آن باشد.")
        tracking = evidence.tracking_number.strip() if evidence else ""
        image = evidence.image if evidence else None
        if len(tracking) > 80:
            raise ValueError("شمارهٔ پیگیری باید حداکثر ۸۰ نویسه باشد.")
        if image is not None and not 1 <= len(image) <= MAX_RECEIPT_BYTES:
            raise ValueError("حجم فایل رسید باید حداکثر ۱۰ مگابایت باشد.")
        with self.session.begin() as db:
            self._required_entry(db, entry_id).settled_on = day
            if day is None or evidence is not None:
                if day is not None and (tracking or image):
                    db.merge(SettlementProof(entry_id=entry_id, tracking_number=tracking, image=image))
                else:
                    proof = db.get(SettlementProof, entry_id)
                    if proof is not None:
                        db.delete(proof)

    def delete(self, entry_id: int):
        with self.session.begin() as db:
            entry = self._required_entry(db, entry_id)
            if entry.loan_id is not None:
                raise ValueError("این قسط بخشی از برنامهٔ بازپرداخت یک وام است.")
            db.delete(entry)

    def setting(self, key: str, default: int) -> int:
        with self.session() as db:
            setting = db.get(Setting, key)
            return default if setting is None else setting.value

    def set_setting(self, key: str, value: int):
        with self.session.begin() as db:
            db.merge(Setting(key=key, value=value))

    def reminder_days(self) -> int:
        return self.setting("reminder_days", DEFAULT_LEAD_DAYS)

    def reminder_minutes(self) -> int:
        return self.setting("reminder_minutes", DEFAULT_REMINDER_MINUTES)

    def set_reminder_settings(self, days: int, minutes: int):
        if not 0 <= days <= MAX_LEAD_DAYS:
            raise ValueError("فاصلهٔ یادآوری معتبر نیست.")
        if not 1 <= minutes <= MAX_REMINDER_MINUTES:
            raise ValueError("فاصلهٔ تکرار اعلان باید بین یک دقیقه و ۳۰ روز باشد.")
        with self.session.begin() as db:
            db.merge(Setting(key="reminder_days", value=days))
            db.merge(Setting(key="reminder_minutes", value=minutes))

    @staticmethod
    def _potential_reminders(today: date):
        return select(Entry).where(
            Entry.settled_on.is_(None), Entry.due_on <= today + timedelta(days=MAX_LEAD_DAYS),
        )

    def reminder_count(self, today: date) -> int:
        default = self.reminder_days()
        with self.session() as db:
            return sum(is_due(entry, today, default) for entry in db.scalars(self._potential_reminders(today)))

    def collect_reminders(
        self, now: datetime, *, at_startup=False, deliver: Callable[[list[Entry]], None] | None = None,
    ) -> list[Entry]:
        today = now.date()
        timestamp = int(now.timestamp())
        default = self.reminder_days()
        interval_seconds = self.reminder_minutes() * 60
        delivery = ReminderDelivery
        can_repeat = (
            (delivery.notified_at <= timestamp - interval_seconds)
            | (delivery.notified_at > timestamp)
        )
        with self.session.begin() as db:
            query = self._potential_reminders(today).order_by(Entry.due_on, Entry.id)
            if not at_startup:
                recent = select(delivery.entry_id).where(
                    delivery.entry_id == Entry.id, delivery.due_on == Entry.due_on, ~can_repeat,
                ).exists()
                query = query.where(~recent)
            fresh = []
            for entry in db.scalars(query):
                if is_due(entry, today, default):
                    record = insert(delivery).values(
                        entry_id=entry.id, due_on=entry.due_on, notified_at=timestamp,
                    )
                    record = record.on_conflict_do_update(
                        index_elements=[delivery.entry_id],
                        set_={"due_on": entry.due_on, "notified_at": timestamp},
                        where=None if at_startup else (delivery.due_on != entry.due_on) | can_repeat,
                    )
                    if db.execute(record).rowcount == 1:
                        fresh.append(entry)
            if fresh and deliver is not None:
                deliver(fresh)
        return fresh

    def backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            raise ValueError("برای نسخهٔ پشتیبان یک مسیر دیگر انتخاب کنید.")
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
        try:
            source = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                target = sqlite3.connect(temporary)
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def export(self, destination: Path, today: date):
        if destination.resolve() == self.path.resolve():
            raise ValueError("برای خروجی یک مسیر دیگر انتخاب کنید.")
        default = self.reminder_days()
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", dir=destination.parent, delete=False,
        ) as file:
            temporary = Path(file.name)
            try:
                writer = csv.writer(file)
                writer.writerow((
                    "شناسه", "نوع", "جهت", "عنوان", "طرف حساب", "مبلغ (تومان)",
                    "سررسید شمسی", "وضعیت", "تاریخ تسویهٔ شمسی",
                    "شماره یا شناسهٔ چک", "بانک", "شماره قسط", "تعداد اقساط", "یادداشت",
                ))
                for entry in self.entries():
                    writer.writerow((
                        entry.id, KIND_NAMES[entry.kind], DIRECTION_NAMES[entry.direction],
                        csv_text(entry.title), csv_text(entry.party), entry.amount,
                        short_date(entry.due_on), status_label(entry, today, default),
                        short_date(entry.settled_on) if entry.settled_on else "",
                        csv_text(entry.reference, preserve_digits=True), csv_text(entry.bank),
                        entry.installment_number or "", entry.installment_total or "",
                        csv_text(entry.notes),
                    ))
                file.close()
                temporary.replace(destination)
            finally:
                file.close()
                temporary.unlink(missing_ok=True)


def csv_text(value: str, *, preserve_digits: bool = False) -> str:
    text = value.lstrip()
    if text.startswith(("=", "+", "-", "@")) or (preserve_digits and normalized(text).isdigit()):
        return "'" + value
    return value
