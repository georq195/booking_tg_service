from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.bot.filters import IsAdmin
from app.db.models import Booking, BookingStatus, DayOff, Service, User, WorkSchedule
from app.services.booking_service import BookingService
from app.services.errors import (
    AlreadyCancelled,
    BookingNotFound,
    InvalidWorkDay,
    ServiceNotFound,
)
from app.services.slots import WorkDay
from app.utils.texts import format_booking_line

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
TUESDAY = date(2026, 11, 3)


def at(day, hour):
    return datetime.combine(day, time(hour), tzinfo=TZ).astimezone(UTC)


@pytest.fixture
async def env(session_factory):
    async with session_factory() as s:
        user = User(telegram_id=77, name="Аня", phone="+7")
        service = Service(title="Cut", duration_min=60, price=1000, is_active=True)
        s.add_all([user, service])
        s.add_all(
            WorkSchedule(weekday=d, start_time=time(10), end_time=time(18))
            for d in range(5)
        )
        await s.commit()
        ids = (user.id, service.id)
    svc = BookingService(session_factory, TZ, step_min=60, cancel_deadline_hours=2)
    return svc, ids[0], ids[1]


async def test_set_day_off_with_bookings_requires_confirm(env, session_factory):
    svc, uid, sid = env
    booking = await svc.create(uid, sid, at(TUESDAY, 12), now=NOW)
    affected = await svc.set_day_off(TUESDAY, "болею", confirm=False)
    assert [b.id for b in affected] == [booking.id]
    async with session_factory() as s:
        assert await s.scalar(select(DayOff)) is None
        assert (await s.get(Booking, booking.id)).status == BookingStatus.active


async def test_set_day_off_confirmed_cancels_bookings(env, session_factory):
    svc, uid, sid = env
    booking = await svc.create(uid, sid, at(TUESDAY, 12), now=NOW)
    cancelled = await svc.set_day_off(TUESDAY, "болею", confirm=True)
    assert [b.id for b in cancelled] == [booking.id]
    async with session_factory() as s:
        assert (await s.scalar(select(DayOff))).reason == "болею"
        assert (await s.get(Booking, booking.id)).status == BookingStatus.cancelled
    assert await svc.get_free_slots(TUESDAY, sid, now=NOW) == []


async def test_set_day_off_without_bookings_closes_day(env):
    svc, _, sid = env
    assert await svc.set_day_off(TUESDAY, None, confirm=False) == []
    assert await svc.get_free_slots(TUESDAY, sid, now=NOW) == []


async def test_set_day_off_twice_is_not_an_error(env, session_factory):
    svc, _, _ = env
    await svc.set_day_off(TUESDAY, None, confirm=True)
    await svc.set_day_off(TUESDAY, "again", confirm=True)
    async with session_factory() as s:
        assert len((await s.scalars(select(DayOff))).all()) == 1


async def test_set_work_schedule_none_makes_weekday_off(env):
    svc, _, sid = env
    assert await svc.get_free_slots(TUESDAY, sid, now=NOW)  # tuesday works
    await svc.set_work_schedule(TUESDAY.weekday(), None)
    assert await svc.get_free_slots(TUESDAY, sid, now=NOW) == []
    await svc.set_work_schedule(TUESDAY.weekday(), None)  # idempotent


async def test_set_work_schedule_updates_and_creates(env):
    svc, _, _ = env
    work = WorkDay(time(9), time(13), time(11), time(12))
    await svc.set_work_schedule(0, work)  # update existing monday
    await svc.set_work_schedule(6, work)  # create sunday
    schedule = await svc.get_work_schedule()
    assert schedule[0] == work and schedule[6] == work
    with pytest.raises(ValueError):
        await svc.set_work_schedule(7, work)


async def test_list_for_day_sorted_by_time(env):
    svc, uid, sid = env
    late = await svc.create(uid, sid, at(TUESDAY, 15), now=NOW)
    early = await svc.create(uid, sid, at(TUESDAY, 11), now=NOW)
    other_day = await svc.create(uid, sid, at(TUESDAY + timedelta(days=1), 11), now=NOW)
    cancelled = await svc.create(uid, sid, at(TUESDAY, 13), now=NOW)
    await svc.cancel(cancelled.id, uid, now=NOW)
    result = await svc.list_for_day(TUESDAY)
    assert [b.id for b in result] == [early.id, late.id]
    assert other_day.id not in [b.id for b in result]


