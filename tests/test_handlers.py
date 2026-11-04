from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app.bot.handlers import booking
from app.bot.keyboards.inline import DateCb
from app.bot.states import BookingFlow
from app.services.errors import SlotInPast, SlotTaken, SlotTooSoon
from app.utils import texts

SLOT = datetime(2026, 11, 3, 7, 0, tzinfo=UTC)
FLOW = {"service_id": 1, "day": "2026-11-03", "ts": int(SLOT.timestamp())}


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
    s.list_active_services = AsyncMock(
        return_value=[SimpleNamespace(id=1, title="Cut", is_active=True)]
    )
    s.get_free_slots = AsyncMock(return_value=[SLOT])
    s.create = AsyncMock()
    return s


OTHER = SimpleNamespace(id=2, title="Color", is_active=True)


def _services_after_deactivation():
    # first lookup (service 1 gone) finds nothing; the re-offer lists another one
    return iter([[OTHER], [OTHER]])


async def _assert_back_to_service_choice(callback, state):
    callback.answer.assert_awaited()
    kwargs = callback.message.answer.await_args
    assert kwargs.args[0] == texts.SERVICE_UNAVAILABLE
    assert kwargs.kwargs["reply_markup"] is not None
    assert await state.get_state() == BookingFlow.choosing_service.state


@pytest.mark.parametrize(
    "error, text",
    [
        (SlotTaken, texts.SLOT_TAKEN),
        (SlotInPast, texts.SLOT_IN_PAST),
        (SlotTooSoon, texts.SLOT_TOO_SOON),
    ],
)
async def test_confirm_error_reshows_slots_for_same_day(
    error, text, callback, state, svc, session_factory
):
    await state.set_state(BookingFlow.confirming)
    await state.set_data(FLOW)
    svc.create.side_effect = error(SLOT)
    await booking.on_confirm(callback, state, svc, session_factory)
    callback.answer.assert_awaited()
    shown = callback.message.edit_text.await_args.args[0]
    assert shown.startswith(text)
    assert await state.get_state() == BookingFlow.choosing_slot.state
    assert svc.get_free_slots.await_args.args[0].isoformat() == FLOW["day"]


async def test_on_date_inactive_service_answers_and_reports(
    callback, state, svc
):
    await state.set_state(BookingFlow.choosing_date)
    await state.set_data({"service_id": 1})
    svc.list_active_services.side_effect = _services_after_deactivation()
    await booking.on_date(callback, DateCb(day="2026-11-03"), state, svc)
    callback.answer.assert_awaited()
    await _assert_back_to_service_choice(callback, state)
    svc.get_free_slots.assert_not_awaited()


async def test_on_confirm_inactive_service_answers_and_reports(
    callback, state, svc, session_factory
):
    await state.set_state(BookingFlow.confirming)
    await state.set_data(FLOW)
    svc.list_active_services.side_effect = _services_after_deactivation()
    await booking.on_confirm(callback, state, svc, session_factory)
    callback.answer.assert_awaited()
    await _assert_back_to_service_choice(callback, state)
    svc.create.assert_not_awaited()


async def test_stale_callback_keeps_live_state(callback, state):
    await state.set_state(BookingFlow.choosing_slot)
    await state.set_data(FLOW)
    await booking.on_stale(callback)
    callback.answer.assert_awaited()
    callback.message.answer.assert_awaited_with(texts.SESSION_EXPIRED)
    assert await state.get_state() == BookingFlow.choosing_slot.state
    assert await state.get_data() == FLOW
