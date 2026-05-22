"""FSM-состояния модератора."""
from aiogram.fsm.state import State, StatesGroup


class ModerationFlow(StatesGroup):
    awaiting_reject_reason = State()
    awaiting_answer = State()
