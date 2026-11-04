from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import gspread
import pytest
from openpyxl import load_workbook

from app.db.models import Booking, BookingStatus, Service, User
from app.services.booking_service import BookingService
from app.services.exporters import COLUMNS, BookingRow
from app.services.exporters.excel import export_to_xlsx
from app.services.exporters.gsheets import export_to_gsheet

TZ = ZoneInfo("Europe/Moscow")


def make_rows():
    return [
        BookingRow(
            1, datetime(2026, 11, 3, 12, 0, tzinfo=TZ), "Аня", "+79990001122",
            "Стрижка", 1500, "active",
        ),
        BookingRow(
            2, datetime(2026, 11, 3, 14, 30, tzinfo=TZ), "Борис", None,
            "Окрашивание", 3000, "cancelled",
        ),
    ]


def test_columns_are_fixed():
    assert COLUMNS == [
        "ID", "Дата и время", "Клиент", "Телефон", "Услуга", "Цена", "Статус"
    ]


def test_xlsx_has_header_and_rows(tmp_path):
    rows = make_rows()
    out = export_to_xlsx(rows, tmp_path / "out.xlsx")
    assert out == tmp_path / "out.xlsx"
    wb = load_workbook(out)
    assert wb.sheetnames == ["Записи"]
    ws = wb["Записи"]
    assert [c.value for c in ws[1]] == COLUMNS
    assert ws.max_row == len(rows) + 1
    assert ws["A2"].value == 1
    assert ws["B2"].value == "03.11.2026 12:00"
    assert ws["D3"].value in (None, "")
    assert ws["F2"].value == 1500
    assert ws["G3"].value == "отменена"


def test_xlsx_column_width_fits_content(tmp_path):
    rows = make_rows()
    ws = load_workbook(export_to_xlsx(rows, tmp_path / "w.xlsx"))["Записи"]
    assert ws.column_dimensions["E"].width >= len("Окрашивание")
    assert ws.column_dimensions["B"].width >= len("03.11.2026 12:00")


def test_xlsx_empty_rows_writes_header_only(tmp_path):
    ws = load_workbook(export_to_xlsx([], tmp_path / "e.xlsx"))["Записи"]
    assert ws.max_row == 1
    assert [c.value for c in ws[1]] == COLUMNS


@pytest.mark.parametrize("evil", ["=1+1", "+7 999", "-5", "@SUM(A1)"])
def test_xlsx_formula_like_text_stays_text(tmp_path, evil):
    rows = [
        BookingRow(1, datetime(2026, 11, 3, 12, tzinfo=TZ), evil, evil, evil, 1, "active")
    ]
    ws = load_workbook(export_to_xlsx(rows, tmp_path / "f.xlsx"))["Записи"]
    for col in "CDE":
        cell = ws[f"{col}2"]
        assert cell.data_type == "s"
        assert cell.value == evil


class FakeWorksheet:
    """Models the gspread bits the exporter uses, including the grid limit:
    update() beyond the grid fails like the real API (APIError), resize() changes
    the grid, batch_clear() empties ranges. `cells` maps (row, col) -> value."""

    def __init__(self, old_rows=0, row_count=100, col_count=7, fail_update=False):
        self.calls = []
        self.row_count = row_count
        self.col_count = col_count
        self.fail_update = fail_update
        self.cells = {
            (r, c): f"old{r}-{c}"
            for r in range(1, old_rows + 1)
            for c in range(1, col_count + 1)
        }

    def clear(self):
        self.calls.append(("clear",))
        self.cells.clear()

    def resize(self, rows=None, cols=None):
        self.calls.append(("resize", rows, cols))
        if rows is not None:
            self.row_count = rows
            self.cells = {k: v for k, v in self.cells.items() if k[0] <= rows}
        if cols is not None:
            self.col_count = cols
            self.cells = {k: v for k, v in self.cells.items() if k[1] <= cols}

    def update(self, values, range_name=None, **kwargs):
        self.calls.append(("update", values, range_name, kwargs))
        if self.fail_update:
            raise RuntimeError("quota exceeded")
        if len(values) > self.row_count or max(len(r) for r in values) > self.col_count:
            raise RuntimeError("Range exceeds grid limits")
        for r, row in enumerate(values, start=1):
            for c, value in enumerate(row, start=1):
                self.cells[(r, c)] = value

    def batch_clear(self, ranges):
        self.calls.append(("batch_clear", list(ranges)))
        for rng in ranges:
            first, last = rng.split(":")
            r1, c1 = gspread.utils.a1_to_rowcol(first)
            r2, c2 = gspread.utils.a1_to_rowcol(last)
            for key in [k for k in self.cells if r1 <= k[0] <= r2 and c1 <= k[1] <= c2]:
                del self.cells[key]

    def used_rows(self):
        return sorted({r for r, _ in self.cells})

    def row(self, r):
        return [self.cells.get((r, c)) for c in range(1, self.col_count + 1)]


