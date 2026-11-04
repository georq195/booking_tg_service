from dataclasses import dataclass
from datetime import datetime

from app.utils import texts

COLUMNS: list[str] = [
    "ID",
    "Дата и время",
    "Клиент",
    "Телефон",
    "Услуга",
    "Цена",
    "Статус",
]
SHEET_TITLE = "Записи"
DATETIME_FORMAT = "%d.%m.%Y %H:%M"


@dataclass(frozen=True)
class BookingRow:
    booking_id: int
    start_local: datetime  # tz-aware, in the configured timezone
    client_name: str
    phone: str | None
    service_title: str
    price: int
    status: str  # BookingStatus value


def row_values(row: BookingRow) -> list[str | int]:
    """Cell values for one row. Text stays str: writers must never let it be
    interpreted as a formula (see excel.py and gsheets.py)."""
    return [
        row.booking_id,
        f"{row.start_local:{DATETIME_FORMAT}}",
        row.client_name,
        row.phone or "",
        row.service_title,
        row.price,
        texts.EXPORT_STATUS_LABELS.get(row.status, row.status),
    ]
