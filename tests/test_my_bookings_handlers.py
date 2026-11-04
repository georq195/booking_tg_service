from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText
from aiogram.types import Message

from app.bot.handlers import build_router, my_bookings
from app.bot.keyboards.inline import BookingCb, DateCb, SlotCb
from app.bot.states import RescheduleFlow
from app.services.errors import (
    AlreadyCancelled,
    SlotInPast,
    SlotTaken,
    SlotTooSoon,
    TooLateToChange,
)
from app.utils import texts

SLOT = datetime(2026, 11, 3, 7, 0, tzinfo=UTC)
FLOW = {"reschedule_booking_id": 5, "service_id": 1, "day": "2026-11-03"}


@pytest.fixture
async def state():
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))


@pytest.fixture
def callback():
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.from_user = SimpleNamespace(id=1, full_name="Аня")
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


@pytest.fixture
def svc():
    s = MagicMock()
    s.tz = ZoneInfo("Europe/Moscow")
    booking = SimpleNamespace(id=5, service_id=1, start_at=SLOT)
    s.list_active_for_user = AsyncMock(return_value=[booking])
    s.service_titles = AsyncMock(return_value={1: "Cut <b>"})
    s.get_free_slots = AsyncMock(return_value=[SLOT])
    s.cancel = AsyncMock()
    s.reschedule = AsyncMock(
        return_value=SimpleNamespace(id=6, service_id=1, start_at=SLOT)
    )
    return s


def shown(callback) -> str:
    return callback.message.edit_text.await_args.args[0]


async def test_cmd_my_lists_bookings_with_escaped_titles(state, svc, session_factory):
    message = MagicMock()
    message.from_user = SimpleNamespace(id=1, full_name="Аня")
    message.answer = AsyncMock()
    await my_bookings.cmd_my(message, state, svc, session_factory)
    text = message.answer.await_args.args[0]
    assert "Cut &lt;b&gt;" in text and "10:00" in text
    assert message.answer.await_args.kwargs["reply_markup"] is not None


async def test_cmd_my_without_bookings(state, svc, session_factory):
    svc.list_active_for_user.return_value = []
    message = MagicMock()
    message.from_user = SimpleNamespace(id=1, full_name="Аня")
    message.answer = AsyncMock()
    await my_bookings.cmd_my(message, state, svc, session_factory)
    assert message.answer.await_args.args[0] == texts.NO_BOOKINGS


async def test_cancel_asks_for_confirmation_without_cancelling(
    callback, state, svc, session_factory
):
    await my_bookings.on_cancel_ask(
        callback, BookingCb(booking_id=5, action="cancel"), state, svc, session_factory
    )
    callback.answer.assert_awaited()
    # SLOT is 10:00 Moscow on 03.11; the service title is HTML-escaped
    assert shown(callback) == texts.CANCEL_ASK.format(
        date="вт 03.11", time="10:00", service="Cut &lt;b&gt;"
    )
    kb = callback.message.edit_text.await_args.kwargs["reply_markup"]
    actions = [BookingCb.unpack(b.callback_data).action for r in kb.inline_keyboard for b in r]
    assert actions == ["cancel_yes", "back"]
    svc.cancel.assert_not_awaited()


async def test_cancel_confirmed(callback, svc, session_factory):
    await my_bookings.on_cancel_yes(
        callback, BookingCb(booking_id=5, action="cancel_yes"), svc, session_factory
    )
    svc.cancel.assert_awaited_once()
    assert shown(callback) == texts.CANCELLED


async def test_double_cancel_says_already_cancelled(callback, svc, session_factory):
    svc.cancel.side_effect = [None, AlreadyCancelled(5)]
    data = BookingCb(booking_id=5, action="cancel_yes")
    await my_bookings.on_cancel_yes(callback, data, svc, session_factory)
    await my_bookings.on_cancel_yes(callback, data, svc, session_factory)
    assert shown(callback) == texts.ALREADY_CANCELLED
    assert svc.cancel.await_count == 2
    assert callback.answer.await_count == 2


async def test_cancel_too_late_shows_message(callback, svc, session_factory):
    svc.cancel.side_effect = TooLateToChange(5)
    await my_bookings.on_cancel_yes(
        callback, BookingCb(booking_id=5, action="cancel_yes"), svc, session_factory
    )
    assert shown(callback) == texts.TOO_LATE


async def test_not_modified_error_is_tolerated(callback, svc, session_factory):
    callback.message.edit_text.side_effect = TelegramBadRequest(
        method=EditMessageText(text="x"),
        message="Bad Request: message is not modified",
    )
    await my_bookings.on_cancel_yes(
        callback, BookingCb(booking_id=5, action="cancel_yes"), svc, session_factory
    )
    callback.answer.assert_awaited()


