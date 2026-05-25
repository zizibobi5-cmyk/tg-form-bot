"""Настройки юзербота. Намеренно отдельно от config.py, чтобы юзербот мог
запускаться без BOT_TOKEN (он ему не нужен) и не зависел от шагов
инициализации основного бота.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


def _normalize_database_url(url: str) -> str:
    """Приводит URL к виду, совместимому с SQLAlchemy + asyncpg.

    Дублирует ту же логику, что и в ``config.py``, чтобы юзербот не зависел
    от загрузки настроек бота.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgresql+asyncpg://"):
        parts = urlsplit(url)
        if parts.query:
            keep = []
            for chunk in parts.query.split("&"):
                if not chunk:
                    continue
                key = chunk.split("=", 1)[0].lower()
                if key in {"sslmode", "channel_binding", "options"}:
                    continue
                keep.append(chunk)
            url = urlunsplit(
                (parts.scheme, parts.netloc, parts.path, "&".join(keep), parts.fragment)
            )
    return url


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Переменная окружения {name} обязательна для юзербота")
    return val


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Переменная окружения {name} должна быть int, получено: {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Переменная окружения {name} должна быть числом, получено: {raw!r}") from exc


@dataclass(slots=True)
class UserbotSettings:
    api_id: int
    api_hash: str
    session_string: str
    channel_id: int
    database_url: str
    poll_interval_seconds: float
    publish_delay_between_texts: float
    publish_delay_before_photos: float
    http_port: int
    log_level: str

    @classmethod
    def load(cls) -> "UserbotSettings":
        try:
            api_id = int(_require("TELEGRAM_API_ID"))
        except ValueError as exc:
            raise RuntimeError("TELEGRAM_API_ID должен быть числом") from exc
        return cls(
            api_id=api_id,
            api_hash=_require("TELEGRAM_API_HASH"),
            session_string=_require("TELEGRAM_SESSION"),
            channel_id=int(_require("CHANNEL_ID")),
            database_url=_normalize_database_url(_require("DATABASE_URL")),
            poll_interval_seconds=_get_float("USERBOT_POLL_INTERVAL", default=5.0),
            publish_delay_between_texts=_get_float("CHANNEL_DELAY_BETWEEN_TEXTS", default=5.0),
            publish_delay_before_photos=_get_float("CHANNEL_DELAY_BEFORE_PHOTOS", default=15.0),
            http_port=_get_int("PORT", default=8081),
            log_level=os.getenv("USERBOT_LOG_LEVEL", "INFO"),
        )
