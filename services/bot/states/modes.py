"""FSM: кастомный режим чата."""
from aiogram.fsm.state import State, StatesGroup


class CustomModeStates(StatesGroup):
    enter_prompt = State()
    confirm_edit = State()
