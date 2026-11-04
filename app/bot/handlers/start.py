from html import escape

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.inline import services_kb
from app.bot.states import BookingFlow
from app.services.booking_service import BookingService
from app.services.users import get_or_create_user
from app.utils import texts

async def cmd_start(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await state.clear()
    tg_user = message.from_user
    if tg_user is None:
        return
    await get_or_create_user(session_factory, tg_user.id, tg_user.full_name)
    await message.answer(texts.GREETING.format(name=escape(tg_user.full_name)))
    services = await booking_service.list_active_services()
    if not services:
        await message.answer(texts.NO_SERVICES)
        return
    await state.set_state(BookingFlow.choosing_service)
    await message.answer(texts.CHOOSE_SERVICE, reply_markup=services_kb(services))


def build_router() -> Router:
    router = Router(name="start")
    router.message.register(cmd_start, CommandStart())
    return router
