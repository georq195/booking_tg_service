from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters import IsAdmin, IsPrivateChat
from app.bot.handlers.admin.common import show
from app.bot.keyboards.admin import AdmMenuCb, admin_menu_kb
from app.utils import texts


async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.ADMIN_MENU, reply_markup=admin_menu_kb())


async def on_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await show(callback, texts.ADMIN_MENU, admin_menu_kb())


def build_router(is_admin: IsAdmin) -> Router:
    router = Router(name="admin_menu")
    router.message.filter(is_admin, IsPrivateChat())
    router.callback_query.filter(is_admin, IsPrivateChat())
    router.message.register(cmd_admin, Command("admin"))
    router.callback_query.register(on_menu, AdmMenuCb.filter(F.action == "menu"))
    return router

