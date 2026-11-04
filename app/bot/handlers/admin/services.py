from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters import IsAdmin, IsPrivateChat
from app.bot.handlers.admin.common import show
from app.bot.keyboards.admin import (
    AdmMenuCb,
    AdmServiceCb,
    service_card_kb,
    services_admin_kb,
)
from app.bot.states import AdminFlow
from app.services.booking_service import MAX_DURATION_MIN, MAX_PRICE, BookingService
from app.services.errors import ServiceNotFound
from app.utils import texts
from app.utils.parsing import parse_positive_int

_PROMPTS = {
    "title": texts.ADMIN_ASK_TITLE,
    "duration": texts.ADMIN_ASK_DURATION,
    "price": texts.ADMIN_ASK_PRICE,
}


def _valid_title(text: str) -> str | None:
    title = text.strip()
    return title if 0 < len(title) <= 255 else None


async def on_services_open(
    callback: CallbackQuery, state: FSMContext, booking_service: BookingService
) -> None:
    await callback.answer()
    await state.clear()
    services = await booking_service.list_all_services()
    title = texts.ADMIN_SERVICES_TITLE if services else texts.ADMIN_SERVICES_EMPTY
    await show(callback, title, services_admin_kb(services))


async def _show_card(
    callback: CallbackQuery, booking_service: BookingService, service_id: int
) -> None:
    try:
        service = await booking_service.get_service(service_id)
    except ServiceNotFound:
        await show(callback, texts.ADMIN_SERVICE_NOT_FOUND)
        return
    await show(
        callback,
        texts.ADMIN_SERVICE_CARD.format(
            title=escape(service.title),
            duration=service.duration_min,
            price=service.price,
            hidden="" if service.is_active else texts.ADMIN_SERVICE_HIDDEN_MARK,
        ),
        service_card_kb(service),
    )


async def on_service_action(
    callback: CallbackQuery,
    callback_data: AdmServiceCb,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    await callback.answer()
    action, service_id = callback_data.action, callback_data.service_id
    if action == "open":
        await state.clear()
        await _show_card(callback, booking_service, service_id)
    elif action == "add":
        await state.clear()
        await state.set_state(AdminFlow.add_title)
        await show(callback, texts.ADMIN_ASK_TITLE)
    elif action == "hide":
        await state.clear()
        try:
            await booking_service.hide_service(service_id)
        except ServiceNotFound:
            await show(callback, texts.ADMIN_SERVICE_NOT_FOUND)
            return
        await _show_card(callback, booking_service, service_id)
    elif action in _PROMPTS:
        await state.clear()
        await state.set_state(AdminFlow.edit_value)
        await state.update_data(service_id=service_id, field=action)
        await show(callback, _PROMPTS[action])


async def on_add_title(message: Message, state: FSMContext) -> None:
    title = _valid_title(message.text or "")
    if title is None:
        await message.answer(texts.ADMIN_BAD_TITLE)
        return
    await state.update_data(title=title)
    await state.set_state(AdminFlow.add_duration)
    await message.answer(texts.ADMIN_ASK_DURATION)


async def on_add_duration(message: Message, state: FSMContext) -> None:
    try:
        duration = parse_positive_int(
            message.text or "", minimum=1, maximum=MAX_DURATION_MIN
        )
    except ValueError:
        await message.answer(texts.ADMIN_BAD_NUMBER)
        return
    await state.update_data(duration=duration)
    await state.set_state(AdminFlow.add_price)
    await message.answer(texts.ADMIN_ASK_PRICE)


async def on_add_price(
    message: Message, state: FSMContext, booking_service: BookingService
) -> None:
    try:
        price = parse_positive_int(message.text or "", minimum=0, maximum=MAX_PRICE)
    except ValueError:
        await message.answer(texts.ADMIN_BAD_PRICE)
        return
    data = await state.get_data()
    if "title" not in data or "duration" not in data:
        await state.clear()
        await message.answer(texts.ADMIN_ERROR)
        return
    await booking_service.add_service(data["title"], data["duration"], price)
    await state.clear()
    services = await booking_service.list_all_services()
    await message.answer(
        texts.ADMIN_SERVICE_ADDED, reply_markup=services_admin_kb(services)
    )


async def on_edit_value(
    message: Message, state: FSMContext, booking_service: BookingService
) -> None:
    data = await state.get_data()
    field, service_id = data.get("field"), data.get("service_id")
    if field not in _PROMPTS or service_id is None:
        await state.clear()
        await message.answer(texts.ADMIN_ERROR)
        return
    text = message.text or ""
    if field == "title":
        title = _valid_title(text)
        if title is None:
            await message.answer(texts.ADMIN_BAD_TITLE)
            return
        changes: dict = {"title": title}
    else:
        try:
            if field == "duration":
                changes = {
                    "duration_min": parse_positive_int(
                        text, minimum=1, maximum=MAX_DURATION_MIN
                    )
                }
            else:
                changes = {
                    "price": parse_positive_int(text, minimum=0, maximum=MAX_PRICE)
                }
        except ValueError:
            await message.answer(
                texts.ADMIN_BAD_NUMBER if field == "duration" else texts.ADMIN_BAD_PRICE
            )
            return
    try:
        await booking_service.update_service(service_id, **changes)
    except ServiceNotFound:
        await state.clear()
        await message.answer(texts.ADMIN_SERVICE_NOT_FOUND)
        return
    await state.clear()
    await message.answer(texts.ADMIN_SERVICE_UPDATED)


def build_router(is_admin: IsAdmin) -> Router:
    router = Router(name="admin_services")
    router.message.filter(is_admin, IsPrivateChat())
    router.callback_query.filter(is_admin, IsPrivateChat())
    router.callback_query.register(
        on_services_open, AdmMenuCb.filter(F.action == "services")
    )
    router.callback_query.register(on_service_action, AdmServiceCb.filter())
    text_input = (F.text, ~F.text.startswith("/"))
    router.message.register(on_add_title, AdminFlow.add_title, *text_input)
    router.message.register(on_add_duration, AdminFlow.add_duration, *text_input)
    router.message.register(on_add_price, AdminFlow.add_price, *text_input)
    router.message.register(on_edit_value, AdminFlow.edit_value, *text_input)
    return router
