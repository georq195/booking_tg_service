import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import select

from app.db.models import Booking, BookingStatus, Service, User
from app.utils import texts

logger = logging.getLogger(__name__)

H24 = timedelta(hours=24)
H2 = timedelta(hours=2)


class ReminderService:
    """Sends 24h / 2h reminders. `bot` is any object with
    `async send_message(chat_id, text)`. `is_permanent_error(exc)` tells
    whether a send failure will never succeed (bot blocked, chat gone): such
    bookings are marked as reminded so they are not retried every minute.
    Any other failure is transient: the flag stays unset and the next tick retries."""

    def __init__(
        self,
        session_factory,
        bot,
        tz,
        is_permanent_error: Callable[[Exception], bool] | None = None,
    ):
        self._sf = session_factory
        self._bot = bot
        self._tz = tz
        self._is_permanent = is_permanent_error or (lambda exc: False)

    async def run_once(self) -> int:
        return await self.send_due(datetime.now(UTC))

    async def send_due(self, now: datetime) -> int:
        async with self._sf() as s:
            ids = (
                await s.scalars(
                    select(Booking.id).where(
                        Booking.status == BookingStatus.active,
                        Booking.start_at > now,
                        Booking.start_at <= now + H24,
                        ~(Booking.reminded_24h & Booking.reminded_2h),
                    )
                )
            ).all()
        sent = 0
        for booking_id in ids:
            try:
                sent += await self._process(booking_id, now)
            except Exception:
                logger.exception("Reminder processing failed for booking %s", booking_id)
        return sent

    async def _process(self, booking_id: int, now: datetime) -> int:
        async with self._sf() as s:
            row = (
                await s.execute(
                    select(Booking, User, Service)
                    .join(User, User.id == Booking.user_id)
                    .join(Service, Service.id == Booking.service_id)
                    .where(Booking.id == booking_id)
                )
            ).one_or_none()
            if row is None:
                return 0
            booking, user, service = row
            start = booking.start_at
            if booking.status != BookingStatus.active or start <= now:
                return 0

            if not booking.reminded_2h and now >= start - H2:
                template, created_late = texts.REMINDER_2H, booking.created_at > start - H2
                mark_24h = True
            elif not booking.reminded_24h and now >= start - H24:
                template, created_late = texts.REMINDER_24H, booking.created_at > start - H24
                mark_24h = False
            else:
                return 0

            def mark():
                booking.reminded_24h = True
                if mark_24h:
                    booking.reminded_2h = True

            if created_late:
                mark()
                await s.commit()
                return 0

            local = start.astimezone(self._tz)
            text = template.format(
                service=escape(service.title),
                date=f"{local:%d.%m.%Y}",
                time=f"{local:%H:%M}",
            )
            try:
                await self._bot.send_message(user.telegram_id, text)
            except Exception as exc:
                if self._is_permanent(exc):
                    logger.warning(
                        "Reminder for booking %s undeliverable (%s), marking as sent",
                        booking_id, type(exc).__name__,
                    )
                    mark()
                    await s.commit()
                else:
                    logger.warning(
                        "Reminder for booking %s failed (%s), will retry",
                        booking_id, type(exc).__name__,
                    )
                return 0
            mark()
            await s.commit()
            return 1
