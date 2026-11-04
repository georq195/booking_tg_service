import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Booking,
    BookingStatus,
    DayOff,
    Service,
    User,
    WorkSchedule,
)
from app.services.exporters import BookingRow
from app.services.errors import (
    AlreadyCancelled,
    BookingNotActive,
    BookingNotFound,
    InvalidWorkDay,
    NotYourBooking,
    ServiceNotFound,
    SlotInPast,
    SlotTooSoon,
    SlotTaken,
    TooLateToChange,
)
from app.services.slots import WorkDay, compute_free_slots
from app.utils.dates import earliest_booking_day

MAX_DURATION_MIN = 24 * 60
MAX_PRICE = 10**9


@dataclass(frozen=True)
class BookingDetails:
    """A booking with the client and service it refers to (for admin views)."""

    booking: Booking
    user: User
    service: Service


class BookingService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        tz: ZoneInfo,
        step_min: int,
        cancel_deadline_hours: int,
    ) -> None:
        if step_min <= 0:
            raise ValueError("step_min must be positive")
        if cancel_deadline_hours < 0:
            raise ValueError("cancel_deadline_hours must not be negative")
        self._session_factory = session_factory
        self._tz = tz
        self._step_min = step_min
        self._deadline = timedelta(hours=cancel_deadline_hours)
        self._lock = asyncio.Lock()

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    async def list_active_services(self) -> list[Service]:
        async with self._session_factory() as s:
            result = await s.scalars(
                select(Service).where(Service.is_active).order_by(Service.id)
            )
            return list(result)

    async def list_active_for_user(
        self, user_id: int, now: datetime | None = None
    ) -> list[Booking]:
        now = now or datetime.now(UTC)
        async with self._session_factory() as s:
            result = await s.scalars(
                select(Booking)
                .where(
                    Booking.user_id == user_id,
                    Booking.status == BookingStatus.active,
                    Booking.start_at > now,
                )
                .order_by(Booking.start_at, Booking.id)
            )
            return list(result)

    async def service_titles(self, service_ids: list[int]) -> dict[int, str]:
        """Titles by id, including deactivated services (old bookings keep them)."""
        if not service_ids:
            return {}
        async with self._session_factory() as s:
            rows = await s.execute(
                select(Service.id, Service.title).where(Service.id.in_(service_ids))
            )
            return {sid: title for sid, title in rows.all()}

    async def get_free_slots(
        self, day: date, service_id: int, now: datetime | None = None
    ) -> list[datetime]:
        now = now or datetime.now(UTC)
        async with self._session_factory() as s:
            service = await self._get_service(s, service_id)
            return await self._free_slots(s, day, service, now)

    async def create(
        self,
        user_id: int,
        service_id: int,
        start_at: datetime,
        now: datetime | None = None,
    ) -> Booking:
        now = now or datetime.now(UTC)
        async with self._lock, self._session_factory() as s:
            service = await self._get_service(s, service_id)
            booking = await self._new_booking(s, user_id, service, start_at, now)
            await s.commit()
            return booking

    async def cancel(
        self, booking_id: int, user_id: int, now: datetime | None = None
    ) -> Booking:
        now = now or datetime.now(UTC)
        async with self._lock, self._session_factory() as s:
            booking = await self._get_changeable(s, booking_id, user_id, now)
            booking.status = BookingStatus.cancelled
            await s.commit()
            return booking

    async def reschedule(
        self,
        booking_id: int,
        user_id: int,
        new_start: datetime,
        now: datetime | None = None,
    ) -> Booking:
        now = now or datetime.now(UTC)
        async with self._lock, self._session_factory() as s:
            old = await self._get_owned_active(s, booking_id, user_id)
            if old.start_at == new_start:
                return old
            self._check_deadline(old, now)
            service = await s.get(Service, old.service_id)
            new = await self._new_booking(
                s, user_id, service, new_start, now, exclude_id=old.id
            )
            old.status = BookingStatus.cancelled
            await s.commit()
            return new

    async def _get_service(self, s: AsyncSession, service_id: int) -> Service:
        service = await s.get(Service, service_id)
        if service is None or not service.is_active:
            raise ValueError(f"unknown or inactive service: {service_id}")
        return service

    async def _get_owned_active(
        self, s: AsyncSession, booking_id: int, user_id: int
    ) -> Booking:
        booking = await s.get(Booking, booking_id)
        if booking is None:
            raise BookingNotFound(booking_id)
        if booking.user_id != user_id:
            raise NotYourBooking(booking_id)
        if booking.status == BookingStatus.cancelled:
            raise AlreadyCancelled(booking_id)
        if booking.status != BookingStatus.active:
            raise BookingNotActive(booking_id)
        return booking

    def _check_deadline(self, booking: Booking, now: datetime) -> None:
        if booking.start_at - now < self._deadline:
            raise TooLateToChange(booking.id)

    async def _get_changeable(
        self, s: AsyncSession, booking_id: int, user_id: int, now: datetime
    ) -> Booking:
        booking = await self._get_owned_active(s, booking_id, user_id)
        self._check_deadline(booking, now)
        return booking

    async def _new_booking(
        self,
        s: AsyncSession,
        user_id: int,
        service: Service,
        start_at: datetime,
        now: datetime,
        exclude_id: int | None = None,
    ) -> Booking:
        if start_at < now:
            raise SlotInPast(start_at)
        day = start_at.astimezone(self._tz).date()
        if self._is_closed_for_booking(day, now):
            raise SlotTooSoon(start_at)
        free = await self._free_slots(s, day, service, now, exclude_id)
        if start_at not in free:
            raise SlotTaken(start_at)
        booking = Booking(
            user_id=user_id,
            service_id=service.id,
            start_at=start_at,
            end_at=start_at + timedelta(minutes=service.duration_min),
            status=BookingStatus.active,
        )
        s.add(booking)
        await s.flush()
        return booking

    def _is_closed_for_booking(self, day: date, now: datetime) -> bool:
        """Same-day booking is closed: the first bookable day is tomorrow in the
        configured timezone (not in UTC)."""
        return day < earliest_booking_day(now.astimezone(self._tz).date())

    def _day_bounds(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time.min, tzinfo=self._tz).astimezone(UTC)
        end = datetime.combine(
            day + timedelta(days=1), time.min, tzinfo=self._tz
        ).astimezone(UTC)
        return start, end

    async def _active_on_day(self, s: AsyncSession, day: date) -> list[Booking]:
        day_start, day_end = self._day_bounds(day)
        result = await s.scalars(
            select(Booking)
            .where(
                Booking.status == BookingStatus.active,
                Booking.start_at >= day_start,
                Booking.start_at < day_end,
            )
            .order_by(Booking.start_at, Booking.id)
        )
        return list(result)

    async def _free_slots(
        self,
        s: AsyncSession,
        day: date,
        service: Service,
        now: datetime,
        exclude_id: int | None = None,
    ) -> list[datetime]:
        if self._is_closed_for_booking(day, now):
            return []
        if await s.scalar(select(DayOff.id).where(DayOff.day == day)) is not None:
            return []
        row = await s.scalar(
            select(WorkSchedule).where(WorkSchedule.weekday == day.weekday())
        )
        work = (
            WorkDay(row.start_time, row.end_time, row.break_start, row.break_end)
            if row
            else None
        )
        day_start, day_end = self._day_bounds(day)
        query = select(Booking.start_at, Booking.end_at).where(
            Booking.status == BookingStatus.active,
            Booking.start_at < day_end,
            Booking.end_at > day_start,
        )
        if exclude_id is not None:
            query = query.where(Booking.id != exclude_id)
        busy = [(a, b) for a, b in (await s.execute(query)).all()]
        return compute_free_slots(
            day, work, busy, service.duration_min, self._step_min, self._tz, now
        )

    # ---- admin operations -------------------------------------------------

    async def list_for_day(self, day: date) -> list[Booking]:
        """Active bookings starting on the local `day`, ordered by time."""
        async with self._session_factory() as s:
            return await self._active_on_day(s, day)

    async def booking_details(self, booking_ids: list[int]) -> list[BookingDetails]:
        """Bookings (any status) with client and service, ordered by time."""
        if not booking_ids:
            return []
        async with self._session_factory() as s:
            rows = await s.execute(
                select(Booking, User, Service)
                .join(User, Booking.user_id == User.id)
                .join(Service, Booking.service_id == Service.id)
                .where(Booking.id.in_(booking_ids))
                .order_by(Booking.start_at, Booking.id)
            )
            return [BookingDetails(b, u, sv) for b, u, sv in rows.all()]

    async def list_rows(self, date_from: date, date_to: date) -> list[BookingRow]:
        """Bookings of any status starting on local days date_from..date_to
        (inclusive), ordered by time, for export."""
        start, _ = self._day_bounds(date_from)
        _, end = self._day_bounds(date_to)
        async with self._session_factory() as s:
            rows = await s.execute(
                select(Booking, User, Service)
                .join(User, Booking.user_id == User.id)
                .join(Service, Booking.service_id == Service.id)
                .where(Booking.start_at >= start, Booking.start_at < end)
                .order_by(Booking.start_at, Booking.id)
            )
            return [
                BookingRow(
                    booking_id=b.id,
                    start_local=b.start_at.astimezone(self._tz),
                    client_name=u.name,
                    phone=u.phone,
                    service_title=sv.title,
                    price=sv.price,
                    status=b.status.value,
                )
                for b, u, sv in rows.all()
            ]

    async def admin_cancel(self, booking_id: int) -> Booking:
        """Cancel without ownership or deadline checks."""
        async with self._lock, self._session_factory() as s:
            booking = await s.get(Booking, booking_id)
            if booking is None:
                raise BookingNotFound(booking_id)
            if booking.status == BookingStatus.cancelled:
                raise AlreadyCancelled(booking_id)
            booking.status = BookingStatus.cancelled
            await s.commit()
            return booking

    async def set_day_off(
        self, day: date, reason: str | None, confirm: bool
    ) -> list[Booking]:
        """Close `day`. With active bookings and confirm=False nothing changes and
        those bookings are returned; with confirm=True the day is closed and the
        bookings are cancelled (returned). Closing a closed day is a no-op."""
        async with self._lock, self._session_factory() as s:
            affected = await self._active_on_day(s, day)
            if affected and not confirm:
                return affected
            existing = await s.scalar(select(DayOff).where(DayOff.day == day))
            if existing is None:
                s.add(DayOff(day=day, reason=reason))
            for booking in affected:
                booking.status = BookingStatus.cancelled
            await s.commit()
            return affected

    async def remove_day_off(self, day: date) -> bool:
        """Reopen a closed day. Returns False when it was not closed. Bookings
        cancelled when the day was closed are not restored."""
        async with self._lock, self._session_factory() as s:
            existing = await s.scalar(select(DayOff).where(DayOff.day == day))
            if existing is None:
                return False
            await s.delete(existing)
            await s.commit()
            return True

    async def list_days_off(self, from_day: date) -> list[date]:
        """Closed days on or after `from_day`, ascending."""
        async with self._session_factory() as s:
            rows = await s.scalars(
                select(DayOff.day).where(DayOff.day >= from_day).order_by(DayOff.day)
            )
            return list(rows)

    async def bookings_outside_work_day(
        self, weekday: int, work: WorkDay | None, now: datetime | None = None
    ) -> list[Booking]:
        """Future active bookings on local `weekday` that would not fit `work`:
        all of them when work is None, otherwise those starting before it opens,
        ending after it closes or overlapping its break. Read-only: used to warn
        before a schedule change, nothing is cancelled. Invalid `work` raises
        InvalidWorkDay, like set_work_schedule."""
        if work is not None:
            self._check_work_day(work)
        now = now or datetime.now(UTC)
        async with self._session_factory() as s:
            result = await s.scalars(
                select(Booking)
                .where(Booking.status == BookingStatus.active, Booking.start_at > now)
                .order_by(Booking.start_at, Booking.id)
            )
            candidates = [
                b
                for b in result
                if b.start_at.astimezone(self._tz).weekday() == weekday
            ]
        if work is None:
            return candidates
        return [b for b in candidates if not self._fits(b, work)]

    def _fits(self, booking: Booking, work: WorkDay) -> bool:
        day = booking.start_at.astimezone(self._tz).date()

        def at(t: time) -> datetime:
            return datetime.combine(day, t, tzinfo=self._tz).astimezone(UTC)

        if booking.start_at < at(work.start) or booking.end_at > at(work.end):
            return False
        if work.break_start is not None and work.break_end is not None:
            if booking.start_at < at(work.break_end) and at(work.break_start) < booking.end_at:
                return False
        return True

    async def get_work_schedule(self) -> dict[int, WorkDay]:
        async with self._session_factory() as s:
            rows = await s.scalars(select(WorkSchedule))
            return {
                r.weekday: WorkDay(r.start_time, r.end_time, r.break_start, r.break_end)
                for r in rows
            }

    async def set_work_schedule(self, weekday: int, work: WorkDay | None) -> None:
        """Set hours for a weekday (0=Mon); None makes it a regular day off."""
        if not 0 <= weekday <= 6:
            raise ValueError(f"weekday out of range: {weekday}")
        if work is not None:
            self._check_work_day(work)
        async with self._lock, self._session_factory() as s:
            row = await s.scalar(
                select(WorkSchedule).where(WorkSchedule.weekday == weekday)
            )
            if work is None:
                if row is not None:
                    await s.delete(row)
            else:
                if row is None:
                    row = WorkSchedule(weekday=weekday)
                    s.add(row)
                row.start_time = work.start
                row.end_time = work.end
                row.break_start = work.break_start
                row.break_end = work.break_end
            await s.commit()

    async def list_all_services(self) -> list[Service]:
        """All services including hidden ones."""
        async with self._session_factory() as s:
            return list(await s.scalars(select(Service).order_by(Service.id)))

    async def get_service(self, service_id: int) -> Service:
        async with self._session_factory() as s:
            service = await s.get(Service, service_id)
            if service is None:
                raise ServiceNotFound(service_id)
            return service

    async def add_service(self, title: str, duration_min: int, price: int) -> Service:
        self._check_service_values(title, duration_min, price)
        async with self._lock, self._session_factory() as s:
            service = Service(
                title=title.strip(),
                duration_min=duration_min,
                price=price,
                is_active=True,
            )
            s.add(service)
            await s.commit()
            return service

    async def update_service(
        self,
        service_id: int,
        *,
        title: str | None = None,
        duration_min: int | None = None,
        price: int | None = None,
    ) -> Service:
        async with self._lock, self._session_factory() as s:
            service = await s.get(Service, service_id)
            if service is None:
                raise ServiceNotFound(service_id)
            self._check_service_values(
                service.title if title is None else title,
                service.duration_min if duration_min is None else duration_min,
                service.price if price is None else price,
            )
            if title is not None:
                service.title = title.strip()
            if duration_min is not None:
                service.duration_min = duration_min
            if price is not None:
                service.price = price
            await s.commit()
            return service

    async def hide_service(self, service_id: int) -> Service:
        """Hide from clients; existing bookings keep the service."""
        async with self._lock, self._session_factory() as s:
            service = await s.get(Service, service_id)
            if service is None:
                raise ServiceNotFound(service_id)
            service.is_active = False
            await s.commit()
            return service

    @staticmethod
    def _check_service_values(title: str, duration_min: int, price: int) -> None:
        if not title.strip() or len(title.strip()) > 255:
            raise ValueError("title must be 1..255 characters")
        if not 0 < duration_min <= MAX_DURATION_MIN:
            raise ValueError(f"duration must be 1..{MAX_DURATION_MIN} minutes")
        if not 0 <= price <= MAX_PRICE:
            raise ValueError(f"price must be 0..{MAX_PRICE}")

    @staticmethod
    def _check_work_day(work: WorkDay) -> None:
        if work.start >= work.end:
            raise InvalidWorkDay("end_before_start")
        if (work.break_start is None) != (work.break_end is None):
            raise InvalidWorkDay("half_break")
        if work.break_start is not None and work.break_end is not None:
            if not work.start <= work.break_start < work.break_end <= work.end:
                raise InvalidWorkDay("bad_break")
