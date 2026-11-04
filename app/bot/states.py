from aiogram.fsm.state import State, StatesGroup


class BookingFlow(StatesGroup):
    choosing_service = State()
    choosing_date = State()
    choosing_slot = State()
    confirming = State()


class RescheduleFlow(StatesGroup):
    choosing_date = State()
    choosing_slot = State()


class AdminFlow(StatesGroup):
    waiting_hours = State()
    add_title = State()
    add_duration = State()
    add_price = State()
    edit_value = State()
