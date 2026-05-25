"""Конвертер Telegram-HTML → (plain text, list[MessageEntity]) для Telethon.

Telethon-овый ``html.parse`` режет ``<tg-emoji>``, потому что HTML-парсер
по умолчанию не знает про этот тег. Нам нужно сохранять премиум-эмодзи как
``MessageEntityCustomEmoji``, поэтому пишем свой парсер.

Поддерживаются те же теги, которые aiogram кладёт в ``message.html_text``:
``b``, ``i``, ``u``, ``s``, ``code``, ``pre``, ``a href=...``,
``a href="tg://user?id=..."`` и ``tg-emoji emoji-id="..."``.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityCode,
    MessageEntityCustomEmoji,
    MessageEntityItalic,
    MessageEntityMentionName,
    MessageEntityPre,
    MessageEntityStrike,
    MessageEntityTextUrl,
    MessageEntityUnderline,
)


class _TgHtmlParser(HTMLParser):
    SINGLE_TAGS: dict[str, type] = {
        "b": MessageEntityBold,
        "strong": MessageEntityBold,
        "i": MessageEntityItalic,
        "em": MessageEntityItalic,
        "u": MessageEntityUnderline,
        "ins": MessageEntityUnderline,
        "s": MessageEntityStrike,
        "del": MessageEntityStrike,
        "strike": MessageEntityStrike,
        "code": MessageEntityCode,
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.entities: list[Any] = []
        # стек открытых тегов: (tag, start_offset_utf16, extra)
        self._open: list[tuple[str, int, dict[str, str]]] = []

    def _offset(self) -> int:
        # Telegram считает offset/length в UTF-16 code units.
        return sum(len(p.encode("utf-16-le")) // 2 for p in self.text_parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        adict: dict[str, str] = {k: (v or "") for k, v in attrs}
        if tag == "a":
            self._open.append((tag, self._offset(), {"url": adict.get("href", "")}))
        elif tag == "tg-emoji":
            emoji_id = adict.get("emoji-id") or adict.get("emoji_id") or ""
            self._open.append((tag, self._offset(), {"emoji_id": emoji_id}))
        elif tag == "pre":
            self._open.append((tag, self._offset(), {"lang": adict.get("language", "")}))
        elif tag in self.SINGLE_TAGS:
            self._open.append((tag, self._offset(), {}))
        # все остальные теги (br, p, div, span без атрибутов) игнорируем,
        # их контент попадает в data как обычный текст.

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for i in range(len(self._open) - 1, -1, -1):
            ot, start, extra = self._open[i]
            if ot != tag:
                continue
            end = self._offset()
            length = end - start
            if length > 0:
                self._emit_entity(tag, start, length, extra)
            del self._open[i]
            return

    def _emit_entity(self, tag: str, start: int, length: int, extra: dict[str, str]) -> None:
        if tag in self.SINGLE_TAGS:
            cls = self.SINGLE_TAGS[tag]
            self.entities.append(cls(offset=start, length=length))
        elif tag == "pre":
            lang = extra.get("lang") or ""
            self.entities.append(MessageEntityPre(offset=start, length=length, language=lang))
        elif tag == "a":
            url = extra.get("url", "")
            if url.startswith("tg://user?id="):
                try:
                    uid = int(url.split("=", 1)[1])
                    self.entities.append(MessageEntityMentionName(offset=start, length=length, user_id=uid))
                    return
                except (ValueError, IndexError):
                    pass
            if url:
                self.entities.append(MessageEntityTextUrl(offset=start, length=length, url=url))
        elif tag == "tg-emoji":
            raw = extra.get("emoji_id", "")
            try:
                doc_id = int(raw)
            except ValueError:
                return
            self.entities.append(
                MessageEntityCustomEmoji(offset=start, length=length, document_id=doc_id)
            )

    def handle_data(self, data: str) -> None:
        if data:
            self.text_parts.append(data)


def html_to_text_and_entities(html: str) -> tuple[str, list[Any]]:
    """Преобразует Telegram-HTML в (plain text, entities[]).

    entities — это список объектов ``MessageEntity*`` из Telethon, готовый
    к передаче в ``client.send_message(..., formatting_entities=entities)`` или
    ``client.send_file(..., formatting_entities=entities)``.
    """
    parser = _TgHtmlParser()
    parser.feed(html or "")
    parser.close()
    return ("".join(parser.text_parts), parser.entities)
