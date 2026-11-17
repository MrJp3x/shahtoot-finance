from datetime import date
import re

from PySide6.QtCore import QCalendar, QDate

JALALI = QCalendar(QCalendar.System.Jalali)
MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)
WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")
FA_DIGITS = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")
ASCII_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك", "01234567890123456789یک")
DATE_MIN = JALALI.dateFromParts(1300, 1, 1).toPython()
DATE_MAX = JALALI.dateFromParts(1599, 12, JALALI.daysInMonth(12, 1599)).toPython()
MAX_AMOUNT = 999_999_999_999_999


def fa(value: object) -> str:
    return str(value).translate(FA_DIGITS)


def normalized(value: str) -> str:
    return value.translate(ASCII_DIGITS).replace("\u200c", "").strip().casefold()


def money(amount: int) -> str:
    return fa(f"{amount:,}")


def parse_money(text: str) -> int:
    raw = normalized(text).replace("٬", ",")
    if not re.fullmatch(r"[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+", raw):
        raise ValueError("مبلغ را به صورت عدد صحیح به تومان وارد کنید.")
    amount = int(raw.replace(",", ""))
    if not 1 <= amount <= MAX_AMOUNT:
        raise ValueError("مبلغ باید بیشتر از صفر و حداکثر ۱۵ رقمی باشد.")
    return amount


def qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


def short_date(day: date) -> str:
    part = JALALI.partsFromDate(qdate(day))
    return fa(f"{part.year:04d}/{part.month:02d}/{part.day:02d}")


def long_date(day: date) -> str:
    part = JALALI.partsFromDate(qdate(day))
    return fa(f"{WEEKDAYS[day.weekday()]}، {part.day} {MONTHS[part.month - 1]} {part.year}")


def parse_date(text: str) -> date:
    match = re.fullmatch(r"([0-9]{4})[/-]([0-9]{1,2})[/-]([0-9]{1,2})", normalized(text))
    if match:
        year, month, day = map(int, match.groups())
        result = JALALI.dateFromParts(year, month, day)
        if result.isValid() and 1300 <= year <= 1599:
            return result.toPython()
    raise ValueError("تاریخ شمسی معتبر وارد کنید. نمونه: ۱۴۰۵/۰۸/۲۶")


def monthly_dates(first: date, count: int) -> list[date]:
    part = JALALI.partsFromDate(qdate(first))
    result = []
    for offset in range(count):
        year_offset, month_index = divmod(part.month - 1 + offset, 12)
        year, month = part.year + year_offset, month_index + 1
        day = min(part.day, JALALI.daysInMonth(month, year))
        result.append(JALALI.dateFromParts(year, month, day).toPython())
    if any(day < DATE_MIN or day > DATE_MAX for day in result):
        raise ValueError("سررسید قسط‌ها از محدودهٔ تاریخ برنامه خارج می‌شود.")
    return result