class FakeSpreadsheet:
    url = "https://docs.google.com/spreadsheets/d/SID"

    def __init__(self, ws, missing=False):
        self.ws = ws
        self.missing = missing
        self.added = []

    def worksheet(self, title):
        if self.missing and not self.added:
            raise gspread.WorksheetNotFound(title)
        assert title == "Записи"
        return self.ws

    def add_worksheet(self, title, rows, cols):
        self.added.append((title, rows, cols))
        self.ws.row_count, self.ws.col_count = rows, cols
        return self.ws


class FakeClient:
    def __init__(self, sheet):
        self.sheet = sheet
        self.opened = []

    def open_by_key(self, key):
        self.opened.append(key)
        return self.sheet


def run_gsheet(rows, missing=False, ws=None):
    ws = ws or FakeWorksheet()
    sheet = FakeSpreadsheet(ws, missing)
    client = FakeClient(sheet)
    seen = []

    def factory(path):
        seen.append(path)
        return client

    url = export_to_gsheet(rows, "SID", "creds.json", client_factory=factory)
    return url, ws, sheet, client, seen


def test_gsheet_writes_header_and_rows_via_fake_client():
    url, ws, _, client, seen = run_gsheet(make_rows())
    assert url == "https://docs.google.com/spreadsheets/d/SID"
    assert seen == ["creds.json"]
    assert client.opened == ["SID"]
    kind, values, _, kwargs = next(c for c in ws.calls if c[0] == "update")
    assert kind == "update"
    assert kwargs["value_input_option"] == "RAW"
    assert values[0] == COLUMNS
    assert values[1] == [
        1, "03.11.2026 12:00", "Аня", "+79990001122", "Стрижка", 1500, "активна"
    ]
    assert values[2][3] == ""
    assert len(values) == 3


def test_gsheet_empty_rows_writes_header_only():
    _, ws, *_ = run_gsheet([])
    assert next(c for c in ws.calls if c[0] == "update")[1] == [COLUMNS]


def test_gsheet_creates_missing_worksheet():
    _, ws, sheet, *_ = run_gsheet(make_rows(), missing=True)
    assert [a[0] for a in sheet.added] == ["Записи"]
    assert ws.used_rows() == [1, 2, 3]


def test_gsheet_formula_like_text_is_sent_raw_as_str():
    rows = [
        BookingRow(1, datetime(2026, 11, 3, 12, tzinfo=TZ), "=HYPERLINK(1)", "+7", "@x", 1, "active")
    ]
    _, ws, *_ = run_gsheet(rows)
    _, values, _, kwargs = next(c for c in ws.calls if c[0] == "update")
    assert kwargs["value_input_option"] == "RAW"
    assert values[1][2] == "=HYPERLINK(1)" and isinstance(values[1][2], str)
    assert isinstance(values[1][3], str)


def many_rows(n):
    return [
        BookingRow(i, datetime(2026, 11, 3, 12, tzinfo=TZ), f"N{i}", None, "S", 1, "active")
        for i in range(1, n + 1)
    ]