async def test_other_bad_request_is_not_swallowed(callback, svc, session_factory):
    callback.message.edit_text.side_effect = TelegramBadRequest(
        method=EditMessageText(text="x"), message="Bad Request: chat not found"
    )
    with pytest.raises(TelegramBadRequest):
        await my_bookings.on_cancel_yes(
            callback, BookingCb(booking_id=5, action="cancel_yes"), svc, session_factory
        )


async def test_full_reschedule(callback, state, svc, session_factory):
    await my_bookings.on_move(
        callback, BookingCb(booking_id=5, action="move"), state, svc, session_factory
    )
    assert await state.get_state() == RescheduleFlow.choosing_date.state
    assert (await state.get_data())["reschedule_booking_id"] == 5

    await my_bookings.on_res_date(callback, DateCb(day="2026-11-03"), state, svc)
    assert await state.get_state() == RescheduleFlow.choosing_slot.state
    assert svc.get_free_slots.await_args.args[1] == 1

    await my_bookings.on_res_slot(
        callback, SlotCb(ts=int(SLOT.timestamp())), state, svc, session_factory
    )
    args = svc.reschedule.await_args.args
    assert args[0] == 5 and args[2] == SLOT
    assert shown(callback).startswith("Запись перенесена!")
    assert "Cut &lt;b&gt;" in shown(callback)
    assert await state.get_state() is None


async def test_move_unknown_booking(callback, state, svc, session_factory):
    svc.list_active_for_user.return_value = []
    await my_bookings.on_move(
        callback, BookingCb(booking_id=5, action="move"), state, svc, session_factory
    )
    assert shown(callback) == texts.BOOKING_NOT_FOUND
    assert await state.get_state() is None


@pytest.mark.parametrize(
    "error, text",
    [
        (SlotTaken, texts.SLOT_TAKEN),
        (SlotInPast, texts.SLOT_IN_PAST),
        (SlotTooSoon, texts.SLOT_TOO_SOON),
    ],
)
async def test_reschedule_slot_error_reshows_slots(
    error, text, callback, state, svc, session_factory
):
    await state.set_state(RescheduleFlow.choosing_slot)
    await state.set_data(FLOW)
    svc.reschedule.side_effect = error(SLOT)
    await my_bookings.on_res_slot(
        callback, SlotCb(ts=int(SLOT.timestamp())), state, svc, session_factory
    )
    assert shown(callback).startswith(text)
    assert await state.get_state() == RescheduleFlow.choosing_slot.state
    assert svc.get_free_slots.await_args.args[0].isoformat() == "2026-11-03"
    assert (await state.get_data())["reschedule_booking_id"] == 5


async def test_reschedule_too_late_clears_state(callback, state, svc, session_factory):
    await state.set_state(RescheduleFlow.choosing_slot)
    await state.set_data(FLOW)
    svc.reschedule.side_effect = TooLateToChange(5)
    await my_bookings.on_res_slot(
        callback, SlotCb(ts=int(SLOT.timestamp())), state, svc, session_factory
    )
    assert shown(callback) == texts.TOO_LATE
    assert await state.get_state() is None


async def test_res_date_without_flow_data_expires(callback, state, svc):
    await state.set_state(RescheduleFlow.choosing_date)
    await my_bookings.on_res_date(callback, DateCb(day="2026-11-03"), state, svc)
    callback.message.answer.assert_awaited_with(texts.SESSION_EXPIRED)
    assert await state.get_state() is None


def test_my_bookings_router_precedes_booking_fallback():
    names = [r.name for r in build_router().sub_routers]
    assert names.index("my_bookings") < names.index("booking")


def test_combined_router_can_be_built_twice():
    a, b = build_router(), build_router()
    assert a is not b
    Dispatcher().include_router(a)
    Dispatcher().include_router(b)


async def test_cancel_ask_for_foreign_or_unknown_booking_shows_not_found(
    callback, state, svc, session_factory
):
    await my_bookings.on_cancel_ask(
        callback, BookingCb(booking_id=99, action="cancel"), state, svc, session_factory
    )
    assert shown(callback) == texts.BOOKING_NOT_FOUND
    assert callback.message.edit_text.await_args.kwargs.get("reply_markup") is None


async def test_cancel_confirm_on_inactive_booking_says_not_active(
    callback, svc, session_factory
):
    from app.services.errors import BookingNotActive

    svc.cancel.side_effect = BookingNotActive(5)
    await my_bookings.on_cancel_yes(
        callback, BookingCb(booking_id=5, action="cancel_yes"), svc, session_factory
    )
    assert shown(callback) == texts.BOOKING_NOT_ACTIVE
