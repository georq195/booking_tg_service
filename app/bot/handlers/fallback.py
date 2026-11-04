from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from app.utils import texts


async def on_unknown_message(message: Message) -> None:
    await message.answer(texts.FALLBACK_HINT)


def build_router() -> Router:
    """Catch-all for private messages that no other handler took. StateFilter(None)
    keeps it away from messages that belong to a running FSM flow."""
    router = Router(name="fallback")
    router.message.register(
        on_unknown_message, StateFilter(None), F.chat.type == "private"
    )
    return router
