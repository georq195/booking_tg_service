from datetime import UTC, date, datetime
from html import escape

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.inline import (
    ConfirmCb,
    DateCb,
    ServiceCb,
    SlotCb,
    confirm_kb,
    dates_kb,
    services_kb,
    slots_kb,
)
from app.bot.states import BookingFlow
from app.db.models import Service
from app.services.booking_service import BookingService
from app.services.errors import SlotInPast, SlotTaken, SlotTooSoon
from app.bot.slot_errors import SLOT_ERROR_TEXTS
from app.services.users import get_or_create_user
from app.utils import texts
from app.utils.dates import bookable_days, day_label

async def _show(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=markup)


async def _reply(callback: CallbackQuery, text: str) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(text)


async def _expired(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _reply(callback, texts.SESSION_EXPIRED)


async def _unavailable(
    callback: CallbackQuery, state: FSMContext, booking_service: BookingService
) -> None:
    """The chosen service is gone: send the user back to the service choice."""
    await state.clear()
    services = await booking_service.list_active_services()
    if not services or not isinstance(callback.message, Message):
        await _reply(callback, texts.SERVICE_UNAVAILABLE + "\n" + texts.NO_SERVICES)
        return
    await state.set_state(BookingFlow.choosing_service)
    await callback.message.answer(
        texts.SERVICE_UNAVAILABLE, reply_markup=services_kb(services)
    )


async def _get_active_service(
    booking_service: BookingService, service_id: int
) -> Service | None:
    services = await booking_service.list_active_services()
    return next((s for s in services if s.id == service_id), None)


async def _show_dates(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    prefix: str = "",
) -> None:
    today = datetime.now(booking_service.tz).date()
    await state.set_state(BookingFlow.choosing_date)
    await _show(
        callback, prefix + texts.CHOOSE_DATE, dates_kb(bookable_days(today))
    )


async def _show_slots(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    service_id: int,
    day: date,
    prefix: str = "",
) -> None:
    slots = await booking_service.get_free_slots(day, service_id)
    if not slots:
        await _show_dates(
            callback,
            state,
            booking_service,
            prefix + texts.NO_SLOTS.format(date=day_label(day)) + "\n\n",
        )
        return
    await state.update_data(day=day.isoformat())
    await state.set_state(BookingFlow.choosing_slot)
    await _show(
        callback,
        prefix + texts.CHOOSE_SLOT.format(date=day_label(day)),
        slots_kb(slots, booking_service.tz),
    )


async def on_service(
    callback: CallbackQuery,
    callback_data: ServiceCb,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    await callback.answer()
    await state.update_data(service_id=callback_data.service_id)
    await _show_dates(callback, state, booking_service)


async def on_date(
    callback: CallbackQuery,
    callback_data: DateCb,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    await callback.answer()
    data = await state.get_data()
    if "service_id" not in data:
        await _expired(callback, state)
        return
    if await _get_active_service(booking_service, data["service_id"]) is None:
        await _unavailable(callback, state, booking_service)
        return
    day = date.fromisoformat(callback_data.day)
    await _show_slots(callback, state, booking_service, data["service_id"], day)


async def on_slot(
    callback: CallbackQuery,
    callback_data: SlotCb,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    await callback.answer()
    data = await state.get_data()
    if "service_id" not in data:
        await _expired(callback, state)
        return
    service = await _get_active_service(booking_service, data["service_id"])
    if service is None:
        await _unavailable(callback, state, booking_service)
        return
    start = datetime.fromtimestamp(callback_data.ts, UTC).astimezone(booking_service.tz)
    await state.update_data(ts=callback_data.ts)
    await state.set_state(BookingFlow.confirming)
    await _show(
        callback,
        texts.CONFIRM_SUMMARY.format(
            service=escape(service.title),
            date=day_label(start.date()),
            time=f"{start:%H:%M}",
        ),
        confirm_kb(),
    )


async def on_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    data = await state.get_data()
    if not {"service_id", "ts", "day"} <= data.keys():
        await _expired(callback, state)
        return
    service = await _get_active_service(booking_service, data["service_id"])
    if service is None:
        await _unavailable(callback, state, booking_service)
        return
    user = await get_or_create_user(
        session_factory, callback.from_user.id, callback.from_user.full_name
    )
    start = datetime.fromtimestamp(data["ts"], UTC)
    try:
        await booking_service.create(user.id, data["service_id"], start)
    except ValueError:  # service deactivated between the check and create
        await _unavailable(callback, state, booking_service)
        return
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
    local = start.astimezone(booking_service.tz)
    await state.clear()
    await _show(
        callback,
        texts.BOOKED.format(
            service=escape(service.title), date=day_label(local.date()), time=f"{local:%H:%M}"
        ),
    )


# Fallback: booking callbacks that arrive without a matching FSM state
# (e.g. old messages after a restart with MemoryStorage). State is left
# untouched so a stale button never wipes a live flow.
async def on_stale(callback: CallbackQuery) -> None:
    await callback.answer()
    await _reply(callback, texts.SESSION_EXPIRED)


def build_router() -> Router:
    router = Router(name="booking")
    cb = router.callback_query
    cb.register(on_service, BookingFlow.choosing_service, ServiceCb.filter())
    cb.register(on_date, BookingFlow.choosing_date, DateCb.filter())
    cb.register(on_slot, BookingFlow.choosing_slot, SlotCb.filter())
    cb.register(on_confirm, BookingFlow.confirming, ConfirmCb.filter())
    for data_cls in (ServiceCb, DateCb, SlotCb, ConfirmCb):
        cb.register(on_stale, data_cls.filter())
    return router
