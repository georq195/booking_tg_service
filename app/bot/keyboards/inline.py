from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Booking, Service
from app.utils import texts
from app.utils.dates import day_label


class ServiceCb(CallbackData, prefix="svc"):
    service_id: int


class DateCb(CallbackData, prefix="date"):
    day: str  # ISO date


class SlotCb(CallbackData, prefix="slot"):
    ts: int  # UTC epoch seconds


class ConfirmCb(CallbackData, prefix="ok"):
    pass


class BookingCb(CallbackData, prefix="bk"):
    booking_id: int
    # cancel (ask) | cancel_yes | move | back (to the list, booking_id unused)
    action: str


def services_kb(services: list[Service]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in services:
        b.button(text=s.title, callback_data=ServiceCb(service_id=s.id))
    b.adjust(1)
    return b.as_markup()


def dates_kb(days: list[date]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in days:
        b.button(text=day_label(d), callback_data=DateCb(day=d.isoformat()))
    b.adjust(2)
    return b.as_markup()


def slots_kb(slots: list[datetime], tz: ZoneInfo) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in slots:
        b.button(
            text=s.astimezone(tz).strftime("%H:%M"),
            callback_data=SlotCb(ts=int(s.timestamp())),
        )
    b.adjust(3)
    return b.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.CONFIRM_BUTTON, callback_data=ConfirmCb())
    return b.as_markup()


def my_bookings_kb(bookings: list[Booking], tz: ZoneInfo) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for booking in bookings:
        local = booking.start_at.astimezone(tz)
        when = f"{local:%d.%m %H:%M}"
        b.button(
            text=texts.CANCEL_BUTTON.format(when=when),
            callback_data=BookingCb(booking_id=booking.id, action="cancel"),
        )
        b.button(
            text=texts.MOVE_BUTTON.format(when=when),
            callback_data=BookingCb(booking_id=booking.id, action="move"),
        )
    b.adjust(2)
    return b.as_markup()


def cancel_confirm_kb(booking_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text=texts.CANCEL_YES_BUTTON,
        callback_data=BookingCb(booking_id=booking_id, action="cancel_yes"),
    )
    b.button(
        text=texts.CANCEL_NO_BUTTON,
        callback_data=BookingCb(booking_id=booking_id, action="back"),
    )
    b.adjust(1)
    return b.as_markup()
