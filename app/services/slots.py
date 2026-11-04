from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class WorkDay:
    start: time
    end: time
    break_start: time | None = None
    break_end: time | None = None


def _local(day: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, t, tzinfo=tz).astimezone(timezone.utc)


def compute_free_slots(
    day: date,
    work: WorkDay | None,
    busy: list[tuple[datetime, datetime]],
    duration_min: int,
    step_min: int,
    tz: ZoneInfo,
    now: datetime,
) -> list[datetime]:
    """Return UTC-aware slot starts for `day`, ascending. Intervals are half-open."""
    if work is None:
        return []
    duration = timedelta(minutes=duration_min)
    step = timedelta(minutes=step_min)
    day_end = _local(day, work.end, tz)
    brk = None
    if work.break_start is not None and work.break_end is not None:
        brk = (_local(day, work.break_start, tz), _local(day, work.break_end, tz))
    blocked = list(busy) + ([brk] if brk else [])

    result = []
    start = _local(day, work.start, tz)
    while start + duration <= day_end:
        end = start + duration
        if start >= now and not any(start < b_end and b_start < end for b_start, b_end in blocked):
            result.append(start)
        start += step
    return result
