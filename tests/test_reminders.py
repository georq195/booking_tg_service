from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.db.models import Booking, BookingStatus, Service, User
from app.main import build_scheduler, is_permanent_send_error
from app.services.reminders import ReminderService
from app.utils import texts

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
H24_PREFIX = texts.REMINDER_24H.split("\n")[0]
H2_PREFIX = texts.REMINDER_2H.split("\n")[0]


class FakeBot:
    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail or {}

    async def send_message(self, chat_id, text):
        if chat_id in self.fail:
            raise self.fail[chat_id]
        self.sent.append((chat_id, text))


class BlockedError(Exception):
    pass


def permanent(exc):
    return isinstance(exc, BlockedError)


async def add_booking(
    session_factory, start_at, created_at=None, status=BookingStatus.active,
    telegram_id=1, title="Cut",
):
    async with session_factory() as s:
        user = User(telegram_id=telegram_id, name="U")
        service = Service(title=title, duration_min=60, price=1, is_active=True)
        s.add_all([user, service])
        await s.flush()
        b = Booking(
            user_id=user.id, service_id=service.id, start_at=start_at,
            end_at=start_at + timedelta(hours=1), status=status,
            created_at=created_at or NOW - timedelta(days=5),
        )
        s.add(b)
        await s.commit()
        return b.id


async def flags(session_factory, booking_id):
    async with session_factory() as s:
        b = await s.get(Booking, booking_id)
        return b.reminded_24h, b.reminded_2h


def make(session_factory, bot, is_permanent=None):
    return ReminderService(session_factory, bot, TZ, is_permanent_error=is_permanent)


async def test_sends_24h_reminder_once(session_factory):
    await add_booking(session_factory, NOW + timedelta(hours=23))
    bot = FakeBot()
    svc = make(session_factory, bot)
    assert await svc.send_due(NOW) == 1
    assert await svc.send_due(NOW) == 0
    assert len(bot.sent) == 1 and bot.sent[0][0] == 1


async def test_sends_2h_reminder_once(session_factory):
    bid = await add_booking(session_factory, NOW + timedelta(hours=1, minutes=30))
    bot = FakeBot()
    svc = make(session_factory, bot)
    assert await svc.send_due(NOW) == 1
    assert await svc.send_due(NOW) == 0
    assert len(bot.sent) == 1
    assert await flags(session_factory, bid) == (True, True)


async def test_both_24h_then_2h_are_sent_separately(session_factory):
    start = NOW + timedelta(hours=23)
    bid = await add_booking(session_factory, start)
    bot = FakeBot()
    svc = make(session_factory, bot)
    await svc.send_due(NOW)
    assert await flags(session_factory, bid) == (True, False)
    assert await svc.send_due(start - timedelta(hours=1)) == 1
    assert len(bot.sent) == 2
    assert H24_PREFIX in bot.sent[0][1] and H2_PREFIX not in bot.sent[0][1]
    assert H2_PREFIX in bot.sent[1][1] and H24_PREFIX not in bot.sent[1][1]


async def test_cancelled_booking_gets_no_reminder(session_factory):
    await add_booking(
        session_factory, NOW + timedelta(hours=1), status=BookingStatus.cancelled
    )
    bot = FakeBot()
    assert await make(session_factory, bot).send_due(NOW) == 0
    assert bot.sent == []


async def test_past_booking_gets_no_reminder(session_factory):
    bid = await add_booking(session_factory, NOW - timedelta(minutes=5))
    bot = FakeBot()
    assert await make(session_factory, bot).send_due(NOW) == 0
    assert bot.sent == []
    assert await flags(session_factory, bid) == (False, False)


async def test_booking_created_less_than_24h_ahead_skips_24h_reminder(session_factory):
    start = NOW + timedelta(hours=19)
    bid = await add_booking(session_factory, start, created_at=NOW - timedelta(hours=1))
    bot = FakeBot()
    svc = make(session_factory, bot)
    assert await svc.send_due(NOW) == 0
    assert bot.sent == []
    assert await flags(session_factory, bid) == (True, False)
    # the 2h reminder still goes out later
    assert await svc.send_due(start - timedelta(hours=2)) == 1


