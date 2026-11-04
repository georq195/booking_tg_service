from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.slots import WorkDay, compute_free_slots

TZ = ZoneInfo("Europe/Moscow")
DAY = date(2026, 11, 2)
WORK = WorkDay(start=time(10, 0), end=time(18, 0), break_start=None, break_end=None)
EARLY_NOW = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)


def msk(h, m=0):
    return datetime(2026, 11, 2, h, m, tzinfo=TZ).astimezone(timezone.utc)


def slots(work=WORK, busy=(), duration=60, step=30, now=EARLY_NOW):
    return compute_free_slots(DAY, work, list(busy), duration, step, TZ, now)


def test_empty_day_returns_all_slots():
    result = slots()
    assert len(result) == 15
    assert result[0] == msk(10)
    assert result[-1] == msk(17)
    assert all(s.tzinfo is not None and s.utcoffset() == timedelta(0) for s in result)


def test_busy_interval_removes_overlapping_slots():
    result = slots(busy=[(msk(12), msk(13))])
    for removed in (msk(11, 30), msk(12), msk(12, 30)):
        assert removed not in result
    assert msk(11) in result
    assert msk(13) in result


def test_break_is_excluded():
    work = WorkDay(time(10), time(18), time(14), time(15))
    result = slots(work=work)
    for removed in (msk(13, 30), msk(14), msk(14, 30)):
        assert removed not in result
    assert msk(13) in result
    assert msk(15) in result


def test_past_slots_are_excluded():
    result = slots(now=msk(12, 10))
    assert result[0] == msk(12, 30)


def test_day_off_returns_empty():
    assert slots(work=None) == []


def test_service_longer_than_gap_not_offered():
    busy = [(msk(10), msk(12)), (msk(12, 30), msk(18))]
    assert slots(busy=busy) == []


def test_back_to_back_bookings_do_not_conflict():
    result = slots(busy=[(msk(12), msk(13))])
    assert msk(11) in result  # ends exactly at 12:00
    assert msk(13) in result  # starts exactly at 13:00


def test_slot_exactly_at_now_is_allowed():
    assert msk(12) in slots(now=msk(12))