async def test_admin_cancel_ignores_deadline_and_owner(env):
    svc, uid, sid = env
    soon = at(TUESDAY, 10)
    booking = await svc.create(uid, sid, soon, now=NOW)
    result = await svc.admin_cancel(booking.id)  # within the 2h deadline
    assert result.status == BookingStatus.cancelled
    with pytest.raises(AlreadyCancelled):
        await svc.admin_cancel(booking.id)
    with pytest.raises(BookingNotFound):
        await svc.admin_cancel(9999)


async def test_booking_details_include_client_and_service(env):
    svc, uid, sid = env
    booking = await svc.create(uid, sid, at(TUESDAY, 12), now=NOW)
    await svc.admin_cancel(booking.id)  # any status
    (d,) = await svc.booking_details([booking.id])
    assert (d.user.telegram_id, d.user.name, d.service.title) == (77, "Аня", "Cut")
    assert await svc.booking_details([]) == []


async def test_services_crud(env):
    svc, _, _ = env
    new = await svc.add_service("  Color ", 90, 3000)
    assert new.title == "Color" and new.is_active
    updated = await svc.update_service(new.id, title="Dye", price=3500)
    assert (updated.title, updated.duration_min, updated.price) == ("Dye", 90, 3500)
    await svc.update_service(new.id, duration_min=45)
    assert (await svc.get_service(new.id)).duration_min == 45
    await svc.hide_service(new.id)
    assert new.id not in [s.id for s in await svc.list_active_services()]
    assert new.id in [s.id for s in await svc.list_all_services()]


async def test_services_validation_and_not_found(env):
    svc, _, _ = env
    for args in [
        ("", 60, 1),
        ("   ", 60, 1),
        ("x", 0, 1),
        ("x", -30, 1),
        ("x", 60, -5),
        ("x" * 256, 60, 1),
    ]:
        with pytest.raises(ValueError):
            await svc.add_service(*args)
    with pytest.raises(ValueError):
        await svc.update_service(env[2], duration_min=0)
    for call in (svc.get_service, svc.hide_service):
        with pytest.raises(ServiceNotFound):
            await call(9999)
    with pytest.raises(ServiceNotFound):
        await svc.update_service(9999, title="x")


def test_format_booking_line_escapes_html():
    booking = SimpleNamespace(start_at=datetime(2026, 11, 3, 9, 0, tzinfo=UTC))
    user = SimpleNamespace(name="<b>&")
    service = SimpleNamespace(title="<i>Cut</i>")
    line = format_booking_line(booking, user, service, TZ)
    assert line == "12:00 — &lt;b&gt;&amp; (&lt;i&gt;Cut&lt;/i&gt;)"
    assert "<b>" not in line and "<i>" not in line


async def test_is_admin_filter_rejects_non_admin():
    flt = IsAdmin([1, 2])
    admin = SimpleNamespace(from_user=SimpleNamespace(id=2))
    stranger = SimpleNamespace(from_user=SimpleNamespace(id=3))
    anonymous = SimpleNamespace(from_user=None)
    assert await flt(admin) is True
    assert await flt(stranger) is False
    assert await flt(anonymous) is False
    assert await IsAdmin([])(admin) is False


async def test_free_service_with_zero_price_is_allowed(env):
    svc, _, _ = env
    assert (await svc.add_service("Consult", 30, 0)).price == 0
    updated = await svc.update_service(env[2], price=0)
    assert updated.price == 0


@pytest.mark.parametrize(
    ("work", "reason"),
    [
        (WorkDay(time(18), time(10)), "end_before_start"),
        (WorkDay(time(10), time(10)), "end_before_start"),
        (WorkDay(time(10), time(18), time(14), None), "half_break"),
        (WorkDay(time(10), time(18), None, time(15)), "half_break"),
        (WorkDay(time(10), time(18), time(15), time(14)), "bad_break"),
        (WorkDay(time(10), time(18), time(14), time(14)), "bad_break"),
        (WorkDay(time(10), time(18), time(9), time(11)), "bad_break"),
        (WorkDay(time(10), time(18), time(17), time(19)), "bad_break"),
    ],
)
async def test_set_work_schedule_rejects_invalid_workday(env, work, reason):
    svc, _, _ = env
    before = await svc.get_work_schedule()
    with pytest.raises(InvalidWorkDay) as exc:
        await svc.set_work_schedule(0, work)
    assert exc.value.reason == reason
    assert await svc.get_work_schedule() == before  # nothing written


