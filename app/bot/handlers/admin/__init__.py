from collections.abc import Iterable

from aiogram import Router

from app.bot.filters import IsAdmin
from app.bot.handlers.admin import bookings, export, menu, schedule, services
from app.services.exporters.gsheets import GSheetsConfig


def build_router(
    admin_ids: Iterable[int], gsheets: GSheetsConfig | None = None
) -> Router:
    """Fresh admin routers on every call. Each leaf router carries its own IsAdmin
    filter: a parent's filter does not stop events reaching its sub-routers."""
    is_admin = IsAdmin(admin_ids)
    root = Router(name="admin")
    root.include_routers(
        menu.build_router(is_admin),
        schedule.build_router(is_admin),
        bookings.build_router(is_admin),
        services.build_router(is_admin),
        export.build_router(is_admin, gsheets),
    )
    return root
