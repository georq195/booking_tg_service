from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from aiogram import Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app.bot.filters import IsAdmin
from app.bot.handlers import admin, build_router
from app.bot.keyboards import admin as kb
from app.bot.handlers.admin import bookings as bookings_h
from app.bot.handlers.admin import menu as menu_h
from app.bot.handlers.admin import schedule as schedule_h
from app.bot.handlers.admin import services as services_h
from app.bot.states import AdminFlow
from app.db.models import BookingStatus
from app.services.errors import AlreadyCancelled, InvalidWorkDay
from app.services.slots import WorkDay
from app.utils import texts
from app.utils.parsing import parse_positive_int, parse_work_hours

TZ = ZoneInfo("Europe/Moscow")
START = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)  # 12:00 Moscow


@pytest.fixture
async def state():
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))


@pytest.fixture
def callback():
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.from_user = SimpleNamespace(id=1, full_name="Admin")
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


def message(text):
    m = MagicMock()
    m.text = text
    m.answer = AsyncMock()
    m.from_user = SimpleNamespace(id=1, full_name="Admin")
    return m


@pytest.fixture
def bot():
    return SimpleNamespace(send_message=AsyncMock())


def details(booking_id=5, name="<b>Аня", title="Cut&Go", tg=777):
    return SimpleNamespace(
        booking=SimpleNamespace(id=booking_id, start_at=START),
        user=SimpleNamespace(telegram_id=tg, name=name),
        service=SimpleNamespace(title=title),
    )


@pytest.fixture
def svc():
    s = MagicMock()
    s.tz = TZ
    s.list_for_day = AsyncMock(return_value=[SimpleNamespace(id=5)])
    s.booking_details = AsyncMock(return_value=[details()])
    s.admin_cancel = AsyncMock(return_value=SimpleNamespace(id=5))
    s.set_day_off = AsyncMock(return_value=[])
    s.set_work_schedule = AsyncMock()
    s.list_rows = AsyncMock(return_value=[])
    s.bookings_outside_work_day = AsyncMock(return_value=[])
    s.remove_day_off = AsyncMock(return_value=True)
    s.list_days_off = AsyncMock(return_value=[date(2026, 11, 10)])
    s.get_work_schedule = AsyncMock(return_value={})
    s.list_all_services = AsyncMock(return_value=[])
    s.add_service = AsyncMock(return_value=SimpleNamespace(id=1))
    s.update_service = AsyncMock()
    s.hide_service = AsyncMock()
    s.get_service = AsyncMock(
        return_value=SimpleNamespace(
            id=1, title="<i>X", duration_min=30, price=10, is_active=True
        )
    )
    return s


# ---- wiring ---------------------------------------------------------------


def _observers_with_handlers(router):
    for r in (router, *router.chain_tail):
        for observer in r.observers.values():
            if observer.handlers:
                yield r, observer


def test_every_admin_observer_is_guarded_by_is_admin():
    router = admin.build_router([42])
    seen = list(_observers_with_handlers(router))
    assert {o.event_name for _, o in seen} == {"message", "callback_query"}
    for _, observer in seen:
        # router-level filters live on the observer's own handler object
        assert any(
            isinstance(f.callback, IsAdmin) for f in observer._handler.filters
        ), observer.event_name


def test_admin_router_is_fresh_each_call():
    a, b = admin.build_router([1]), admin.build_router([1])
    assert a is not b
    Dispatcher().include_router(a)
    Dispatcher().include_router(b)


def test_admin_panel_is_off_without_ids():
    names = {r.name for r in build_router().sub_routers}
    assert "admin" not in names
    assert "admin" in {r.name for r in build_router([1]).sub_routers}


