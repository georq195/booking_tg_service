from app.services.errors import SlotInPast, SlotTaken, SlotTooSoon
from app.utils import texts

# Client-facing message for each slot error a booking/reschedule attempt can raise.
SLOT_ERROR_TEXTS: dict[type[Exception], str] = {
    SlotTaken: texts.SLOT_TAKEN,
    SlotInPast: texts.SLOT_IN_PAST,
    SlotTooSoon: texts.SLOT_TOO_SOON,
}
