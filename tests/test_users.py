import asyncio
from datetime import time
from sqlalchemy import select

from app.db.models import Service, User
from app.services.booking_service import BookingService
from app.services.users import get_or_create_user
from zoneinfo import ZoneInfo


async def test_get_or_create_user_creates_once_and_updates_name(session_factory):
    a = await get_or_create_user(session_factory, 100, "Аня")
    b = await get_or_create_user(session_factory, 100, "Аня Н")
    assert a.id == b.id
    assert b.name == "Аня Н"
    async with session_factory() as s:
        assert len((await s.scalars(select(User))).all()) == 1


async def test_list_active_services_only_active_ordered(session_factory):
    async with session_factory() as s:
        s.add_all(
            [
                Service(title="B", duration_min=30, price=1, is_active=True),
                Service(title="X", duration_min=30, price=1, is_active=False),
                Service(title="C", duration_min=30, price=1, is_active=True),
            ]
        )
        await s.commit()
    svc = BookingService(session_factory, ZoneInfo("Europe/Moscow"), 30, 2)
    assert [s.title for s in await svc.list_active_services()] == ["B", "C"]


async def test_concurrent_first_calls_create_one_user_without_error(session_factory):
    results = await asyncio.gather(
        *(get_or_create_user(session_factory, 555, f"Имя{i}") for i in range(5))
    )
    assert len({u.id for u in results}) == 1
    async with session_factory() as s:
        assert len((await s.scalars(select(User).where(User.telegram_id == 555))).all()) == 1