async def test_guard_blocks_non_admin_callback_in_real_dispatch(svc):
    from aiogram.types import Update

    from app.bot.middlewares import ServicesMiddleware

    dp = Dispatcher(storage=MemoryStorage())
    dp.callback_query.outer_middleware(ServicesMiddleware(svc, None))
    dp.include_router(build_router([1]))
    bot = AsyncMock()
    bot.id = 1
    data = kb.AdmDayCb(kind="off_yes", day="2026-11-03").pack()
    for uid, expected in ((2, 0), (1, 1)):
        update = Update.model_validate(
            {
                "update_id": 1,
                "callback_query": {
                    "id": "1",
                    "from": {"id": uid, "is_bot": False, "first_name": "x"},
                    "chat_instance": "1",
                    "data": data,
                    "message": {
                        "message_id": 1,
                        "date": 0,
                        "chat": {"id": 1, "type": "private"},
                    },
                },
            },
            context={"bot": bot},
        )
        await dp.feed_update(bot, update)
        assert svc.set_day_off.await_count == expected


# ---- callback data & keyboards -------------------------------------------


def test_callback_data_roundtrip_and_limit():
    items = [
        kb.AdmMenuCb(action="schedule"),
        kb.AdmWeekdayCb(weekday=6, action="off"),
        kb.AdmDayCb(kind="off_yes", day=date.max.isoformat()),
        kb.AdmBookingCb(booking_id=2**31, action="cancel_yes"),
        kb.AdmServiceCb(service_id=2**31, action="duration"),
    ]
    for item in items:
        packed = item.pack()
        assert len(packed.encode()) <= 64
        assert type(item).unpack(packed) == item


def test_admin_menu_and_schedule_keyboards():
    menu = kb.admin_menu_kb()
    assert [b.text for r in menu.inline_keyboard for b in r] == [
        texts.ADMIN_BTN_SCHEDULE,
        texts.ADMIN_BTN_DAYOFF,
        texts.ADMIN_BTN_DAYSOFF,
        texts.ADMIN_BTN_SERVICES,
        texts.ADMIN_BTN_BOOKINGS,
        texts.ADMIN_BTN_EXPORT,
    ]
    sched = kb.schedule_kb({0: WorkDay(time(10), time(18), time(14), time(15))})
    buttons = [b for r in sched.inline_keyboard for b in r]
    assert buttons[0].text == "пн 10:00-18:00 (14:00-15:00)"
    assert buttons[1].text == f"вт {texts.ADMIN_WEEKDAY_OFF}"
    assert kb.AdmWeekdayCb.unpack(buttons[1].callback_data).weekday == 1


def test_services_keyboard_marks_hidden_and_has_add():
    services = [
        SimpleNamespace(id=1, title="A", is_active=True),
        SimpleNamespace(id=2, title="B", is_active=False),
    ]
    buttons = [b for r in kb.services_admin_kb(services).inline_keyboard for b in r]
    assert buttons[1].text == "B" + texts.ADMIN_SERVICE_HIDDEN_MARK
    assert kb.AdmServiceCb.unpack(buttons[-2].callback_data).action == "add"
    assert kb.AdmMenuCb.unpack(buttons[-1].callback_data).action == "menu"


# ---- parsing ----------------------------------------------------------------


def test_parse_work_hours():
    assert parse_work_hours("10:00-18:00") == WorkDay(time(10), time(18))
    assert parse_work_hours(" 9:30 - 18:00  13:00-14:00 ") == WorkDay(
        time(9, 30), time(18), time(13), time(14)
    )
    for bad in ["", "abc", "10-18", "25:00-26:00", "10:00-18:00 14:00", "10:60-18:00"]:
        with pytest.raises(ValueError):
            parse_work_hours(bad)


def test_parse_positive_int():
    assert parse_positive_int(" 60 ", minimum=1, maximum=100) == 60
    assert parse_positive_int("0", minimum=0, maximum=100) == 0
    for bad in ["", "x", "1.5", "-1", "0", "101", "٣"]:
        with pytest.raises(ValueError):
            parse_positive_int(bad, minimum=1, maximum=100)


# ---- handlers ---------------------------------------------------------------


async def test_admin_command_shows_menu(state):
    m = message("/admin")
    await menu_h.cmd_admin(m, state)
    m.answer.assert_awaited_once()
    assert m.answer.await_args.args[0] == texts.ADMIN_MENU


