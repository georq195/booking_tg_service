import asyncio
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.handlers import build_router
from app.bot.middlewares import ServicesMiddleware
from app.config import get_settings
from app.db.base import init_db, make_engine, make_session_factory
from app.services.booking_service import BookingService
from app.services.exporters.gsheets import GSheetsConfig
from app.services.reminders import ReminderService
from app.utils import texts

log = logging.getLogger(__name__)


def build_dispatcher(
    booking_service: BookingService,
    session_factory,
    admin_ids=(),
    gsheets: GSheetsConfig | None = None,
) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    middleware = ServicesMiddleware(booking_service, session_factory)
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)
    dp.include_router(build_router(admin_ids, gsheets))
    return dp


def bot_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description=texts.BOT_CMD_START_DESC),
        BotCommand(command="my", description=texts.BOT_CMD_MY_DESC),
    ]


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(bot_commands())


def warn_if_no_admins(admin_ids) -> None:
    if not admin_ids:
        log.warning("ADMIN_IDS is empty: admin panel disabled")


_PERMANENT_BAD_REQUEST = ("chat not found", "user is deactivated")


def is_permanent_send_error(exc: Exception) -> bool:
    """Bot blocked / chat gone: retrying will never help."""
    if isinstance(exc, TelegramForbiddenError):
        return True
    if isinstance(exc, TelegramBadRequest):
        return any(m in str(exc).lower() for m in _PERMANENT_BAD_REQUEST)
    return False


def build_scheduler(reminders: ReminderService) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        reminders.run_once,
        "interval",
        minutes=1,
        id="send_due_reminders",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    return scheduler


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    warn_if_no_admins(settings.admin_ids)
    engine = make_engine(settings.database_url)
    await init_db(engine)
    session_factory = make_session_factory(engine)
    booking_service = BookingService(
        session_factory,
        ZoneInfo(settings.timezone),
        settings.slot_step_min,
        settings.cancel_deadline_hours,
    )
    gsheets = None
    if settings.gsheets_credentials_path and settings.gsheets_spreadsheet_id:
        gsheets = GSheetsConfig(
            settings.gsheets_credentials_path, settings.gsheets_spreadsheet_id
        )
    dp = build_dispatcher(booking_service, session_factory, settings.admin_ids, gsheets)
    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await set_bot_commands(bot)
    reminders = ReminderService(
        session_factory, bot, ZoneInfo(settings.timezone), is_permanent_send_error
    )
    scheduler = build_scheduler(reminders)
    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
