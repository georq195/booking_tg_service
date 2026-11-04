from datetime import date
from zoneinfo import ZoneInfo

from aiogram import Dispatcher

from app.bot.keyboards.inline import ConfirmCb, DateCb, ServiceCb, SlotCb
from app.main import build_dispatcher
from app.services.booking_service import BookingService
from app.utils.dates import bookable_days, day_label, next_days


async def test_build_dispatcher_assembles_routers_and_middleware(session_factory):
    svc = BookingService(session_factory, ZoneInfo("Europe/Moscow"), 30, 2)
    dp = build_dispatcher(svc, session_factory)
    assert isinstance(dp, Dispatcher)
    assert dp.message.outer_middleware
    assert dp.callback_query.outer_middleware


def test_callback_data_fits_telegram_limit():
    packed = [
        ServiceCb(service_id=2**31).pack(),
        DateCb(day=date.max.isoformat()).pack(),
        SlotCb(ts=2**40).pack(),
        ConfirmCb().pack(),
    ]
    assert all(len(p.encode()) <= 64 for p in packed)


def test_day_label_fixed_russian_weekdays():
    assert day_label(date(2026, 11, 2)) == "пн 02.11"
    assert day_label(date(2026, 11, 8)) == "вс 08.11"


def test_next_days_starts_today_and_counts():
    days = next_days(date(2026, 11, 2))
    assert len(days) == 14
    assert days[0] == date(2026, 11, 2)
    assert days[-1] == date(2026, 11, 15)


def test_bookable_days_start_tomorrow_and_count():
    days = bookable_days(date(2026, 11, 2))
    assert len(days) == 14
    assert days[0] == date(2026, 11, 3)
    assert days[-1] == date(2026, 11, 16)


async def test_dispatcher_can_be_built_twice(session_factory):
    svc = BookingService(session_factory, ZoneInfo("Europe/Moscow"), 30, 2)
    build_dispatcher(svc, session_factory)
    build_dispatcher(svc, session_factory)


def test_build_router_returns_fresh_routers_attachable_to_separate_dispatchers():
    from app.bot.handlers import build_router

    a, b = build_router(), build_router()
    assert a is not b
    Dispatcher().include_router(a)
    Dispatcher().include_router(b)
