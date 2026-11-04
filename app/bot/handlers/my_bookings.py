from datetime import UTC, date, datetime
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.inline import (
    BookingCb,
    DateCb,
    SlotCb,
    cancel_confirm_kb,
    dates_kb,
    my_bookings_kb,
    slots_kb,
)
from app.bot.states import RescheduleFlow
from app.services.booking_service import BookingService
from app.bot.slot_errors import SLOT_ERROR_TEXTS
from app.services.errors import (
    AlreadyCancelled,
    BookingNotActive,
    BookingNotFound,
    NotYourBooking,
    SlotInPast,
    SlotTaken,
    SlotTooSoon,
    TooLateToChange,
)
from app.services.users import get_or_create_user
from app.utils import texts
from app.utils.dates import bookable_days, day_label

_ERROR_TEXTS: dict[type[Exception], str] = {
    AlreadyCancelled: texts.ALREADY_CANCELLED,
    BookingNotActive: texts.BOOKING_NOT_ACTIVE,
    TooLateToChange: texts.TOO_LATE,
    BookingNotFound: texts.BOOKING_NOT_FOUND,
    NotYourBooking: texts.NOT_YOUR_BOOKING,
}


async def _show(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        # A double tap re-sends identical content; that is harmless.
        if "message is not modified" not in str(exc):
            raise


async def _reply(callback: CallbackQuery, text: str) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(text)


async def _user_id(
    session_factory: async_sessionmaker[AsyncSession], callback: CallbackQuery
) -> int:
    user = await get_or_create_user(
        session_factory, callback.from_user.id, callback.from_user.full_name
    )
    return user.id


async def _list_view(
    booking_service: BookingService, user_id: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    bookings = await booking_service.list_active_for_user(user_id)
    if not bookings:
        return texts.NO_BOOKINGS, None
    titles = await booking_service.service_titles([b.service_id for b in bookings])
    lines = [texts.MY_BOOKINGS_TITLE]
    for b in bookings:
        local = b.start_at.astimezone(booking_service.tz)
        lines.append(
            texts.BOOKING_LINE.format(
                date=day_label(local.date()),
                time=f"{local:%H:%M}",
                service=escape(titles.get(b.service_id, "")),
            )
        )
    return "\n".join(lines), my_bookings_kb(bookings, booking_service.tz)


async def cmd_my(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await state.clear()
    tg_user = message.from_user
    if tg_user is None:
        return
    user = await get_or_create_user(session_factory, tg_user.id, tg_user.full_name)
    text, markup = await _list_view(booking_service, user.id)
    await message.answer(text, reply_markup=markup)


async def on_back(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    await state.clear()
    text, markup = await _list_view(
        booking_service, await _user_id(session_factory, callback)
    )
    await _show(callback, text, markup)


async def on_cancel_ask(
    callback: CallbackQuery,
    callback_data: BookingCb,
    state: FSMContext,
    booking_service: BookingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    await state.clear()
    user_id = await _user_id(session_factory, callback)
    # Only the user's own active bookings are looked up, never someone else's.
    bookings = await booking_service.list_active_for_user(user_id)
    booking = next((b for b in bookings if b.id == callback_data.booking_id), None)
    if booking is None:
        await _show(callback, texts.BOOKING_NOT_FOUND)
        return
    titles = await booking_service.service_titles([booking.service_id])
    local = booking.start_at.astimezone(booking_service.tz)
    await _show(
        callback,
        texts.CANCEL_ASK.format(
            date=day_label(local.date()),
            time=f"{local:%H:%M}",
            service=escape(titles.get(booking.service_id, "")),
        ),
        cancel_confirm_kb(callback_data.booking_id),
    )


async def on_cancel_yes(
    callback: CallbackQuery,
    callback_data: BookingCb,
    booking_service: BookingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    user_id = await _user_id(session_factory, callback)
    try:
        await booking_service.cancel(callback_data.booking_id, user_id)
    except (
        AlreadyCancelled,
        BookingNotActive,
        TooLateToChange,
        BookingNotFound,
        NotYourBooking,
    ) as exc:
        await _show(callback, _ERROR_TEXTS[type(exc)])
        return
    await _show(callback, texts.CANCELLED)


async def on_move(
    callback: CallbackQuery,
    callback_data: BookingCb,
    state: FSMContext,
    booking_service: BookingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    user_id = await _user_id(session_factory, callback)
    bookings = await booking_service.list_active_for_user(user_id)
    booking = next((b for b in bookings if b.id == callback_data.booking_id), None)
    if booking is None:
        await state.clear()
        await _show(callback, texts.BOOKING_NOT_FOUND)
        return
    await state.set_data(
        {"reschedule_booking_id": booking.id, "service_id": booking.service_id}
    )
    await state.set_state(RescheduleFlow.choosing_date)
    today = datetime.now(booking_service.tz).date()
    await _show(callback, texts.CHOOSE_DATE, dates_kb(bookable_days(today)))


async def _show_slots(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    service_id: int,
    day: date,
    prefix: str = "",
) -> None:
    try:
        slots = await booking_service.get_free_slots(day, service_id)
    except ValueError:  # service deactivated meanwhile
        await state.clear()
        await _show(callback, texts.RESCHEDULE_SERVICE_GONE)
        return
    if not slots:
        await state.set_state(RescheduleFlow.choosing_date)
        today = datetime.now(booking_service.tz).date()
        await _show(
            callback,
            prefix + texts.NO_SLOTS.format(date=day_label(day)),
            dates_kb(bookable_days(today)),
        )
        return
    await state.update_data(day=day.isoformat())
    await state.set_state(RescheduleFlow.choosing_slot)
    await _show(
        callback,
        prefix + texts.CHOOSE_SLOT.format(date=day_label(day)),
        slots_kb(slots, booking_service.tz),
    )


async def on_res_date(
    callback: CallbackQuery,
    callback_data: DateCb,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    await callback.answer()
    data = await state.get_data()
    if "service_id" not in data or "reschedule_booking_id" not in data:
        await state.clear()
        await _reply(callback, texts.SESSION_EXPIRED)
        return
    day = date.fromisoformat(callback_data.day)
    await _show_slots(callback, state, booking_service, data["service_id"], day)


async def on_res_slot(
    callback: CallbackQuery,
    callback_data: SlotCb,
    state: FSMContext,
    booking_service: BookingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    data = await state.get_data()
    if not {"service_id", "reschedule_booking_id", "day"} <= data.keys():
        await state.clear()
        await _reply(callback, texts.SESSION_EXPIRED)
        return
    user_id = await _user_id(session_factory, callback)
    start = datetime.fromtimestamp(callback_data.ts, UTC)
    try:
        new = await booking_service.reschedule(
            data["reschedule_booking_id"], user_id, start
        )
    except (SlotTaken, SlotInPast, SlotTooSoon) as exc:
        error = SLOT_ERROR_TEXTS[type(exc)]
        await _show_slots(
            callback,
            state,
            booking_service,
            data["service_id"],
            date.fromisoformat(data["day"]),
            prefix=error + "\n\n",
        )
        return
    except (
        AlreadyCancelled,
        BookingNotActive,
        TooLateToChange,
        BookingNotFound,
        NotYourBooking,
    ) as exc:
        await state.clear()
        await _show(callback, _ERROR_TEXTS[type(exc)])
        return
    titles = await booking_service.service_titles([new.service_id])
    local = new.start_at.astimezone(booking_service.tz)
    await state.clear()
    await _show(
        callback,
        texts.RESCHEDULED.format(
            service=escape(titles.get(new.service_id, "")),
            date=day_label(local.date()),
            time=f"{local:%H:%M}",
        ),
    )


def build_router() -> Router:
    router = Router(name="my_bookings")
    router.message.register(cmd_my, Command("my"))
    cb = router.callback_query
    cb.register(on_cancel_ask, BookingCb.filter(F.action == "cancel"))
    cb.register(on_cancel_yes, BookingCb.filter(F.action == "cancel_yes"))
    cb.register(on_move, BookingCb.filter(F.action == "move"))
    cb.register(on_back, BookingCb.filter(F.action == "back"))
    cb.register(on_res_date, RescheduleFlow.choosing_date, DateCb.filter())
    cb.register(on_res_slot, RescheduleFlow.choosing_slot, SlotCb.filter())
    return router