async def test_schedule_bad_format_keeps_waiting(state, svc):
    await state.set_state(AdminFlow.waiting_hours)
    await state.update_data(weekday=1)
    m = message("абв")
    await schedule_h.on_hours(m, state, svc)
    svc.set_work_schedule.assert_not_awaited()
    assert m.answer.await_args.args[0] == texts.ADMIN_HOURS_BAD_FORMAT
    assert await state.get_state() == AdminFlow.waiting_hours.state


async def test_schedule_invalid_workday_message_from_texts(state, svc):
    await state.set_state(AdminFlow.waiting_hours)
    await state.update_data(weekday=1)
    for reason, text in [
        ("end_before_start", texts.ADMIN_HOURS_END_BEFORE_START),
        ("bad_break", texts.ADMIN_HOURS_BAD_BREAK),
    ]:
        svc.set_work_schedule.side_effect = InvalidWorkDay(reason)
        m = message("10:00-18:00")
        await schedule_h.on_hours(m, state, svc)
        assert m.answer.await_args.args[0] == text
    assert await state.get_state() == AdminFlow.waiting_hours.state


async def test_schedule_valid_saves_and_clears(state, svc):
    await state.set_state(AdminFlow.waiting_hours)
    await state.update_data(weekday=1)
    m = message("10:00-18:00 14:00-15:00")
    await schedule_h.on_hours(m, state, svc)
    svc.set_work_schedule.assert_awaited_once_with(
        1, WorkDay(time(10), time(18), time(14), time(15))
    )
    assert await state.get_state() is None


async def test_dayoff_with_bookings_asks_confirmation_and_escapes(callback, svc):
    await schedule_h.on_dayoff_pick(
        callback, kb.AdmDayCb(kind="off", day="2026-11-03"), svc
    )
    svc.set_day_off.assert_not_awaited()
    text = callback.message.edit_text.await_args.args[0]
    assert "12:00 — &lt;b&gt;Аня (Cut&amp;Go)" in text and "<b>" not in text
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert kb.AdmDayCb.unpack(markup.inline_keyboard[0][0].callback_data).kind == "off_yes"


async def test_dayoff_confirmed_notifies_every_client(callback, svc, bot):
    svc.set_day_off.return_value = [SimpleNamespace(id=5)]
    await schedule_h.on_dayoff_confirm(
        callback, kb.AdmDayCb(kind="off_yes", day="2026-11-03"), svc, bot
    )
    svc.set_day_off.assert_awaited_once_with(date(2026, 11, 3), None, confirm=True)
    chat_id, text = bot.send_message.await_args.args
    assert chat_id == 777
    assert "&lt;b&gt;" not in text and "Cut&amp;Go" in text
    assert text.startswith("Ваша запись отменена")


async def test_dayoff_confirmed_survives_blocked_client(callback, svc, bot):
    from aiogram.exceptions import TelegramForbiddenError

    svc.set_day_off.return_value = [SimpleNamespace(id=5), SimpleNamespace(id=6)]
    svc.booking_details.return_value = [details(5, tg=1), details(6, tg=2)]
    bot.send_message.side_effect = [
        TelegramForbiddenError(method=MagicMock(), message="blocked"),
        None,
    ]
    await schedule_h.on_dayoff_confirm(
        callback, kb.AdmDayCb(kind="off_yes", day="2026-11-03"), svc, bot
    )
    assert bot.send_message.await_count == 2
    assert texts.ADMIN_DAYOFF_DONE_NOTIFIED.format(
        date="вт 03.11", count=2
    ) in callback.message.edit_text.await_args.args[0]


async def test_day_bookings_list_escapes_and_offers_cancel(callback, svc):
    await bookings_h.on_day(callback, kb.AdmDayCb(kind="list", day="2026-11-03"), svc)
    text = callback.message.edit_text.await_args.args[0]
    assert "&lt;b&gt;Аня" in text and "<b>" not in text
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    data = kb.AdmBookingCb.unpack(markup.inline_keyboard[0][0].callback_data)
    assert (data.booking_id, data.action) == (5, "cancel")


async def test_admin_cancel_notifies_client(callback, svc, bot):
    await bookings_h.on_cancel_yes(
        callback, kb.AdmBookingCb(booking_id=5, action="cancel_yes"), svc, bot
    )
    svc.admin_cancel.assert_awaited_once_with(5)
    assert bot.send_message.await_args.args[0] == 777
    assert callback.message.edit_text.await_args.args[0] == texts.ADMIN_CANCELLED


