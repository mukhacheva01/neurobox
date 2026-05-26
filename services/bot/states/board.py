"""FSM: доска объявлений."""
from aiogram.fsm.state import State, StatesGroup


class BoardPostStates(StatesGroup):
    enter_text = State()
    enter_photo = State()
    confirm = State()


class BoardCommentStates(StatesGroup):
    enter_text = State()
