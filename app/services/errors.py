class BookingError(Exception):
    """Base class for domain errors of the booking service."""


class SlotTaken(BookingError):
    pass


class SlotInPast(BookingError):
    pass


class SlotTooSoon(BookingError):
    """Booking for today (or any day before the first bookable one) is closed."""


class BookingNotFound(BookingError):
    pass


class NotYourBooking(BookingError):
    pass


class TooLateToChange(BookingError):
    pass


class AlreadyCancelled(BookingError):
    pass


class ServiceNotFound(BookingError):
    pass


class InvalidWorkDay(BookingError):
    """Rejected WorkDay; `reason` is end_before_start | half_break | bad_break."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BookingNotActive(BookingError):
    """The booking is neither active nor cancelled (e.g. already done)."""
