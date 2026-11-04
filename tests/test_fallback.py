import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from aiogram import Dispatcher
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from app.bot.handlers import build_router
from app.bot.middlewares import ServicesMiddleware
from app.bot.states import AdminFlow
from app.main import bot_commands, set_bot_commands, warn_if_no_admins
from app.utils import texts

TZ = ZoneInfo("Europe/Moscow")


def make_dp(svc, admin_ids=(1,)):
    dp = Dispatcher(storage=MemoryStorage())
    mw = ServicesMiddleware(svc, None)
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(build_router(admin_ids))
    return dp


def msg_update(text, uid=1, chat_type="private"):
    bot = AsyncMock()
    bot.id = 1
    update = Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": 1, "type": chat_type},
                "from": {"id": uid, "is_bot": False, "first_name": "x"},
                "text": text,
            },
        },
        context={"bot": bot},
    )
    return bot, update


def sent_texts(bot):
    return [c.args[0].text for c in bot.await_args_list if hasattr(c.args[0], "text")]


def make_svc():
    s = MagicMock()
    s.tz = TZ
    s.set_work_schedule = AsyncMock()
    s.get_work_schedule = AsyncMock(return_value={})
    s.bookings_outside_work_day = AsyncMock(return_value=[])
    return s


async def test_fallback_answers_stateless_private_message_with_hint():
    dp = make_dp(make_svc())
    bot, update = msg_update("привет", uid=5)
    await dp.feed_update(bot, update)
    assert sent_texts(bot) == [texts.FALLBACK_HINT]
    assert "/start" in texts.FALLBACK_HINT and "/my" in texts.FALLBACK_HINT


async def test_fallback_answers_unknown_command():
    dp = make_dp(make_svc())
    bot, update = msg_update("/help", uid=5)
    await dp.feed_update(bot, update)
    assert sent_texts(bot) == [texts.FALLBACK_HINT]


async def test_fallback_ignores_group_chats():
    dp = make_dp(make_svc())
    bot, update = msg_update("привет", uid=5, chat_type="group")
    await dp.feed_update(bot, update)
    assert sent_texts(bot) == []


async def test_fallback_does_not_swallow_message_in_admin_fsm_state():
    svc = make_svc()
    dp = make_dp(svc)
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    await dp.storage.set_state(key, AdminFlow.waiting_hours)
    await dp.storage.set_data(key, {"weekday": 1})
    bot, update = msg_update("10:00-18:00", uid=1)
    await dp.feed_update(bot, update)
    svc.set_work_schedule.assert_awaited_once()
    assert texts.FALLBACK_HINT not in sent_texts(bot)


async def test_fallback_does_not_answer_when_state_handler_rejects_input():
    # in a state but unmatched input: the state handler's own prompt, not the hint
    svc = make_svc()
    dp = make_dp(svc)
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    await dp.storage.set_state(key, AdminFlow.waiting_hours)
    await dp.storage.set_data(key, {"weekday": 1})
    bot, update = msg_update("абв", uid=1)
    await dp.feed_update(bot, update)
    assert sent_texts(bot) == [texts.ADMIN_HOURS_BAD_FORMAT]


def test_greeting_and_booked_mention_my():
    assert "/my" in texts.GREETING
    assert "/my" in texts.BOOKED


def test_bot_commands_are_start_and_my_with_russian_descriptions():
    cmds = bot_commands()
    assert [c.command for c in cmds] == ["start", "my"]
    assert [c.description for c in cmds] == [
        texts.BOT_CMD_START_DESC,
        texts.BOT_CMD_MY_DESC,
    ]


async def test_set_bot_commands_calls_bot():
    bot = SimpleNamespace(set_my_commands=AsyncMock())
    await set_bot_commands(bot)
    bot.set_my_commands.assert_awaited_once_with(bot_commands())


def test_warns_when_no_admins(caplog):
    with caplog.at_level(logging.WARNING):
        warn_if_no_admins(())
    assert any("ADMIN_IDS" in r.message and r.levelno == logging.WARNING for r in caplog.records)


def test_no_warning_with_admins(caplog):
    with caplog.at_level(logging.WARNING):
        warn_if_no_admins((1,))
    assert not caplog.records