async def test_booking_created_inside_2h_window_skips_2h_reminder(session_factory):
    start = NOW + timedelta(hours=1)
    bid = await add_booking(session_factory, start, created_at=NOW - timedelta(minutes=10))
    bot = FakeBot()
    assert await make(session_factory, bot).send_due(NOW) == 0
    assert bot.sent == []
    assert await flags(session_factory, bid) == (True, True)


async def test_both_windows_due_sends_only_2h(session_factory):
    bid = await add_booking(session_factory, NOW + timedelta(hours=1))
    bot = FakeBot()
    svc = make(session_factory, bot)
    assert await svc.send_due(NOW) == 1
    assert len(bot.sent) == 1
    assert H2_PREFIX in bot.sent[0][1]
    assert H24_PREFIX not in bot.sent[0][1]
    assert await flags(session_factory, bid) == (True, True)
    assert await svc.send_due(NOW) == 0


async def test_not_due_yet_sends_nothing(session_factory):
    bid = await add_booking(session_factory, NOW + timedelta(hours=25))
    bot = FakeBot()
    assert await make(session_factory, bot).send_due(NOW) == 0
    assert await flags(session_factory, bid) == (False, False)


async def test_blocked_bot_marks_flag_and_does_not_stop_others(session_factory):
    start = NOW + timedelta(hours=1)
    blocked = await add_booking(session_factory, start, telegram_id=1)
    ok = await add_booking(session_factory, start, telegram_id=2)
    bot = FakeBot(fail={1: BlockedError("blocked")})
    svc = make(session_factory, bot, permanent)
    assert await svc.send_due(NOW) == 1
    assert [c for c, _ in bot.sent] == [2]
    assert await flags(session_factory, blocked) == (True, True)
    assert await flags(session_factory, ok) == (True, True)
    assert await svc.send_due(NOW) == 0


async def test_transient_failure_keeps_flag_unset_and_retries(session_factory):
    start = NOW + timedelta(hours=1)
    bad = await add_booking(session_factory, start, telegram_id=1)
    ok = await add_booking(session_factory, start, telegram_id=2)
    bot = FakeBot(fail={1: RuntimeError("network")})
    svc = make(session_factory, bot, permanent)
    assert await svc.send_due(NOW) == 1
    assert await flags(session_factory, bad) == (False, False)
    assert await flags(session_factory, ok) == (True, True)
    bot.fail = {}
    assert await svc.send_due(NOW) == 1
    assert await flags(session_factory, bad) == (True, True)


async def test_message_has_local_time_and_escaped_title(session_factory):
    start = datetime(2026, 11, 2, 9, 30, tzinfo=UTC)  # 12:30 Moscow
    await add_booking(session_factory, start, title="<b>Cut</b> & co")
    bot = FakeBot()
    await make(session_factory, bot).send_due(NOW)
    text = bot.sent[0][1]
    assert "12:30" in text and "02.11" in text
    assert "&lt;b&gt;Cut&lt;/b&gt; &amp; co" in text
    assert "<b>Cut</b>" not in text


async def test_flags_persist_in_db(session_factory):
    bid = await add_booking(session_factory, NOW + timedelta(hours=23))
    await make(session_factory, FakeBot()).send_due(NOW)
    async with session_factory() as s:
        b = (await s.scalars(select(Booking).where(Booking.id == bid))).one()
        assert b.reminded_24h is True


def test_is_permanent_send_error():
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
    from aiogram.methods import SendMessage

    m = SendMessage(chat_id=1, text="x")
    assert is_permanent_send_error(TelegramForbiddenError(m, "Forbidden: bot was blocked by the user"))
    assert is_permanent_send_error(TelegramBadRequest(m, "Bad Request: chat not found"))
    assert not is_permanent_send_error(TelegramBadRequest(m, "Bad Request: message is too long"))
    assert not is_permanent_send_error(TelegramRetryAfter(m, "Flood", 5))
    assert not is_permanent_send_error(RuntimeError("x"))


async def test_scheduler_job_registered_every_minute(session_factory):
    svc = make(session_factory, FakeBot())
    scheduler = build_scheduler(svc)
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 30
    assert job.trigger.interval == timedelta(minutes=1)
    assert job.func == svc.run_once