async def test_admin_cancel_already_cancelled_does_not_notify(callback, svc, bot):
    svc.admin_cancel.side_effect = AlreadyCancelled(5)
    await bookings_h.on_cancel_yes(
        callback, kb.AdmBookingCb(booking_id=5, action="cancel_yes"), svc, bot
    )
    bot.send_message.assert_not_awaited()
    assert callback.message.edit_text.await_args.args[0] == texts.ALREADY_CANCELLED


async def test_add_service_flow_validates_each_step(state, svc):
    await menu_h_start_add(state)
    m = message("   ")
    await services_h.on_add_title(m, state)
    assert m.answer.await_args.args[0] == texts.ADMIN_BAD_TITLE
    m = message("Стрижка")
    await services_h.on_add_title(m, state)
    for bad in ["0", "abc", "-5"]:
        m = message(bad)
        await services_h.on_add_duration(m, state)
        assert m.answer.await_args.args[0] == texts.ADMIN_BAD_NUMBER
    await services_h.on_add_duration(message("45"), state)
    m = message("-1")
    await services_h.on_add_price(m, state, svc)
    assert m.answer.await_args.args[0] == texts.ADMIN_BAD_PRICE
    svc.add_service.assert_not_awaited()
    await services_h.on_add_price(message("0"), state, svc)
    svc.add_service.assert_awaited_once_with("Стрижка", 45, 0)
    assert await state.get_state() is None


async def menu_h_start_add(state):
    await state.set_state(AdminFlow.add_title)


async def test_edit_service_value_and_hide(callback, state, svc):
    await state.set_state(AdminFlow.edit_value)
    await state.update_data(service_id=1, field="duration")
    m = message("0")
    await services_h.on_edit_value(m, state, svc)
    svc.update_service.assert_not_awaited()
    await services_h.on_edit_value(message("90"), state, svc)
    svc.update_service.assert_awaited_once_with(1, duration_min=90)
    await services_h.on_service_action(
        callback, kb.AdmServiceCb(service_id=1, action="hide"), state, svc
    )
    svc.hide_service.assert_awaited_once_with(1)


async def test_service_card_escapes_title(callback, state, svc):
    await services_h.on_service_action(
        callback, kb.AdmServiceCb(service_id=1, action="open"), state, svc
    )
    assert "&lt;i&gt;X" in callback.message.edit_text.await_args.args[0]


# ---- F2: empty day needs confirmation; reopening days off -----------------------


async def test_dayoff_empty_day_asks_confirmation_before_closing(callback, svc):
    svc.list_for_day.return_value = []
    await schedule_h.on_dayoff_pick(
        callback, kb.AdmDayCb(kind="off", day="2026-11-03"), svc
    )
    svc.set_day_off.assert_not_awaited()
    assert callback.message.edit_text.await_args.args[0] == texts.ADMIN_DAYOFF_CONFIRM_EMPTY.format(
        date="вт 03.11"
    )
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    first = markup.inline_keyboard[0][0]
    assert first.text == texts.ADMIN_DAYOFF_YES_EMPTY_BTN
    assert kb.AdmDayCb.unpack(first.callback_data).kind == "off_yes"


async def test_dayoff_empty_day_confirmed_closes(callback, svc, bot):
    svc.set_day_off.return_value = []
    await schedule_h.on_dayoff_confirm(
        callback, kb.AdmDayCb(kind="off_yes", day="2026-11-03"), svc, bot
    )
    svc.set_day_off.assert_awaited_once_with(date(2026, 11, 3), None, confirm=True)
    assert callback.message.edit_text.await_args.args[0] == texts.ADMIN_DAYOFF_DONE.format(
        date="вт 03.11"
    )


async def test_daysoff_list_offers_reopen_buttons(callback, state, svc):
    await schedule_h.on_daysoff_open(callback, state, svc)
    assert callback.message.edit_text.await_args.args[0] == texts.ADMIN_DAYSOFF_TITLE
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    data = kb.AdmDayCb.unpack(markup.inline_keyboard[0][0].callback_data)
    assert (data.kind, data.day) == ("reopen", "2026-11-10")


