from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.booking_service import BookingService


class ServicesMiddleware(BaseMiddleware):
    def __init__(
        self,
        booking_service: BookingService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._booking_service = booking_service
        self._session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["booking_service"] = self._booking_service
        data["session_factory"] = self._session_factory
        return await handler(event, data)
