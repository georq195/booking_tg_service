import asyncio
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db.models import Booking, BookingStatus, DayOff, Service, User, WorkSchedule
from app.services.booking_service import BookingService
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
from sqlalchemy import select

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)  # Monday 09:00 Moscow
MONDAY = NOW.astimezone(TZ).date()
TUESDAY = MONDAY + timedelta(days=1)


def local(day, hour):
    return datetime.combine(day, time(hour), tzinfo=TZ).astimezone(UTC)


@pytest.fixture
async def env(session_factory):
    async with session_factory() as s:
        users = [User(telegram_id=1, name="A"), User(telegram_id=2, name="B")]
        service = Service(title="Cut", duration_min=60, price=1000, is_active=True)
        s.add_all(users + [service])
        s.add_all(
            WorkSchedule(weekday=d, start_time=time(10), end_time=time(18))
            for d in range(5)
        )
        await s.commit()
        user_id, other_id, service_id = users[0].id, users[1].id, service.id
    svc = BookingService(session_factory, TZ, step_min=60, cancel_deadline_hours=2)
    return svc, user_id, other_id, service_id


async def count_bookings(session_factory):
    async with session_factory() as s:
        return len((await s.scalars(select(Booking))).all())


async def test_create_booking_removes_slot_from_free_slots(env):
    svc, uid, _, sid = env
    start = local(TUESDAY, 12)
    booking = await svc.create(uid, sid, start, now=NOW)
    assert booking.status == BookingStatus.active
    assert booking.end_at == start + timedelta(minutes=60)
    assert start not in await svc.get_free_slots(TUESDAY, sid, now=NOW)


async def test_create_same_slot_twice_raises_slot_taken(env):
    svc, uid, other, sid = env
    start = local(TUESDAY, 12)
    await svc.create(uid, sid, start, now=NOW)
    with pytest.raises(SlotTaken):
        await svc.create(other, sid, start, now=NOW)


async def test_concurrent_create_only_one_wins(env, session_factory):
    svc, uid, other, sid = env
    start = local(TUESDAY, 12)
    results = await asyncio.gather(
        svc.create(uid, sid, start, now=NOW),
        svc.create(other, sid, start, now=NOW),
        return_exceptions=True,
    )
    assert sum(isinstance(r, Booking) for r in results) == 1
    assert sum(isinstance(r, SlotTaken) for r in results) == 1
    assert await count_bookings(session_factory) == 1


async def test_create_slot_in_past_raises_slot_in_past(env):
    svc, uid, _, sid = env
    with pytest.raises(SlotInPast):
        await svc.create(uid, sid, local(MONDAY, 8), now=NOW)


async def test_cancel_frees_slot(env):
    svc, uid, _, sid = env
    start = local(TUESDAY, 12)
    booking = await svc.create(uid, sid, start, now=NOW)
    cancelled = await svc.cancel(booking.id, uid, now=NOW)
    assert cancelled.status == BookingStatus.cancelled
    assert start in await svc.get_free_slots(TUESDAY, sid, now=NOW)


async def test_cancel_twice_raises_already_cancelled(env):
    svc, uid, _, sid = env
    booking = await svc.create(uid, sid, local(TUESDAY, 12), now=NOW)
    await svc.cancel(booking.id, uid, now=NOW)
    with pytest.raises(AlreadyCancelled):
        await svc.cancel(booking.id, uid, now=NOW)


async def test_cancel_less_than_deadline_raises_too_late(env):
    svc, uid, _, sid = env
    start = local(MONDAY, 11)  # exactly the deadline is allowed
    # booked the day before: same-day booking is closed
    booking = await svc.create(uid, sid, start, now=NOW - timedelta(days=1))
    late_now = start - timedelta(hours=2) + timedelta(minutes=1)
    with pytest.raises(TooLateToChange):
        await svc.cancel(booking.id, uid, now=late_now)
    cancelled = await svc.cancel(booking.id, uid, now=start - timedelta(hours=2))
    assert cancelled.status == BookingStatus.cancelled


async def test_cancel_foreign_booking_raises_not_your_booking(env):
    svc, uid, other, sid = env
    booking = await svc.create(uid, sid, local(TUESDAY, 12), now=NOW)
    with pytest.raises(NotYourBooking):
        await svc.cancel(booking.id, other, now=NOW)
    with pytest.raises(BookingNotFound):
        await svc.cancel(9999, uid, now=NOW)


async def test_reschedule_moves_booking_and_frees_old_slot(env, session_factory):
    svc, uid, _, sid = env
    old_start, new_start = local(TUESDAY, 12), local(TUESDAY, 14)
    old = await svc.create(uid, sid, old_start, now=NOW)
    new = await svc.reschedule(old.id, uid, new_start, now=NOW)
    assert new.id != old.id
    assert new.status == BookingStatus.active and new.start_at == new_start
    async with session_factory() as s:
        assert (await s.get(Booking, old.id)).status == BookingStatus.cancelled
    free = await svc.get_free_slots(TUESDAY, sid, now=NOW)
    assert old_start in free and new_start not in free


async def test_reschedule_to_taken_slot_keeps_old_booking_active(env, session_factory):
    svc, uid, other, sid = env
    old = await svc.create(uid, sid, local(TUESDAY, 12), now=NOW)
    taken = local(TUESDAY, 14)
    await svc.create(other, sid, taken, now=NOW)
    with pytest.raises(SlotTaken):
        await svc.reschedule(old.id, uid, taken, now=NOW)
    async with session_factory() as s:
        assert (await s.get(Booking, old.id)).status == BookingStatus.active
    assert await count_bookings(session_factory) == 2


