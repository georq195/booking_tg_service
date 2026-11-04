"""All user-facing strings (Russian). Dynamic parts are HTML-escaped by callers."""

from html import escape

GREETING = (
    "Здравствуйте, {name}! Я помогу записаться на приём.\n"
    "Ваши записи: /my"
)
NO_SERVICES = "Пока нет доступных услуг. Загляните, пожалуйста, позже."
CHOOSE_SERVICE = "Выберите услугу:"
CHOOSE_DATE = "Выберите дату:"
CHOOSE_SLOT = "Свободное время на {date}:"
NO_SLOTS = "На {date} свободного времени нет. Выберите другую дату."
CONFIRM_SUMMARY = (
    "Проверьте запись:\n"
    "Услуга: {service}\n"
    "Дата: {date}\n"
    "Время: {time}"
)
CONFIRM_BUTTON = "Подтвердить"
BOOKED = (
    "Вы записаны!\n"
    "Услуга: {service}\n"
    "Дата: {date}\n"
    "Время: {time}\n\n"
    "Ваши записи: /my"
)
SLOT_TAKEN = "К сожалению, это время уже занято. Выберите другое."
SLOT_IN_PAST = "Это время уже прошло. Выберите другое."
SLOT_TOO_SOON = "Запись на сегодня закрыта, доступна со следующего дня. Выберите другую дату."
SESSION_EXPIRED = "Сессия устарела, начните заново: /start"
SERVICE_UNAVAILABLE = "Эта услуга больше недоступна. Выберите другую:"

BOT_CMD_START_DESC = "Записаться на приём"
BOT_CMD_MY_DESC = "Мои записи: отмена и перенос"
FALLBACK_HINT = (
    "Не понял сообщение. Записаться на приём: /start. "
    "Ваши записи, отмена и перенос: /my."
)

# My bookings
NO_BOOKINGS = "У вас нет предстоящих записей. Записаться: /start"
MY_BOOKINGS_TITLE = "Ваши записи:"
BOOKING_LINE = "{date} {time} - {service}"
CANCEL_BUTTON = "Отменить {when}"
MOVE_BUTTON = "Перенести {when}"
CANCEL_ASK = "Отменить запись?\n{date} {time} - {service}"
CANCEL_YES_BUTTON = "Да, отменить"
CANCEL_NO_BUTTON = "Нет, оставить"
CANCELLED = "Запись отменена."
ALREADY_CANCELLED = "Эта запись уже отменена."
BOOKING_NOT_ACTIVE = "Эта запись уже неактивна: изменить её нельзя."
TOO_LATE = "Изменить запись уже нельзя: до приёма осталось слишком мало времени."
BOOKING_NOT_FOUND = "Запись не найдена."
NOT_YOUR_BOOKING = "Это не ваша запись."
RESCHEDULE_SERVICE_GONE = "Эта услуга больше недоступна, перенос невозможен."
RESCHEDULED = (
    "Запись перенесена!\n"
    "Услуга: {service}\n"
    "Дата: {date}\n"
    "Время: {time}"
)

# Fixed names, independent of the process locale. Index = date.weekday().
WEEKDAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

# Admin panel
ADMIN_MENU = "Админ-панель:"
ADMIN_BTN_SCHEDULE = "График работы"
ADMIN_BTN_DAYOFF = "Закрыть день"
ADMIN_BTN_DAYSOFF = "Закрытые дни"
ADMIN_BTN_SERVICES = "Услуги"
ADMIN_BTN_BOOKINGS = "Записи на день"
ADMIN_BTN_EXPORT = "Экспорт записей"
ADMIN_BTN_BACK = "« В меню"
ADMIN_NO_BOOKINGS = "На {date} записей нет."
ADMIN_DAY_BOOKINGS = "Записи на {date}:"
ADMIN_CANCEL_BTN = "Отменить {time}"
ADMIN_CANCEL_ASK = "Отменить запись?\n{line}"
ADMIN_CANCELLED = "Запись отменена, клиент уведомлён."
ADMIN_CANCELLED_NOT_NOTIFIED = (
    "Запись отменена, но уведомить клиента не удалось: {names}. "
    "Свяжитесь с ним сами."
)
ADMIN_NOT_NOTIFIED = "Не удалось уведомить: {names}. Свяжитесь с ними сами."
CLIENT_BOOKING_CANCELLED = "Ваша запись отменена.\n{date} {time} — {service}"

ADMIN_SCHEDULE_TITLE = "График работы (нажмите день, чтобы изменить):"
ADMIN_WEEKDAY_OFF = "выходной"
ADMIN_WEEKDAY_OFF_BTN = "Выходной"
ADMIN_SCHEDULE_PROMPT = (
    "Рабочие часы для дня «{weekday}». Отправьте текстом в формате "
    "10:00-18:00 или с перерывом 10:00-18:00 14:00-15:00, "
    "либо нажмите «Выходной»."
)
ADMIN_SCHEDULE_SAVED = "График для дня «{weekday}» сохранён: {value}."
ADMIN_HOURS_BAD_FORMAT = (
    "Не удалось разобрать время. Формат: 10:00-18:00 "
    "или 10:00-18:00 14:00-15:00. Попробуйте ещё раз."
)
ADMIN_HOURS_END_BEFORE_START = (
    "Конец рабочего дня должен быть позже начала. Попробуйте ещё раз."
)
ADMIN_HOURS_BAD_BREAK = (
    "Перерыв должен начинаться раньше, чем заканчивается, и лежать внутри "
    "рабочих часов. Попробуйте ещё раз."
)

