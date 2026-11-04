import calendar
from datetime import date, timedelta

from app.utils.texts import WEEKDAYS_RU


def day_label(day: date) -> str:
    """'пн 02.11'"""
    return f"{WEEKDAYS_RU[day.weekday()]} {day:%d.%m}"


def next_days(today: date, count: int = 14) -> list[date]:
    return [today + timedelta(days=i) for i in range(count)]


def earliest_booking_day(today: date) -> date:
    """Clients can only book from the next local day: today is closed."""
    return today + timedelta(days=1)


def bookable_days(today: date, count: int = 14) -> list[date]:
    return next_days(earliest_booking_day(today), count)


def export_period(period: str, today: date) -> tuple[date, date]:
    """Inclusive local-date range for an export period button:
    "today" = today; "week" = "7 дней" = today through today+6;
    "month" = the current calendar month (1st to last day)."""
    if period == "today":
        return today, today
    if period == "week":
        return today, today + timedelta(days=6)
    if period == "month":
        last = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=1), today.replace(day=last)
    raise ValueError(f"unknown export period: {period}")
