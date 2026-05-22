"""FSM-состояния задавания вопроса."""
from aiogram.fsm.state import State, StatesGroup


class QuestionForm(StatesGroup):
    waiting_text = State()
