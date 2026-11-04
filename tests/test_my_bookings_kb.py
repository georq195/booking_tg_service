from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.bot.keyboards.inline import BookingCb, my_bookings_kb
from app.db.models import Booking

TZ = ZoneInfo("Europe/Moscow")


def test_booking_callback_roundtrip():
    packed = BookingCb(booking_id=7, action="cancel").pack()
    assert len(packed.encode()) <= 64
    parsed = BookingCb.unpack(packed)
    assert (parsed.booking_id, parsed.action) == (7, "cancel")


def test_my_bookings_kb_has_cancel_and_move_per_booking():
    bookings = [
        Booking(id=1, start_at=datetime(2026, 11, 3, 7, 0, tzinfo=UTC)),
        Booking(id=2, start_at=datetime(2026, 11, 4, 9, 30, tzinfo=UTC)),
    ]
    kb = my_bookings_kb(bookings, TZ)
    buttons = [b for row in kb.inline_keyboard for b in row]
    parsed = [BookingCb.unpack(b.callback_data) for b in buttons]
    for booking in bookings:
        actions = sorted(p.action for p in parsed if p.booking_id == booking.id)
        assert actions == ["cancel", "move"]
    assert "10:00" in buttons[0].text
