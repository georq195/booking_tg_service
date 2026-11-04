from collections.abc import Iterable

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message


class IsAdmin(BaseFilter):
    def __init__(self, admin_ids: Iterable[int]) -> None:
        self._admin_ids = frozenset(admin_ids)

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        return user is not None and user.id in self._admin_ids


class IsPrivateChat(BaseFilter):
    """Message or callback that sits in a private chat. For callbacks the chat of
    the message carrying the button counts; a callback without that message
    (inline origin) is not private. Keeps admin output out of group chats."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        message = event if isinstance(event, Message) else event.message
        chat = getattr(message, "chat", None)
        return chat is not None and chat.type == "private"