async def test_daysoff_list_empty(callback, state, svc):
    svc.list_days_off.return_value = []
    await schedule_h.on_daysoff_open(callback, state, svc)
    assert callback.message.edit_text.await_args.args[0] == texts.ADMIN_DAYSOFF_EMPTY


async def test_reopen_day_removes_day_off(callback, svc):
    await schedule_h.on_dayoff_reopen(
        callback, kb.AdmDayCb(kind="reopen", day="2026-11-10"), svc
    )
    svc.remove_day_off.assert_awaited_once_with(date(2026, 11, 10))
    assert callback.message.edit_text.await_args.args[0] == texts.ADMIN_DAYOFF_REOPENED.format(
        date="вт 10.11"
    )


async def test_reopen_day_already_open(callback, svc):
    svc.remove_day_off.return_value = False
    await schedule_h.on_dayoff_reopen(
        callback, kb.AdmDayCb(kind="reopen", day="2026-11-10"), svc
    )
    assert callback.message.edit_text.await_args.args[0] == texts.ADMIN_DAYOFF_ALREADY_OPEN.format(
        date="вт 10.11"
    )


def test_admin_menu_has_days_off_button_and_reopen_callback_fits():
    menu = kb.admin_menu_kb()
    assert texts.ADMIN_BTN_DAYSOFF in [b.text for r in menu.inline_keyboard for b in r]
    assert len(kb.AdmDayCb(kind="reopen", day=date.max.isoformat()).pack().encode()) <= 64


# ---- F3: schedule change warns about stranded bookings (warn-only) --------------


async def test_weekday_off_without_affected_bookings_saves_directly(callback, state, svc):
    await schedule_h.on_weekday(callback, kb.AdmWeekdayCb(weekday=1, action="off"), state, svc)
    svc.bookings_outside_work_day.assert_awaited_once_with(1, None)
    svc.set_work_schedule.assert_awaited_once_with(1, None)


async def test_weekday_off_with_affected_bookings_warns_and_does_not_save(callback, state, svc):
    svc.bookings_outside_work_day.return_value = [SimpleNamespace(id=5)]
    await schedule_h.on_weekday(callback, kb.AdmWeekdayCb(weekday=1, action="off"), state, svc)
    svc.set_work_schedule.assert_not_awaited()
    svc.admin_cancel.assert_not_awaited()
    text = callback.message.edit_text.await_args.args[0]
    assert "12:00 — &lt;b&gt;Аня (Cut&amp;Go)" in text and "<b>" not in text
    assert "вт 03.11" in text
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    data = kb.AdmWeekdayCb.unpack(markup.inline_keyboard[0][0].callback_data)
    assert (data.weekday, data.action) == (1, "off_yes")


async def test_weekday_off_confirmed_saves(callback, state, svc):
    await schedule_h.on_weekday(callback, kb.AdmWeekdayCb(weekday=1, action="off_yes"), state, svc)
    svc.set_work_schedule.assert_awaited_once_with(1, None)
    svc.bookings_outside_work_day.assert_not_awaited()


async def test_hours_with_affected_bookings_warn_then_confirm_saves(callback, state, svc):
    await state.set_state(AdminFlow.waiting_hours)
    await state.update_data(weekday=1)
    svc.bookings_outside_work_day.return_value = [SimpleNamespace(id=5)]
    m = message("11:00-17:00")
    await schedule_h.on_hours(m, state, svc)
    svc.set_work_schedule.assert_not_awaited()
    svc.bookings_outside_work_day.assert_awaited_once_with(1, WorkDay(time(11), time(17)))
    text = m.answer.await_args.args[0]
    assert "&lt;b&gt;Аня" in text and "<b>" not in text
    markup = m.answer.await_args.kwargs["reply_markup"]
    data = kb.AdmWeekdayCb.unpack(markup.inline_keyboard[0][0].callback_data)
    assert (data.weekday, data.action) == (1, "save_yes")
    await schedule_h.on_weekday(callback, data, state, svc)
    svc.set_work_schedule.assert_awaited_once_with(1, WorkDay(time(11), time(17)))
    assert await state.get_state() is None


