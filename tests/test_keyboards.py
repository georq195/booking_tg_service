from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.bot.keyboards.inline import SlotCb, dates_kb, slots_kb

TZ = ZoneInfo("Europe/Moscow")


def test_slots_kb_labels_use_local_time():
    kb = slots_kb([datetime(2026, 11, 2, 7, 0, tzinfo=UTC)], TZ)
    assert kb.inline_keyboard[0][0].text == "10:00"


def test_slots_kb_three_per_row():
    base = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
    kb = slots_kb([base + timedelta(minutes=30 * i) for i in range(7)], TZ)
    assert [len(r) for r in kb.inline_keyboard] == [3, 3, 1]


def test_slot_callback_roundtrip():
    assert SlotCb.unpack(SlotCb(ts=1730000000).pack()).ts == 1730000000


def test_dates_kb_has_14_buttons():
    days = [date(2026, 11, 2) + timedelta(days=i) for i in range(14)]
    kb = dates_kb(days)
    assert sum(len(r) for r in kb.inline_keyboard) == 14
