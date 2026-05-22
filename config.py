"""Конфигурация бота. Загружает переменные из .env и валидирует их."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _normalize_database_url(url: str) -> str:
    """Приводит URL к виду, совместимому с SQLAlchemy + asyncpg.

    - Neon/Render выдают строку вида ``postgresql://...`` или ``postgres://...``;
      для async SQLAlchemy нужен драйвер ``postgresql+asyncpg``.
    - asyncpg не понимает query-параметр ``sslmode=...``; SSL он включает
      сам, поэтому такой параметр нужно вырезать.
    - ``channel_binding=require`` и прочие psql-only параметры тоже убираем.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    # Удаляем несовместимые с asyncpg query-параметры.
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
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(keep), parts.fragment))
    return url


def _get_int(name: str, default: int | None = None, required: bool = False) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        if required:
            raise RuntimeError(f"Переменная окружения {name} обязательна")
        return default  # type: ignore[return-value]
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Переменная окружения {name} должна быть целым числом, получено: {raw!r}") from exc


def _get_float(name: str, default: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Переменная окружения {name} должна быть числом, получено: {raw!r}") from exc


def _get_int_list(name: str) -> list[int]:
    raw = os.getenv(name, "")
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(int(part))
        except ValueError as exc:
            raise RuntimeError(f"Переменная {name} содержит некорректный ID: {part!r}") from exc
    return result


def _get_str(name: str, default: str | None = None, required: bool = False) -> str:
    raw = os.getenv(name)
    if raw is None or raw == "":
        if required:
            raise RuntimeError(f"Переменная окружения {name} обязательна")
        return default or ""
    return raw


@dataclass(slots=True)
class Settings:
    bot_token: str
    channel_id: int
    moderator_chat_id: int
    admin_ids: list[int]
    database_url: str
    antiflood_seconds: int
    max_approved_per_user: int
    max_photos: int
    min_photos: int
    rules_url: str
    channel_delay_between_texts: float
    channel_delay_before_photos: float
    http_port: int
    data_dir: Path = field(default_factory=lambda: BASE_DIR / "data")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @classmethod
    def load(cls) -> "Settings":
        settings = cls(
            bot_token=_get_str("BOT_TOKEN", required=True),
            channel_id=_get_int("CHANNEL_ID", required=True),
            moderator_chat_id=_get_int("MODERATOR_CHAT_ID", required=True),
            admin_ids=_get_int_list("ADMIN_IDS"),
            database_url=_normalize_database_url(
                _get_str("DATABASE_URL", default="sqlite+aiosqlite:///data/bot.db")
            ),
            antiflood_seconds=_get_int("ANTIFLOOD_SECONDS", default=3),
            max_approved_per_user=_get_int("MAX_APPROVED_PER_USER", default=30),
            max_photos=_get_int("MAX_PHOTOS", default=10),
            min_photos=_get_int("MIN_PHOTOS", default=1),
            rules_url=_get_str("RULES_URL", default=""),
            channel_delay_between_texts=_get_float("CHANNEL_DELAY_BETWEEN_TEXTS", default=5.0),
            channel_delay_before_photos=_get_float("CHANNEL_DELAY_BEFORE_PHOTOS", default=15.0),
            http_port=_get_int("PORT", default=8080),
        )
        if settings.is_sqlite:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
        return settings


settings = Settings.load() if os.getenv("BOT_TOKEN") else None  # type: ignore[assignment]


def get_settings() -> Settings:
    """Ленивая загрузка настроек. Удобно для тестов и для отложенной инициализации."""
    global settings
    if settings is None:
        settings = Settings.load()
    return settings
