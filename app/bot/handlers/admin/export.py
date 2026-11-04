import asyncio
import functools
import logging
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.filters import IsAdmin, IsPrivateChat
from app.bot.handlers.admin.common import show
from app.bot.keyboards.admin import (
    AdmExportCb,
    AdmMenuCb,
    back_kb,
    export_format_kb,
    export_period_kb,
)
from app.services.booking_service import BookingService
from app.services.exporters import BookingRow
from app.services.exporters.excel import export_to_xlsx
from app.services.exporters.gsheets import GSheetsConfig, export_to_gsheet
from app.utils import texts
from app.utils.dates import export_period

log = logging.getLogger(__name__)


def _today(tz: ZoneInfo):
    return datetime.now(tz).date()


def _xlsx_bytes(rows: list[BookingRow]) -> bytes:
    """Blocking. The workbook lives in a temp dir that is removed right away."""
    with tempfile.TemporaryDirectory() as tmp:
        return export_to_xlsx(rows, Path(tmp) / "bookings.xlsx").read_bytes()


async def on_export_open(callback: CallbackQuery) -> None:
    await callback.answer()
    await show(callback, texts.EXPORT_CHOOSE_PERIOD, export_period_kb())


async def on_period(callback: CallbackQuery, callback_data: AdmExportCb) -> None:
    await callback.answer()
    await show(
        callback, texts.EXPORT_CHOOSE_FORMAT, export_format_kb(callback_data.period)
    )


async def on_format(
    callback: CallbackQuery,
    callback_data: AdmExportCb,
    booking_service: BookingService,
    gsheets: GSheetsConfig | None = None,
    gsheet_exporter: Callable[..., str] = export_to_gsheet,
) -> None:
    """Export bookings of the chosen period (see export_period). Excel goes to
    the chat as a file, Google as a link. openpyxl and gspread block, so they
    run in a worker thread."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if callback_data.fmt == "gsheet" and gsheets is None:
        await show(callback, texts.EXPORT_GSHEET_NOT_CONFIGURED, back_kb())
        return
    start, end = export_period(callback_data.period, _today(booking_service.tz))
    label = {"start": f"{start:%d.%m.%Y}", "end": f"{end:%d.%m.%Y}"}
    try:
        rows = await booking_service.list_rows(start, end)
        if callback_data.fmt == "gsheet":
            url = await asyncio.to_thread(
                gsheet_exporter, rows, gsheets.spreadsheet_id, gsheets.credentials_path
            )
            text = texts.EXPORT_GSHEET_DONE.format(count=len(rows), url=url, **label)
            await show(callback, text, back_kb())
            return
        data = await asyncio.to_thread(_xlsx_bytes, rows)
        document = BufferedInputFile(
            data, filename=f"bookings_{start.isoformat()}_{end.isoformat()}.xlsx"
        )
        await callback.message.answer_document(
            document, caption=texts.EXPORT_XLSX_CAPTION.format(count=len(rows), **label)
        )
    except Exception:
        log.exception("export failed")
        await show(callback, texts.EXPORT_FAILED, back_kb())
        return
    await show(callback, texts.EXPORT_DONE, back_kb())


def build_router(
    is_admin: IsAdmin,
    gsheets: GSheetsConfig | None = None,
    gsheet_exporter: Callable[..., str] = export_to_gsheet,
) -> Router:
    router = Router(name="admin_export")
    router.message.filter(is_admin, IsPrivateChat())
    router.callback_query.filter(is_admin, IsPrivateChat())
    cb = router.callback_query
    cb.register(on_export_open, AdmMenuCb.filter(F.action == "export"))
    cb.register(on_period, AdmExportCb.filter(F.fmt == ""))
    cb.register(
        functools.partial(on_format, gsheets=gsheets, gsheet_exporter=gsheet_exporter),
        AdmExportCb.filter(F.fmt != ""),
    )
    return router
