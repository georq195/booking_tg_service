from pathlib import Path

from openpyxl import Workbook

from app.services.exporters import COLUMNS, SHEET_TITLE, BookingRow, row_values


def export_to_xlsx(rows: list[BookingRow], path: Path) -> Path:
    """One sheet «Записи»: header row, then one row per booking. Text cells are
    forced to the string type, so a name like "=1+1" is shown, not evaluated."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_TITLE
    ws.append(COLUMNS)
    for row in rows:
        ws.append(row_values(row))
    for line in ws.iter_rows(min_row=2):
        for cell in line:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    for idx, column in enumerate(ws.columns, start=1):
        longest = max(len(str(c.value)) for c in column if c.value is not None)
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = longest + 2
    wb.save(path)
    return path
