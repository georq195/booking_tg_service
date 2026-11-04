import re
from datetime import time

from app.services.slots import WorkDay

_RANGE = r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})"
_HOURS_RE = re.compile(rf"^\s*{_RANGE}(?:\s+{_RANGE})?\s*$", re.ASCII)
_INT_RE = re.compile(r"^\d+$", re.ASCII)


def _t(hours: str, minutes: str) -> time:
    return time(int(hours), int(minutes))  # ValueError when out of range


def parse_work_hours(text: str) -> WorkDay:
    """'10:00-18:00' or '10:00-18:00 14:00-15:00'. Raises ValueError on bad format.

    Semantic checks (end after start, break inside) belong to the service."""
    match = _HOURS_RE.match(text)
    if match is None:
        raise ValueError("bad work hours format")
    g = match.groups()
    break_start = break_end = None
    if g[4] is not None:
        break_start, break_end = _t(g[4], g[5]), _t(g[6], g[7])
    return WorkDay(_t(g[0], g[1]), _t(g[2], g[3]), break_start, break_end)


def parse_positive_int(text: str, *, minimum: int, maximum: int) -> int:
    """Decimal digits only (no signs, no non-ASCII digits); ValueError otherwise."""
    stripped = text.strip()
    if not _INT_RE.match(stripped):
        raise ValueError("not an integer")
    value = int(stripped)
    if not minimum <= value <= maximum:
        raise ValueError("out of range")
    return value
