from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import gspread
from gspread.utils import rowcol_to_a1

from app.services.exporters import COLUMNS, SHEET_TITLE, BookingRow, row_values


@dataclass(frozen=True)
class GSheetsConfig:
    credentials_path: str
    spreadsheet_id: str


def export_to_gsheet(
    rows: list[BookingRow],
    spreadsheet_id: str,
    credentials_path: str,
    client_factory: Callable[[str], Any] = gspread.service_account,
) -> str:
    """Rewrite the «Записи» worksheet (created if missing) and return the
    spreadsheet URL. Writes before clearing: grow grid, update, blank leftovers. Blocking: call it via asyncio.to_thread.

    Values go in with value_input_option="RAW", so Sheets stores text as typed and
    never evaluates a client name like "=1+1" as a formula."""
    client = client_factory(credentials_path)
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(SHEET_TITLE)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=SHEET_TITLE, rows=max(len(rows) + 1, 100), cols=len(COLUMNS)
        )
    values = [COLUMNS] + [row_values(r) for r in rows]
    # The sheet is never emptied up front: grow the grid if the data needs it,
    # write the new data over the old, then blank only what is left below. A
    # failure before the write leaves the previous export untouched.
    grid_rows = max(worksheet.row_count, len(values))
    grid_cols = max(worksheet.col_count, len(COLUMNS))
    if (grid_rows, grid_cols) != (worksheet.row_count, worksheet.col_count):
        worksheet.resize(rows=grid_rows, cols=grid_cols)
    worksheet.update(values, "A1", value_input_option="RAW")
    if grid_rows > len(values):
        first = rowcol_to_a1(len(values) + 1, 1)
        last = rowcol_to_a1(grid_rows, grid_cols)
        worksheet.batch_clear([f"{first}:{last}"])
    return spreadsheet.url