async def test_hours_confirm_without_pending_hours_is_an_error(callback, state, svc):
    await schedule_h.on_weekday(callback, kb.AdmWeekdayCb(weekday=1, action="save_yes"), state, svc)
    svc.set_work_schedule.assert_not_awaited()
    assert callback.message.edit_text.await_args.args[0] == texts.ADMIN_ERROR


async def test_long_warning_list_is_truncated(callback, state, svc):
    svc.bookings_outside_work_day.return_value = [SimpleNamespace(id=i) for i in range(40)]
    svc.booking_details.return_value = [details(i) for i in range(40)]
    await schedule_h.on_weekday(callback, kb.AdmWeekdayCb(weekday=1, action="off"), state, svc)
    text = callback.message.edit_text.await_args.args[0]
    assert len(text) < 4096
    assert texts.ADMIN_SCHEDULE_WARN_MORE.format(count=20) in text


async def test_hours_invalid_detected_by_warning_check_shows_error(state, svc):
    await state.set_state(AdminFlow.waiting_hours)
    await state.update_data(weekday=1)
    svc.bookings_outside_work_day.side_effect = InvalidWorkDay("bad_break")
    m = message("10:00-18:00 14:00-15:00")
    await schedule_h.on_hours(m, state, svc)
    assert m.answer.await_args.args[0] == texts.ADMIN_HOURS_BAD_BREAK
    svc.set_work_schedule.assert_not_awaited()


async def test_new_dayoff_callbacks_are_routed_and_guarded(svc):
    from aiogram.types import Update

    from app.bot.middlewares import ServicesMiddleware

    dp = Dispatcher(storage=MemoryStorage())
    dp.callback_query.outer_middleware(ServicesMiddleware(svc, None))
    dp.include_router(build_router([1]))
    for data, mock in (
        (kb.AdmMenuCb(action="daysoff").pack(), svc.list_days_off),
        (kb.AdmDayCb(kind="reopen", day="2026-11-10").pack(), svc.remove_day_off),
    ):
        for uid, expected in ((2, 0), (1, 1)):
            mock.reset_mock()
            bot = AsyncMock()
            bot.id = 1
            update = Update.model_validate(
                {
                    "update_id": 1,
                    "callback_query": {
                        "id": "1",
                        "from": {"id": uid, "is_bot": False, "first_name": "x"},
                        "chat_instance": "1",
                        "data": data,
                        "message": {
                            "message_id": 1,
                            "date": 0,
                            "chat": {"id": 1, "type": "private"},
                        },
                    },
                },
                context={"bot": bot},
            )
            await dp.feed_update(bot, update)
            assert mock.await_count == expected


# ---- F5: admin is told who could not be notified --------------------------------


def _forbidden():
    from aiogram.exceptions import TelegramForbiddenError

    return TelegramForbiddenError(method=MagicMock(), message="blocked")


async def test_notify_cancelled_returns_items_it_failed_to_deliver(svc, bot):
    from aiogram.exceptions import TelegramBadRequest

    from app.bot.handlers.admin.common import notify_cancelled

    items = [details(5, tg=1), details(6, tg=2), details(7, tg=3)]
    bot.send_message.side_effect = [
        _forbidden(),
        None,
        TelegramBadRequest(method=MagicMock(), message="chat not found"),
    ]
    failed = await notify_cancelled(bot, items, svc)
    assert failed == [items[0], items[2]]
    assert bot.send_message.await_count == 3


async def test_notify_cancelled_all_delivered_returns_empty(svc, bot):
    from app.bot.handlers.admin.common import notify_cancelled

    assert await notify_cancelled(bot, [details(5)], svc) == []


async def test_admin_cancel_says_client_not_notified_when_send_fails(callback, svc, bot):
    bot.send_message.side_effect = _forbidden()
    await bookings_h.on_cancel_yes(
        callback, kb.AdmBookingCb(booking_id=5, action="cancel_yes"), svc, bot
    )
    text = callback.message.edit_text.await_args.args[0]
    assert text == texts.ADMIN_CANCELLED_NOT_NOTIFIED.format(names="&lt;b&gt;Аня")
    assert "клиент уведомлён" not in text


