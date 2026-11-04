from datetime import date, datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.filters import IsAdmin, IsPrivateChat
from app.bot.handlers.admin.common import not_notified_names, notify_cancelled, show
from app.bot.keyboards.admin import (
    AdmDayCb,
    AdmMenuCb,
    AdmWeekdayCb,
    back_kb,
    dayoff_confirm_kb,
    days_kb,
    daysoff_kb,
    describe_work_day,
    schedule_confirm_kb,
    schedule_kb,
    weekday_prompt_kb,
)
from app.bot.states import AdminFlow
from app.services.booking_service import BookingService
from app.services.slots import WorkDay
from app.services.errors import InvalidWorkDay
from app.utils import texts
from app.utils.dates import day_label, next_days
from app.utils.parsing import parse_work_hours

_INVALID_TEXTS = {"end_before_start": texts.ADMIN_HOURS_END_BEFORE_START}


async def on_schedule_open(
    callback: CallbackQuery, state: FSMContext, booking_service: BookingService
) -> None:
    await callback.answer()
    await state.clear()
    schedule = await booking_service.get_work_schedule()
    await show(callback, texts.ADMIN_SCHEDULE_TITLE, schedule_kb(schedule))


_WARN_LIMIT = 20


async def _warning_lines(
    booking_service: BookingService, bookings: list
) -> str:
    details = await booking_service.booking_details([b.id for b in bookings])
    tz = booking_service.tz
    lines = [
        f"{day_label(d.booking.start_at.astimezone(tz).date())} "
        + texts.format_booking_line(d.booking, d.user, d.service, tz)
        for d in details[:_WARN_LIMIT]
    ]
    if len(details) > _WARN_LIMIT:
        lines.append(texts.ADMIN_SCHEDULE_WARN_MORE.format(count=len(details) - _WARN_LIMIT))
    return "\n".join(lines)


def _saved_text(weekday: int, work: WorkDay | None) -> str:
    return texts.ADMIN_SCHEDULE_SAVED.format(
        weekday=texts.WEEKDAYS_RU[weekday], value=describe_work_day(work)
    )


