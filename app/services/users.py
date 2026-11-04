from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User


async def get_or_create_user(
    session_factory: async_sessionmaker[AsyncSession], telegram_id: int, name: str
) -> User:
    async with session_factory() as s:
        user = await s.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(telegram_id=telegram_id, name=name)
            s.add(user)
        elif user.name != name:
            user.name = name
        try:
            await s.commit()
        except IntegrityError:
            # A concurrent first call inserted the same telegram_id: use that row.
            await s.rollback()
            user = await s.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                raise
            if user.name != name:
                user.name = name
            await s.commit()
        return user