async def test_dayoff_confirm_lists_clients_who_could_not_be_notified(callback, svc, bot):
    svc.set_day_off.return_value = [SimpleNamespace(id=5), SimpleNamespace(id=6)]
    svc.booking_details.return_value = [
        details(5, name="<i>Боб", tg=1),
        details(6, name="Вера", tg=2),
    ]
    bot.send_message.side_effect = [_forbidden(), None]
    await schedule_h.on_dayoff_confirm(
        callback, kb.AdmDayCb(kind="off_yes", day="2026-11-03"), svc, bot
    )
    text = callback.message.edit_text.await_args.args[0]
    assert text == (
        texts.ADMIN_DAYOFF_DONE_NOTIFIED.format(date="вт 03.11", count=2)
        + "\n"
        + texts.ADMIN_NOT_NOTIFIED.format(names="&lt;i&gt;Боб")
    )
    assert "Вера" not in text.split("\n")[-1]


async def test_dayoff_confirm_all_delivered_keeps_plain_wording(callback, svc, bot):
    svc.set_day_off.return_value = [SimpleNamespace(id=5)]
    await schedule_h.on_dayoff_confirm(
        callback, kb.AdmDayCb(kind="off_yes", day="2026-11-03"), svc, bot
    )
    assert callback.message.edit_text.await_args.args[0] == (
        texts.ADMIN_DAYOFF_DONE_NOTIFIED.format(date="вт 03.11", count=1)
    )


# ---- M1: admin panel works in private chats only -----------------------------------


def _dp(svc):
    from app.bot.middlewares import ServicesMiddleware

    dp = Dispatcher(storage=MemoryStorage())
    mw = ServicesMiddleware(svc, None)
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(build_router([1]))
    return dp


def _msg_update(text, chat_type):
    from aiogram.types import Update

    bot = AsyncMock()
    bot.id = 1
    return bot, Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": 1, "type": chat_type},
                "from": {"id": 1, "is_bot": False, "first_name": "x"},
                "text": text,
            },
        },
        context={"bot": bot},
    )


def _cb_update(data, chat_type):
    from aiogram.types import Update

    bot = AsyncMock()
    bot.id = 1
    cb = {
        "id": "1",
        "from": {"id": 1, "is_bot": False, "first_name": "x"},
        "chat_instance": "1",
        "data": data,
    }
    if chat_type:
        cb["message"] = {"message_id": 1, "date": 0, "chat": {"id": 1, "type": chat_type}}
    return bot, Update.model_validate(
        {"update_id": 1, "callback_query": cb}, context={"bot": bot}
    )


async def test_admin_command_works_in_private_chat(svc):
    bot, update = _msg_update("/admin", "private")
    await _dp(svc).feed_update(bot, update)
    assert bot.await_count == 1


async def test_admin_command_from_admin_in_group_is_ignored(svc):
    for chat_type in ("group", "supergroup", "channel"):
        bot, update = _msg_update("/admin", chat_type)
        await _dp(svc).feed_update(bot, update)
        assert bot.await_count == 0, chat_type


async def test_admin_callback_from_admin_in_group_is_ignored(svc):
    data = kb.AdmExportCb(period="week", fmt="xlsx").pack()
    for chat_type in ("group", "supergroup"):
        bot, update = _cb_update(data, chat_type)
        await _dp(svc).feed_update(bot, update)
        assert bot.await_count == 0, chat_type
    svc.list_rows.assert_not_called()


async def test_admin_callback_without_message_is_ignored(svc):
    bot, update = _cb_update(kb.AdmMenuCb(action="menu").pack(), None)
    await _dp(svc).feed_update(bot, update)
    assert bot.await_count == 0


async def test_admin_callback_in_private_chat_is_handled(svc):
    bot, update = _cb_update(kb.AdmMenuCb(action="menu").pack(), "private")
    await _dp(svc).feed_update(bot, update)
    assert bot.await_count >= 1