ADMIN_DAYOFF_CHOOSE = "Какой день закрыть?"
ADMIN_DAYOFF_DONE = "День {date} закрыт."
ADMIN_DAYOFF_CONFIRM = (
    "На {date} есть записи:\n{lines}\n\n"
    "Закрыть день и отменить их? Клиенты получат уведомление."
)
ADMIN_DAYOFF_YES_BTN = "Да, закрыть и отменить"
ADMIN_DAYOFF_CONFIRM_EMPTY = "Закрыть день {date}? Записей на него нет."
ADMIN_DAYOFF_YES_EMPTY_BTN = "Да, закрыть"
ADMIN_DAYSOFF_TITLE = (
    "Закрытые дни. Нажмите на день, чтобы открыть его снова "
    "(отменённые записи не восстанавливаются):"
)
ADMIN_DAYSOFF_EMPTY = "Закрытых дней нет."
ADMIN_DAYOFF_REOPEN_BTN = "Открыть {date}"
ADMIN_DAYOFF_REOPENED = "День {date} снова открыт."
ADMIN_DAYOFF_ALREADY_OPEN = "День {date} уже открыт."
ADMIN_SCHEDULE_WARN = (
    "Для дня «{weekday}» новый график: {value}.\n"
    "Будущие записи вне этого графика:\n{lines}\n\n"
    "Записи сами не отменятся, их останется отменить вручную. Сохранить график?"
)
ADMIN_SCHEDULE_WARN_MORE = "…и ещё {count}"
ADMIN_SCHEDULE_SAVE_YES_BTN = "Да, сохранить график"
ADMIN_DAYOFF_DONE_NOTIFIED = "День {date} закрыт, отменено записей: {count}."

ADMIN_SERVICES_TITLE = "Услуги (нажмите, чтобы изменить):"
ADMIN_SERVICES_EMPTY = "Услуг пока нет."
ADMIN_SERVICE_ADD_BTN = "Добавить услугу"
ADMIN_SERVICE_HIDDEN_MARK = " (скрыта)"
ADMIN_SERVICE_CARD = "{title}\nДлительность: {duration} мин\nЦена: {price}{hidden}"
ADMIN_SERVICE_EDIT_TITLE_BTN = "Название"
ADMIN_SERVICE_EDIT_DURATION_BTN = "Длительность"
ADMIN_SERVICE_EDIT_PRICE_BTN = "Цена"
ADMIN_SERVICE_HIDE_BTN = "Скрыть"
ADMIN_SERVICE_HIDDEN = "Услуга скрыта от клиентов."
ADMIN_SERVICE_NOT_FOUND = "Услуга не найдена."
ADMIN_ASK_TITLE = "Введите название услуги:"
ADMIN_ASK_DURATION = "Введите длительность в минутах (целое число от 1 до 1440):"
ADMIN_ASK_PRICE = "Введите цену (целое число, 0 или больше):"
ADMIN_BAD_TITLE = "Название должно быть непустым и не длиннее 255 символов. Попробуйте ещё раз."
ADMIN_BAD_NUMBER = "Нужно целое число от 1 до 1440. Попробуйте ещё раз."
ADMIN_BAD_PRICE = "Нужно целое число от 0 до 1000000000. Попробуйте ещё раз."
ADMIN_SERVICE_ADDED = "Услуга добавлена."
ADMIN_SERVICE_UPDATED = "Услуга обновлена."
ADMIN_ERROR = "Что-то пошло не так, попробуйте ещё раз."

# Export. Periods are computed in the configured timezone: "7 дней" = today
# through today+6, "месяц" = the current calendar month.
EXPORT_CHOOSE_PERIOD = "За какой период выгрузить записи?"
EXPORT_CHOOSE_FORMAT = "В каком формате?"
EXPORT_BTN_TODAY = "Сегодня"
EXPORT_BTN_WEEK = "7 дней"
EXPORT_BTN_MONTH = "Месяц"
EXPORT_BTN_EXCEL = "Excel"
EXPORT_BTN_GSHEET = "Google Таблица"
EXPORT_STATUS_LABELS = {
    "active": "активна",
    "cancelled": "отменена",
    "done": "выполнена",
}
EXPORT_XLSX_CAPTION = "Записи за период {start} - {end}: {count}."
EXPORT_GSHEET_DONE = "Записи за период {start} - {end} ({count}) выгружены:\n{url}"
EXPORT_DONE = "Файл отправлен."
EXPORT_FAILED = "Не удалось выгрузить записи. Подробности в логе бота, попробуйте ещё раз."
EXPORT_GSHEET_NOT_CONFIGURED = (
    "Google Таблица не настроена.\n"
    "1. Создайте сервисный аккаунт Google и скачайте его JSON-ключ в папку credentials/.\n"
    "2. Откройте нужную Google Таблицу и дайте доступ редактора на email "
    "сервисного аккаунта (поле client_email в JSON).\n"
    "3. Укажите в .env переменные GSHEETS_CREDENTIALS_PATH (путь к JSON) и "
    "GSHEETS_SPREADSHEET_ID (ID таблицы из её адреса) и перезапустите бота."
)


def format_booking_line(booking, user, service, tz) -> str:
    """'12:00 — Имя (Услуга)'; user-supplied parts are HTML-escaped."""
    local = booking.start_at.astimezone(tz)
    return f"{local:%H:%M} — {escape(user.name)} ({escape(service.title)})"

# Reminders (service title is HTML-escaped by the caller)
REMINDER_24H = (
    "Напоминаем: завтра у вас запись.\n"
    "Услуга: {service}\n"
    "Дата: {date}\n"
    "Время: {time}"
)
REMINDER_2H = (
    "Напоминаем: через 2 часа у вас запись.\n"
    "Услуга: {service}\n"
    "Дата: {date}\n"
    "Время: {time}"
)
