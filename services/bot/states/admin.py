"""FSM: админка — рассылка, промокоды, поиск юзера и т.д."""
from aiogram.fsm.state import State, StatesGroup


class BroadcastStates(StatesGroup):
    enter_text = State()
    enter_media = State()
    enter_button = State()
    select_audience = State()
    confirm = State()


class PromoStates(StatesGroup):
    enter_code = State()
    enter_credits = State()
    enter_max_uses = State()
    enter_expiry = State()


class FindUserStates(StatesGroup):
    enter_query = State()


class CreditUserStates(StatesGroup):
    enter_amount = State()
    confirm = State()


class NoteUserStates(StatesGroup):
    enter_note = State()


class AdminSendMessageStates(StatesGroup):
    enter_text = State()


class BoardStopwordStates(StatesGroup):
    enter_word = State()


class UnlimitedByUsernameStates(StatesGroup):
    enter_username = State()
