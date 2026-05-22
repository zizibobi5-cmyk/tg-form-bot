"""FSM-состояния заполнения анкеты."""
from aiogram.fsm.state import State, StatesGroup


class ApplicationForm(StatesGroup):
    name_surname = State()
    age_height = State()
    magic_abilities = State()
    character = State()
    biography = State()
    interesting_facts = State()
    work_position = State()
    place_of_living = State()
    roll = State()
    photos = State()
    preview = State()