async def test_reschedule_to_same_slot_is_noop(env, session_factory):
    svc, uid, _, sid = env
    old = await svc.create(uid, sid, local(TUESDAY, 12), now=NOW)
    same = await svc.reschedule(old.id, uid, old.start_at, now=NOW)
    assert same.id == old.id and same.status == BookingStatus.active
    assert await count_bookings(session_factory) == 1


async def test_get_free_slots_empty_on_day_off(env, session_factory):
    svc, _, _, sid = env
    async with session_factory() as s:
        s.add(DayOff(day=TUESDAY, reason="holiday"))
        await s.commit()
    assert await svc.get_free_slots(TUESDAY, sid, now=NOW) == []


@pytest.mark.parametrize("step, hours", [(0, 2), (-5, 2), (30, -1)])
def test_constructor_rejects_invalid_settings(session_factory, step, hours):
    with pytest.raises(ValueError):
        BookingService(session_factory, TZ, step_min=step, cancel_deadline_hours=hours)


async def test_list_active_for_user_excludes_cancelled_and_past(env, session_factory):
    svc, uid, other, sid = env
    later = await svc.create(uid, sid, local(TUESDAY, 14), now=NOW)
    sooner = await svc.create(uid, sid, local(TUESDAY, 11), now=NOW)
    cancelled = await svc.create(uid, sid, local(TUESDAY, 16), now=NOW)
    await svc.cancel(cancelled.id, uid, now=NOW)
    await svc.create(other, sid, local(TUESDAY, 12), now=NOW)
    async with session_factory() as s:
        past = Booking(
            user_id=uid,
            service_id=sid,
            start_at=NOW - timedelta(hours=1),
            end_at=NOW,
            status=BookingStatus.active,
        )
        s.add(past)
        await s.commit()
        past_id = past.id
    result = await svc.list_active_for_user(uid, now=NOW)
    assert [b.id for b in result] == [sooner.id, later.id]
    assert past_id not in [b.id for b in result]


async def test_service_titles_maps_ids_including_inactive(env, session_factory):
    svc, _, _, sid = env
    async with session_factory() as s:
        old = Service(title="Old", duration_min=30, price=1, is_active=False)
        s.add(old)
        await s.commit()
        old_id = old.id
    assert await svc.service_titles([sid, old_id]) == {sid: "Cut", old_id: "Old"}


async def test_done_booking_cannot_be_cancelled_or_rescheduled(env, session_factory):
    svc, uid, _, sid = env
    booking = await svc.create(uid, sid, local(TUESDAY, 12), now=NOW)
    async with session_factory() as s:
        (await s.get(Booking, booking.id)).status = BookingStatus.done
        await s.commit()
    with pytest.raises(BookingNotActive):
        await svc.cancel(booking.id, uid, now=NOW)
    with pytest.raises(BookingNotActive):
        await svc.reschedule(booking.id, uid, local(TUESDAY, 14), now=NOW)
    async with session_factory() as s:
        assert (await s.get(Booking, booking.id)).status == BookingStatus.done


async def test_cancelled_booking_still_raises_already_cancelled(env):
    svc, uid, _, sid = env
    booking = await svc.create(uid, sid, local(TUESDAY, 12), now=NOW)
    await svc.cancel(booking.id, uid, now=NOW)
    with pytest.raises(AlreadyCancelled):
        await svc.cancel(booking.id, uid, now=NOW)


async def test_today_has_no_free_slots(env):
    svc, _, _, sid = env
    # Monday 09:00 Moscow, work 10-18: today's later slots must NOT be offered
    assert await svc.get_free_slots(MONDAY, sid, now=NOW) == []


async def test_tomorrow_is_the_first_bookable_day(env):
    svc, _, _, sid = env
    slots = await svc.get_free_slots(TUESDAY, sid, now=NOW)
    assert slots[0] == local(TUESDAY, 10)


async def test_create_for_today_raises_slot_too_soon(env, session_factory):
    svc, uid, _, sid = env
    with pytest.raises(SlotTooSoon):
        await svc.create(uid, sid, local(MONDAY, 15), now=NOW)
    assert await count_bookings(session_factory) == 0


async def test_past_slot_still_raises_slot_in_past_not_too_soon(env):
    svc, uid, _, sid = env
    with pytest.raises(SlotInPast):
        await svc.create(uid, sid, local(MONDAY, 8), now=NOW)


async def test_same_day_rule_follows_local_date_not_utc(env):
    svc, uid, _, sid = env
    # Tuesday 00:10 Moscow == Monday 21:10 UTC: Tuesday is already "today" locally
    now = datetime(2026, 11, 2, 21, 10, tzinfo=UTC)
    assert await svc.get_free_slots(TUESDAY, sid, now=now) == []
    wednesday = TUESDAY + timedelta(days=1)
    assert (await svc.get_free_slots(wednesday, sid, now=now))[0] == local(wednesday, 10)
    with pytest.raises(SlotTooSoon):
        await svc.create(uid, sid, local(TUESDAY, 12), now=now)
    # Monday 23:30 Moscow (20:30 UTC): Tuesday is tomorrow and bookable
    late = datetime(2026, 11, 2, 20, 30, tzinfo=UTC)
    assert (await svc.get_free_slots(TUESDAY, sid, now=late))[0] == local(TUESDAY, 10)


async def test_reschedule_to_today_raises_slot_too_soon_and_keeps_old(env):
    svc, uid, _, sid = env
    old = await svc.create(uid, sid, local(TUESDAY, 12), now=NOW)
    with pytest.raises(SlotTooSoon):
        await svc.reschedule(old.id, uid, local(MONDAY, 15), now=NOW)
    active = await svc.list_active_for_user(uid, now=NOW)
    assert [b.id for b in active] == [old.id]
