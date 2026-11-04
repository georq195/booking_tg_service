from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.filters import IsAdmin, IsPrivateChat
from app.bot.handlers.admin.common import not_notified_names, notify_cancelled, show
from app.bot.keyboards.admin import (
    AdmBookingCb,
    AdmDayCb,
    AdmMenuCb,
    back_kb,
    booking_cancel_confirm_kb,
    day_bookings_kb,
    days_kb,
)
from app.services.booking_service import BookingService
from app.services.errors import AlreadyCancelled, BookingNotFound
from app.utils import texts
from app.utils.dates import day_label, next_days


async def on_bookings_open(
    callback: CallbackQuery, state: FSMContext, booking_service: BookingService
) -> None:
    await callback.answer()
    await state.clear()
    today = datetime.now(booking_service.tz).date()
    await show(callback, texts.ADMIN_BTN_BOOKINGS, days_kb(next_days(today), "list"))


async def on_day(
    callback: CallbackQuery, callback_data: AdmDayCb, booking_service: BookingService
) -> None:
    await callback.answer()
    day = date.fromisoformat(callback_data.day)
    bookings = await booking_service.list_for_day(day)
    if not bookings:
        await show(
            callback, texts.ADMIN_NO_BOOKINGS.format(date=day_label(day)), back_kb()
        )
        return
    details = await booking_service.booking_details([b.id for b in bookings])
    tz = booking_service.tz
    lines = [texts.ADMIN_DAY_BOOKINGS.format(date=day_label(day))]
    lines += [texts.format_booking_line(d.booking, d.user, d.service, tz) for d in details]
    buttons = [
        (d.booking.id, f"{d.booking.start_at.astimezone(tz):%H:%M}") for d in details
    ]
    await show(callback, "\n".join(lines), day_bookings_kb(buttons))


async def on_cancel_ask(
    callback: CallbackQuery, callback_data: AdmBookingCb, booking_service: BookingService
) -> None:
    await callback.answer()
    details = await booking_service.booking_details([callback_data.booking_id])
    if not details:
        await show(callback, texts.BOOKING_NOT_FOUND, back_kb())
        return
    d = details[0]
    line = texts.format_booking_line(d.booking, d.user, d.service, booking_service.tz)
    await show(
        callback,
        texts.ADMIN_CANCEL_ASK.format(line=line),
        booking_cancel_confirm_kb(d.booking.id),
    )


async def on_cancel_yes(
    callback: CallbackQuery,
    callback_data: AdmBookingCb,
    booking_service: BookingService,
    bot: Bot,
) -> None:
    await callback.answer()
    try:
        await booking_service.admin_cancel(callback_data.booking_id)
    except AlreadyCancelled:
        await show(callback, texts.ALREADY_CANCELLED, back_kb())
        return
    except BookingNotFound:
        await show(callback, texts.BOOKING_NOT_FOUND, back_kb())
        return
    details = await booking_service.booking_details([callback_data.booking_id])
    failed = await notify_cancelled(bot, details, booking_service)
    if failed:
        text = texts.ADMIN_CANCELLED_NOT_NOTIFIED.format(names=not_notified_names(failed))
    else:
        text = texts.ADMIN_CANCELLED
    await show(callback, text, back_kb())


def build_router(is_admin: IsAdmin) -> Router:
    router = Router(name="admin_bookings")
    router.message.filter(is_admin, IsPrivateChat())
    router.callback_query.filter(is_admin, IsPrivateChat())
    cb = router.callback_query
    cb.register(on_bookings_open, AdmMenuCb.filter(F.action == "bookings"))
    cb.register(on_day, AdmDayCb.filter(F.kind == "list"))
    cb.register(on_cancel_ask, AdmBookingCb.filter(F.action == "cancel"))
    cb.register(on_cancel_yes, AdmBookingCb.filter(F.action == "cancel_yes"))
    return router
