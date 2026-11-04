from datetime import date

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Service
from app.services.slots import WorkDay
from app.utils import texts
from app.utils.dates import day_label


class AdmMenuCb(CallbackData, prefix="adm"):
    # menu | schedule | dayoff | daysoff | services | bookings | export
    action: str


class AdmWeekdayCb(CallbackData, prefix="admwd"):
    weekday: int  # 0=Mon
    action: str  # pick | off | off_yes (confirmed) | save_yes (hours confirmed)


class AdmDayCb(CallbackData, prefix="admday"):
    # off (day chosen) | off_yes (confirmed) | list (bookings of day) | reopen
    kind: str
    day: str  # ISO date


class AdmBookingCb(CallbackData, prefix="admbk"):
    booking_id: int
    action: str  # cancel (ask) | cancel_yes


class AdmServiceCb(CallbackData, prefix="admsvc"):
    service_id: int  # 0 for "add"
    action: str  # open | add | title | duration | price | hide


class AdmExportCb(CallbackData, prefix="admexp"):
    period: str  # today | week | month
    fmt: str  # "" (choose format) | xlsx | gsheet


def _back_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=texts.ADMIN_BTN_BACK, callback_data=AdmMenuCb(action="menu").pack()
    )


def _back(b: InlineKeyboardBuilder) -> None:
    b.row(_back_button())


def admin_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, action in (
        (texts.ADMIN_BTN_SCHEDULE, "schedule"),
        (texts.ADMIN_BTN_DAYOFF, "dayoff"),
        (texts.ADMIN_BTN_DAYSOFF, "daysoff"),
        (texts.ADMIN_BTN_SERVICES, "services"),
        (texts.ADMIN_BTN_BOOKINGS, "bookings"),
        (texts.ADMIN_BTN_EXPORT, "export"),
    ):
        b.button(text=text, callback_data=AdmMenuCb(action=action))
    b.adjust(1)
    return b.as_markup()


def describe_work_day(work: WorkDay | None) -> str:
    if work is None:
        return texts.ADMIN_WEEKDAY_OFF
    value = f"{work.start:%H:%M}-{work.end:%H:%M}"
    if work.break_start is not None and work.break_end is not None:
        value += f" ({work.break_start:%H:%M}-{work.break_end:%H:%M})"
    return value


def schedule_kb(schedule: dict[int, WorkDay]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for weekday, name in enumerate(texts.WEEKDAYS_RU):
        b.button(
            text=f"{name} {describe_work_day(schedule.get(weekday))}",
            callback_data=AdmWeekdayCb(weekday=weekday, action="pick"),
        )
    b.adjust(1)
    _back(b)
    return b.as_markup()


def weekday_prompt_kb(weekday: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text=texts.ADMIN_WEEKDAY_OFF_BTN,
        callback_data=AdmWeekdayCb(weekday=weekday, action="off"),
    )
    b.adjust(1)
    _back(b)
    return b.as_markup()


def days_kb(days: list[date], kind: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in days:
        b.button(text=day_label(d), callback_data=AdmDayCb(kind=kind, day=d.isoformat()))
    b.adjust(2)
    b.row(_back_button())
    return b.as_markup()


def dayoff_confirm_kb(day: date, has_bookings: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text=texts.ADMIN_DAYOFF_YES_BTN
        if has_bookings
        else texts.ADMIN_DAYOFF_YES_EMPTY_BTN,
        callback_data=AdmDayCb(kind="off_yes", day=day.isoformat()),
    )
    b.adjust(1)
    _back(b)
    return b.as_markup()


def daysoff_kb(days: list[date]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in days:
        b.button(
            text=texts.ADMIN_DAYOFF_REOPEN_BTN.format(date=day_label(d)),
            callback_data=AdmDayCb(kind="reopen", day=d.isoformat()),
        )
    b.adjust(2)
    b.row(_back_button())
    return b.as_markup()


def schedule_confirm_kb(weekday: int, action: str) -> InlineKeyboardMarkup:
    """Confirm a schedule change that strands bookings; 'No' returns to the schedule."""
    b = InlineKeyboardBuilder()
    b.button(
        text=texts.ADMIN_SCHEDULE_SAVE_YES_BTN,
        callback_data=AdmWeekdayCb(weekday=weekday, action=action),
    )
    b.button(text=texts.CANCEL_NO_BUTTON, callback_data=AdmMenuCb(action="schedule"))
    b.adjust(1)
    return b.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _back(b)
    return b.as_markup()


def day_bookings_kb(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """items: (booking_id, 'HH:MM')."""
    b = InlineKeyboardBuilder()
    for booking_id, when in items:
        b.button(
            text=texts.ADMIN_CANCEL_BTN.format(time=when),
            callback_data=AdmBookingCb(booking_id=booking_id, action="cancel"),
        )
    b.adjust(2)
    b.row(_back_button())
    return b.as_markup()


def booking_cancel_confirm_kb(booking_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text=texts.CANCEL_YES_BUTTON,
        callback_data=AdmBookingCb(booking_id=booking_id, action="cancel_yes"),
    )
    b.button(text=texts.CANCEL_NO_BUTTON, callback_data=AdmMenuCb(action="menu"))
    b.adjust(1)
    return b.as_markup()


def services_admin_kb(services: list[Service]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in services:
        mark = "" if s.is_active else texts.ADMIN_SERVICE_HIDDEN_MARK
        b.button(
            text=s.title + mark,
            callback_data=AdmServiceCb(service_id=s.id, action="open"),
        )
    b.button(
        text=texts.ADMIN_SERVICE_ADD_BTN,
        callback_data=AdmServiceCb(service_id=0, action="add"),
    )
    b.adjust(1)
    _back(b)
    return b.as_markup()


def service_card_kb(service: Service) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, action in (
        (texts.ADMIN_SERVICE_EDIT_TITLE_BTN, "title"),
        (texts.ADMIN_SERVICE_EDIT_DURATION_BTN, "duration"),
        (texts.ADMIN_SERVICE_EDIT_PRICE_BTN, "price"),
    ):
        b.button(
            text=text, callback_data=AdmServiceCb(service_id=service.id, action=action)
        )
    if service.is_active:
        b.button(
            text=texts.ADMIN_SERVICE_HIDE_BTN,
            callback_data=AdmServiceCb(service_id=service.id, action="hide"),
        )
    b.button(text=texts.ADMIN_BTN_SERVICES, callback_data=AdmMenuCb(action="services"))
    b.adjust(3, 1)
    return b.as_markup()


def export_period_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, period in (
        (texts.EXPORT_BTN_TODAY, "today"),
        (texts.EXPORT_BTN_WEEK, "week"),
        (texts.EXPORT_BTN_MONTH, "month"),
    ):
        b.button(text=text, callback_data=AdmExportCb(period=period, fmt=""))
    b.adjust(3)
    _back(b)
    return b.as_markup()


def export_format_kb(period: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, fmt in (
        (texts.EXPORT_BTN_EXCEL, "xlsx"),
        (texts.EXPORT_BTN_GSHEET, "gsheet"),
    ):
        b.button(text=text, callback_data=AdmExportCb(period=period, fmt=fmt))
    b.adjust(2)
    _back(b)
    return b.as_markup()
