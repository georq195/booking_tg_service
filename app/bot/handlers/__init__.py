from collections.abc import Sequence

from aiogram import Router

from app.bot.handlers import admin, booking, fallback, my_bookings, start
from app.services.exporters.gsheets import GSheetsConfig


def build_router(
    admin_ids: Sequence[int] = (), gsheets: GSheetsConfig | None = None
) -> Router:
    root = Router(name="root")
    # The admin router goes first and the admin panel is off without ids.
    # my_bookings must precede booking: booking registers an unfiltered
    # DateCb/SlotCb fallback that would swallow the reschedule callbacks.
    if admin_ids:
        root.include_router(admin.build_router(admin_ids, gsheets))
    root.include_routers(
        start.build_router(), my_bookings.build_router(), booking.build_router()
    )
    # Last: answers only what nothing above handled (and has no FSM state).
    root.include_router(fallback.build_router())
    return root