async def test_set_work_schedule_accepts_break_touching_edges(env):
    svc, _, _ = env
    work = WorkDay(time(10), time(18), time(10), time(18))
    await svc.set_work_schedule(0, work)
    assert (await svc.get_work_schedule())[0] == work


# ---- remove_day_off / list_days_off -------------------------------------------


async def test_remove_day_off_reopens_day_and_is_idempotent(env, session_factory):
    svc, uid, sid = env
    await svc.set_day_off(TUESDAY, None, confirm=True)
    assert await svc.get_free_slots(TUESDAY, sid, now=NOW) == []
    assert await svc.remove_day_off(TUESDAY) is True
    assert await svc.remove_day_off(TUESDAY) is False
    assert await svc.get_free_slots(TUESDAY, sid, now=NOW) != []
    async with session_factory() as s:
        assert await s.scalar(select(DayOff)) is None


async def test_list_days_off_returns_upcoming_sorted(env):
    svc, uid, sid = env
    for d in (date(2026, 11, 10), date(2026, 11, 3), date(2026, 10, 1)):
        await svc.set_day_off(d, None, confirm=True)
    days = await svc.list_days_off(date(2026, 11, 3))
    assert days == [date(2026, 11, 3), date(2026, 11, 10)]


# ---- bookings_outside_work_day (schedule-change warning) ----------------------


async def test_outside_work_day_all_future_bookings_when_weekday_off(env, session_factory):
    svc, uid, sid = env
    b = await svc.create(uid, sid, at(TUESDAY, 12), now=NOW)
    await svc.create(uid, sid, at(date(2026, 11, 4), 12), now=NOW)  # Wednesday
    found = await svc.bookings_outside_work_day(1, None, now=NOW)
    assert [x.id for x in found] == [b.id]


async def test_outside_work_day_only_bookings_outside_new_hours(env):
    svc, uid, sid = env
    early = await svc.create(uid, sid, at(TUESDAY, 10), now=NOW)
    inside = await svc.create(uid, sid, at(TUESDAY, 12), now=NOW)
    late = await svc.create(uid, sid, at(TUESDAY, 17), now=NOW)  # ends 18:00
    found = await svc.bookings_outside_work_day(
        1, WorkDay(time(11), time(17)), now=NOW
    )
    assert [x.id for x in found] == [early.id, late.id]
    assert inside.id not in [x.id for x in found]


async def test_outside_work_day_booking_overlapping_new_break(env):
    svc, uid, sid = env
    b = await svc.create(uid, sid, at(TUESDAY, 13), now=NOW)
    found = await svc.bookings_outside_work_day(
        1, WorkDay(time(10), time(18), time(13, 30), time(14, 30)), now=NOW
    )
    assert [x.id for x in found] == [b.id]


async def test_outside_work_day_ignores_cancelled_bookings(env):
    svc, uid, sid = env
    cancelled = await svc.create(uid, sid, at(TUESDAY, 12), now=NOW)
    await svc.admin_cancel(cancelled.id)
    assert await svc.bookings_outside_work_day(1, None, now=NOW) == []


async def test_outside_work_day_ignores_past_bookings(env):
    svc, uid, sid = env
    monday = date(2026, 11, 2)
    # booked the day before: same-day booking is closed
    await svc.create(uid, sid, at(monday, 12), now=NOW - timedelta(days=1))
    after = at(monday, 15)  # the booking has already started
    assert await svc.bookings_outside_work_day(0, None, now=after) == []


async def test_outside_work_day_unchanged_hours_affect_nothing(env):
    svc, uid, sid = env
    await svc.create(uid, sid, at(TUESDAY, 10), now=NOW)
    await svc.create(uid, sid, at(TUESDAY, 17), now=NOW)
    assert await svc.bookings_outside_work_day(1, WorkDay(time(10), time(18)), now=NOW) == []
