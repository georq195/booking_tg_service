import functools
import os
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, Message, Update
from openpyxl import load_workbook

from app.bot.handlers import build_router
from app.bot.handlers.admin import export as export_h
from app.bot.keyboards import admin as kb
from app.bot.middlewares import ServicesMiddleware
from app.services.exporters import BookingRow
from app.services.exporters.gsheets import GSheetsConfig
from app.utils import texts
from app.utils.dates import export_period

TZ = ZoneInfo("Europe/Moscow")
ROW = BookingRow(1, datetime(2026, 11, 3, 12, tzinfo=TZ), "Аня", None, "Стрижка", 100, "active")


# ---- period helper ----------------------------------------------------------


def test_export_period_today_week_month():
    today = date(2026, 11, 2)
    assert export_period("today", today) == (today, today)
    assert export_period("week", today) == (date(2026, 11, 2), date(2026, 11, 8))
    assert export_period("month", today) == (date(2026, 11, 1), date(2026, 11, 30))


def test_export_period_month_edges_and_leap_year():
    assert export_period("month", date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert export_period("month", date(2026, 12, 31)) == (date(2026, 12, 1), date(2026, 12, 31))
    assert export_period("week", date(2026, 12, 30)) == (date(2026, 12, 30), date(2027, 1, 5))


def test_export_period_unknown_raises():
    with pytest.raises(ValueError):
        export_period("year", date(2026, 11, 2))


# ---- keyboards --------------------------------------------------------------


def test_export_keyboards_and_callback_limit():
    period = kb.export_period_kb()
    labels = [b.text for r in period.inline_keyboard for b in r]
    assert labels[:3] == [
        texts.EXPORT_BTN_TODAY, texts.EXPORT_BTN_WEEK, texts.EXPORT_BTN_MONTH
    ]
    fmt = kb.export_format_kb("week")
    buttons = [b for r in fmt.inline_keyboard for b in r]
    assert [b.text for b in buttons[:2]] == [
        texts.EXPORT_BTN_EXCEL, texts.EXPORT_BTN_GSHEET
    ]
    data = [kb.AdmExportCb.unpack(b.callback_data) for b in buttons[:2]]
    assert [(d.period, d.fmt) for d in data] == [("week", "xlsx"), ("week", "gsheet")]
    assert len(kb.AdmExportCb(period="month", fmt="gsheet").pack().encode()) <= 64
    menu = [b.text for r in kb.admin_menu_kb().inline_keyboard for b in r]
    assert texts.ADMIN_BTN_EXPORT in menu


# ---- handlers ---------------------------------------------------------------


@pytest.fixture
def callback():
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.from_user = SimpleNamespace(id=1, full_name="Admin")
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.answer_document = AsyncMock()
    return cb


@pytest.fixture
def svc():
    s = MagicMock()
    s.tz = TZ
    s.list_rows = AsyncMock(return_value=[ROW])
    return s


async def test_open_shows_period_buttons(callback):
    await export_h.on_export_open(callback)
    assert callback.message.edit_text.await_args.args[0] == texts.EXPORT_CHOOSE_PERIOD


async def test_period_shows_format_buttons(callback):
    await export_h.on_period(callback, kb.AdmExportCb(period="week", fmt=""))
    callback.message.edit_text.assert_awaited_once()
    assert callback.message.edit_text.await_args.args[0] == texts.EXPORT_CHOOSE_FORMAT


async def test_xlsx_sends_document_and_leaves_no_files(callback, svc, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export_h, "_today", lambda tz: date(2026, 11, 2))
    before = set(os.listdir(tmp_path))
    await export_h.on_format(
        callback, kb.AdmExportCb(period="week", fmt="xlsx"), svc, gsheets=None
    )
    svc.list_rows.assert_awaited_once_with(date(2026, 11, 2), date(2026, 11, 8))
    doc = callback.message.answer_document.await_args.args[0]
    assert isinstance(doc, BufferedInputFile)
    assert doc.filename == "bookings_2026-11-02_2026-11-08.xlsx"
    out = tmp_path / "x.xlsx"
    out.write_bytes(doc.data)
    ws = load_workbook(out)["Записи"]
    assert ws.max_row == 2
    out.unlink()
    assert set(os.listdir(tmp_path)) == before


async def test_gsheet_not_configured_shows_instruction(callback, svc):
    await export_h.on_format(
        callback, kb.AdmExportCb(period="today", fmt="gsheet"), svc, gsheets=None
    )
    assert callback.message.edit_text.await_args.args[0] == texts.EXPORT_GSHEET_NOT_CONFIGURED
    svc.list_rows.assert_not_called()


async def test_gsheet_sends_link(callback, svc):
    calls = []

    def fake_export(rows, spreadsheet_id, credentials_path):
        calls.append((rows, spreadsheet_id, credentials_path))
        return "https://example.test/sheet"

    cfg = GSheetsConfig("creds.json", "SID")
    await export_h.on_format(
        callback,
        kb.AdmExportCb(period="today", fmt="gsheet"),
        svc,
        gsheets=cfg,
        gsheet_exporter=fake_export,
    )
    assert calls == [([ROW], "SID", "creds.json")]
    assert "https://example.test/sheet" in callback.message.edit_text.await_args.args[0]


async def test_gsheet_failure_shows_error_not_raise(callback, svc):
    def boom(rows, spreadsheet_id, credentials_path):
        raise RuntimeError("no access")

    await export_h.on_format(
        callback,
        kb.AdmExportCb(period="today", fmt="gsheet"),
        svc,
        gsheets=GSheetsConfig("c", "s"),
        gsheet_exporter=boom,
    )
    assert callback.message.edit_text.await_args.args[0] == texts.EXPORT_FAILED


async def test_exports_run_off_the_event_loop(callback, svc, monkeypatch):
    import asyncio
    import threading

    main = threading.get_ident()
    seen = []

    def fake_export(rows, spreadsheet_id, credentials_path):
        seen.append(threading.get_ident())
        return "u"

    await export_h.on_format(
        callback,
        kb.AdmExportCb(period="today", fmt="gsheet"),
        svc,
        gsheets=GSheetsConfig("c", "s"),
        gsheet_exporter=fake_export,
    )
    assert seen and seen[0] != main


# ---- guard: real dispatch ---------------------------------------------------


def _update(uid, data):
    bot = AsyncMock()
    bot.id = 1
    return bot, Update.model_validate(
        {
            "update_id": 1,
            "callback_query": {
                "id": "1",
                "from": {"id": uid, "is_bot": False, "first_name": "x"},
                "chat_instance": "1",
                "data": data,
                "message": {
                    "message_id": 1,
                    "date": 0,
                    "chat": {"id": 1, "type": "private"},
                },
            },
        },
        context={"bot": bot},
    )


@pytest.mark.parametrize(
    "data",
    [
        kb.AdmMenuCb(action="export").pack(),
        kb.AdmExportCb(period="week", fmt="").pack(),
        kb.AdmExportCb(period="week", fmt="xlsx").pack(),
        kb.AdmExportCb(period="week", fmt="gsheet").pack(),
    ],
)
async def test_guard_blocks_non_admin_export_in_real_dispatch(svc, data):
    dp = Dispatcher(storage=MemoryStorage())
    dp.callback_query.outer_middleware(ServicesMiddleware(svc, None))
    dp.include_router(build_router([1], gsheets=GSheetsConfig("c", "s")))
    for uid, expected in ((2, 0), (1, 1)):
        bot, update = _update(uid, data)
        await dp.feed_update(bot, update)
        # every export handler starts with callback.answer(), a bot API call
        reached = bot.await_count
        assert (reached > 0) == bool(expected), (uid, data)
