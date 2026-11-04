import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.services.booking_service import BookingDetails, BookingService
from app.utils import texts
from app.utils.dates import day_label

log = logging.getLogger(__name__)


async def show(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def notify_cancelled(
    bot: Bot, items: list[BookingDetails], booking_service: BookingService
) -> list[BookingDetails]:
    """Tell each client their booking was cancelled; a blocked bot is not fatal.
    Returns the items whose client could not be reached."""
    failed: list[BookingDetails] = []
    for item in items:
        local = item.booking.start_at.astimezone(booking_service.tz)
        text = texts.CLIENT_BOOKING_CANCELLED.format(
            date=day_label(local.date()),
            time=f"{local:%H:%M}",
            service=escape(item.service.title),
        )
        try:
            await bot.send_message(item.user.telegram_id, text)
        except TelegramAPIError:
            log.warning("could not notify user %s", item.user.telegram_id, exc_info=True)
            failed.append(item)
    return failed


def not_notified_names(failed: list[BookingDetails]) -> str:
    """HTML-escaped client names, each once, in order."""
    return ", ".join(dict.fromkeys(escape(item.user.name) for item in failed))
