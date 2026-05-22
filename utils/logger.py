"""Настройка логирования."""
from __future__ import annotations

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    root.addHandler(handler)
    root.setLevel(level)
    # понижаем уровень шумных библиотек
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
