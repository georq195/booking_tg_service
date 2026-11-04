from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Booking, BookingStatus, Service, User, WorkSchedule


async def _make_user_service(session):
    user = User(telegram_id=1, name="Ivan")
    service = Service(title="Haircut", duration_min=30, price=1000, is_active=True)
    session.add_all([user, service])
    await session.flush()
    return user, service


async def test_booking_defaults_to_active(session):
    user, service = await _make_user_service(session)
    start = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    booking = Booking(
        user_id=user.id,
        service_id=service.id,
        start_at=start,
        end_at=start + timedelta(minutes=30),
    )
    session.add(booking)
    await session.commit()
    assert booking.status == BookingStatus.active
    assert booking.reminded_24h is False
    assert booking.reminded_2h is False


async def test_telegram_id_is_unique(session):
    session.add_all([User(telegram_id=5, name="A"), User(telegram_id=5, name="B")])
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_weekday_is_unique(session):
    session.add_all(
        [
            WorkSchedule(weekday=0, start_time=time(9), end_time=time(18)),
            WorkSchedule(weekday=0, start_time=time(10), end_time=time(19)),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_datetimes_roundtrip_as_aware_utc(session_factory):
    start = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    async with session_factory() as s:
        user, service = await _make_user_service(s)
        booking = Booking(
            user_id=user.id,
            service_id=service.id,
            start_at=start,
            end_at=start + timedelta(minutes=30),
        )
        s.add(booking)
        await s.commit()
        booking_id = booking.id
    async with session_factory() as s:
        loaded = await s.get(Booking, booking_id)
        assert loaded.start_at.tzinfo is not None
        assert loaded.start_at == start
        assert loaded.end_at == start + timedelta(minutes=30)
        assert loaded.created_at.tzinfo is not None


async def test_booking_with_nonexistent_user_violates_foreign_key(session):
    _, service = await _make_user_service(session)
    start = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    session.add(
        Booking(
            user_id=999,
            service_id=service.id,
            start_at=start,
            end_at=start + timedelta(minutes=30),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