def test_gsheet_bigger_export_after_smaller_grows_the_grid_first():
    ws = FakeWorksheet(old_rows=2, row_count=3)
    run_gsheet(many_rows(10), ws=ws)
    assert ws.row_count >= 11
    assert ws.used_rows() == list(range(1, 12))
    assert ws.row(1) == COLUMNS
    assert ws.row(11)[2] == "N10"
    assert [c[0] for c in ws.calls][:2] == ["resize", "update"]


def test_gsheet_smaller_export_after_bigger_leaves_no_stale_rows():
    ws = FakeWorksheet(old_rows=50, row_count=100)
    run_gsheet(many_rows(2), ws=ws)
    assert ws.used_rows() == [1, 2, 3]
    assert all(not str(v).startswith("old") for v in ws.cells.values())


def test_gsheet_header_only_export_clears_all_old_rows():
    ws = FakeWorksheet(old_rows=5, row_count=100)
    run_gsheet([], ws=ws)
    assert ws.used_rows() == [1]


def test_gsheet_never_clears_the_whole_sheet_before_writing():
    ws = FakeWorksheet(old_rows=5)
    run_gsheet(many_rows(3), ws=ws)
    assert ("clear",) not in ws.calls
    names = [c[0] for c in ws.calls]
    assert names.index("update") < names.index("batch_clear")


def test_gsheet_failed_update_keeps_old_data_and_clears_nothing():
    ws = FakeWorksheet(old_rows=5, row_count=100, fail_update=True)
    with pytest.raises(RuntimeError):
        run_gsheet(many_rows(2), ws=ws)
    assert ws.used_rows() == [1, 2, 3, 4, 5]
    assert all(c[0] not in ("clear", "batch_clear") for c in ws.calls)


def test_gsheet_exact_fit_needs_no_cleanup():
    ws = FakeWorksheet(old_rows=3, row_count=3)
    run_gsheet(many_rows(2), ws=ws)
    assert ws.used_rows() == [1, 2, 3]
    assert all(c[0] != "batch_clear" for c in ws.calls)


# ---- BookingService.list_rows ---------------------------------------------


def utc(day, hour):
    return datetime.combine(day, time(hour), tzinfo=TZ).astimezone(UTC)


async def test_list_rows_includes_cancelled(session_factory):
    day = date(2026, 11, 3)
    async with session_factory() as s:
        u1 = User(telegram_id=1, name="Аня", phone="+7999")
        u2 = User(telegram_id=2, name="Борис")
        sv = Service(title="Стрижка", duration_min=60, price=1500, is_active=False)
        s.add_all([u1, u2, sv])
        await s.flush()

        def bk(user, start, status):
            return Booking(
                user_id=user.id, service_id=sv.id, start_at=start,
                end_at=start + timedelta(hours=1), status=status,
            )

        s.add_all(
            [
                bk(u2, utc(day, 15), BookingStatus.cancelled),
                bk(u1, utc(day, 10), BookingStatus.active),
                # 00:30 local of the next day is outside, 00:30 local of day is inside
                bk(u1, utc(day + timedelta(days=1), 0) + timedelta(minutes=30), BookingStatus.active),
                bk(u1, utc(day, 0) + timedelta(minutes=30), BookingStatus.done),
                bk(u1, utc(day - timedelta(days=1), 23), BookingStatus.active),
            ]
        )
        await s.commit()
    svc = BookingService(session_factory, TZ, step_min=30, cancel_deadline_hours=2)
    rows = await svc.list_rows(day, day)
    assert [r.status for r in rows] == ["done", "active", "cancelled"]
    assert [r.start_local.hour for r in rows] == [0, 10, 15]
    first = rows[1]
    assert first.start_local.tzinfo is not None
    assert first.start_local.utcoffset() == timedelta(hours=3)
    assert (first.client_name, first.phone) == ("Аня", "+7999")
    assert (first.service_title, first.price) == ("Стрижка", 1500)
    assert rows[2].phone is None
    wide = await svc.list_rows(day - timedelta(days=1), day + timedelta(days=1))
    assert len(wide) == 5
    assert await svc.list_rows(day + timedelta(days=5), day + timedelta(days=6)) == []