async def on_weekday(
    callback: CallbackQuery,
    callback_data: AdmWeekdayCb,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    await callback.answer()
    weekday = callback_data.weekday
    if not 0 <= weekday <= 6:
        return
    name = texts.WEEKDAYS_RU[weekday]
    action = callback_data.action
    if action == "off":
        await state.clear()
        stranded = await booking_service.bookings_outside_work_day(weekday, None)
        if stranded:
            await show(
                callback,
                texts.ADMIN_SCHEDULE_WARN.format(
                    weekday=name,
                    value=describe_work_day(None),
                    lines=await _warning_lines(booking_service, stranded),
                ),
                schedule_confirm_kb(weekday, "off_yes"),
            )
            return
        action = "off_yes"
    if action == "off_yes":
        await state.clear()
        await booking_service.set_work_schedule(weekday, None)
        await show(
            callback,
            _saved_text(weekday, None),
            schedule_kb(await booking_service.get_work_schedule()),
        )
        return
    if action == "save_yes":
        data = await state.get_data()
        pending = data.get("pending_hours")
        if data.get("weekday") != weekday or not pending:
            await state.clear()
            await show(callback, texts.ADMIN_ERROR)
            return
        work = parse_work_hours(pending)
        await booking_service.set_work_schedule(weekday, work)
        await state.clear()
        await show(
            callback,
            _saved_text(weekday, work),
            schedule_kb(await booking_service.get_work_schedule()),
        )
        return
    await state.clear()
    await state.set_state(AdminFlow.waiting_hours)
    await state.update_data(weekday=weekday)
    await show(
        callback,
        texts.ADMIN_SCHEDULE_PROMPT.format(weekday=name),
        weekday_prompt_kb(weekday),
    )


async def on_hours(
    message: Message, state: FSMContext, booking_service: BookingService
) -> None:
    data = await state.get_data()
    weekday = data.get("weekday")
    if weekday is None:
        await state.clear()
        await message.answer(texts.ADMIN_ERROR)
        return
    try:
        work = parse_work_hours(message.text or "")
    except ValueError:
        await message.answer(texts.ADMIN_HOURS_BAD_FORMAT)
        return
    try:
        # Also validates the hours, so the confirm button can never hit bad ones.
        stranded = await booking_service.bookings_outside_work_day(weekday, work)
    except InvalidWorkDay as exc:
        await message.answer(_INVALID_TEXTS.get(exc.reason, texts.ADMIN_HOURS_BAD_BREAK))
        return
    if stranded:
        await state.update_data(pending_hours=message.text)
        await message.answer(
            texts.ADMIN_SCHEDULE_WARN.format(
                weekday=texts.WEEKDAYS_RU[weekday],
                value=describe_work_day(work),
                lines=await _warning_lines(booking_service, stranded),
            ),
            reply_markup=schedule_confirm_kb(weekday, "save_yes"),
        )
        return
    try:
        await booking_service.set_work_schedule(weekday, work)
    except InvalidWorkDay as exc:
        await message.answer(_INVALID_TEXTS.get(exc.reason, texts.ADMIN_HOURS_BAD_BREAK))
        return
    await state.clear()
    await message.answer(
        _saved_text(weekday, work),
        reply_markup=schedule_kb(await booking_service.get_work_schedule()),
    )


async def on_dayoff_open(
    callback: CallbackQuery, state: FSMContext, booking_service: BookingService
) -> None:
    await callback.answer()
    await state.clear()
    today = datetime.now(booking_service.tz).date()
    await show(callback, texts.ADMIN_DAYOFF_CHOOSE, days_kb(next_days(today), "off"))


async def on_dayoff_pick(
    callback: CallbackQuery, callback_data: AdmDayCb, booking_service: BookingService
) -> None:
    await callback.answer()
    day = date.fromisoformat(callback_data.day)
    affected = await booking_service.list_for_day(day)
    if not affected:
        await show(
            callback,
            texts.ADMIN_DAYOFF_CONFIRM_EMPTY.format(date=day_label(day)),
            dayoff_confirm_kb(day, has_bookings=False),
        )
        return
    details = await booking_service.booking_details([b.id for b in affected])
    lines = "\n".join(
        texts.format_booking_line(d.booking, d.user, d.service, booking_service.tz)
        for d in details
    )
    await show(
        callback,
        texts.ADMIN_DAYOFF_CONFIRM.format(date=day_label(day), lines=lines),
        dayoff_confirm_kb(day),
    )


async def on_daysoff_open(
    callback: CallbackQuery, state: FSMContext, booking_service: BookingService
) -> None:
    await callback.answer()
    await state.clear()
    today = datetime.now(booking_service.tz).date()
    days = await booking_service.list_days_off(today)
    if not days:
        await show(callback, texts.ADMIN_DAYSOFF_EMPTY, back_kb())
        return
    await show(callback, texts.ADMIN_DAYSOFF_TITLE, daysoff_kb(days))


async def on_dayoff_reopen(
    callback: CallbackQuery, callback_data: AdmDayCb, booking_service: BookingService
) -> None:
    await callback.answer()
    day = date.fromisoformat(callback_data.day)
    reopened = await booking_service.remove_day_off(day)
    template = texts.ADMIN_DAYOFF_REOPENED if reopened else texts.ADMIN_DAYOFF_ALREADY_OPEN
    await show(callback, template.format(date=day_label(day)), back_kb())


async def on_dayoff_confirm(
    callback: CallbackQuery,
    callback_data: AdmDayCb,
    booking_service: BookingService,
    bot: Bot,
) -> None:
    await callback.answer()
    day = date.fromisoformat(callback_data.day)
    cancelled = await booking_service.set_day_off(day, None, confirm=True)
    if cancelled:
        details = await booking_service.booking_details([b.id for b in cancelled])
        failed = await notify_cancelled(bot, details, booking_service)
        text = texts.ADMIN_DAYOFF_DONE_NOTIFIED.format(
            date=day_label(day), count=len(cancelled)
        )
        if failed:
            text += "\n" + texts.ADMIN_NOT_NOTIFIED.format(
                names=not_notified_names(failed)
            )
    else:
        text = texts.ADMIN_DAYOFF_DONE.format(date=day_label(day))
    await show(callback, text)


def build_router(is_admin: IsAdmin) -> Router:
    router = Router(name="admin_schedule")
    router.message.filter(is_admin, IsPrivateChat())
    router.callback_query.filter(is_admin, IsPrivateChat())
    cb = router.callback_query
    cb.register(on_schedule_open, AdmMenuCb.filter(F.action == "schedule"))
    cb.register(on_dayoff_open, AdmMenuCb.filter(F.action == "dayoff"))
    cb.register(on_daysoff_open, AdmMenuCb.filter(F.action == "daysoff"))
    cb.register(on_dayoff_reopen, AdmDayCb.filter(F.kind == "reopen"))
    cb.register(on_weekday, AdmWeekdayCb.filter())
    cb.register(on_dayoff_pick, AdmDayCb.filter(F.kind == "off"))
    cb.register(on_dayoff_confirm, AdmDayCb.filter(F.kind == "off_yes"))
    router.message.register(
        on_hours, AdminFlow.waiting_hours, F.text, ~F.text.startswith("/")
    )
    return router
