"""Everything the bot says, without Telegram. Handlers only translate
updates into these calls and `Reply` into aiogram objects — so the whole
conversation is testable with plain pytest."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot import humanize
from bot.parse import parse_deadline
from bot.reminders import parse_offsets, plan
from bot.storage import Deadline, Storage

Button = tuple[str, str]  # (label, callback data)

HELP = (
    "Пиши дедлайны как пишешь другу — я пойму дату и напомню заранее.\n\n"
    "<code>лаба 3 по физике до 25.10 18:00</code>\n"
    "<code>курсач через 2 недели</code>\n"
    "<code>в пятницу к 9 утра коллоквиум</code>\n\n"
    "/list — что впереди\n"
    "/remind 3д 1д 3ч — когда напоминать\n"
    "/tz Europe/Samara — часовой пояс, если не Москва"
)


@dataclass
class Reply:
    text: str
    buttons: list[list[Button]] = field(default_factory=list)


class Service:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def _tz(self, chat_id: int) -> ZoneInfo:
        tz, _ = await self.storage.settings(chat_id)
        return ZoneInfo(tz)

    async def add_from_text(self, chat_id: int, text: str, now: datetime) -> Reply:
        tz, offsets = await self.storage.settings(chat_id)
        local_now = now.astimezone(ZoneInfo(tz))
        parsed = parse_deadline(text, local_now)
        if parsed is None:
            return Reply("Не нашёл тут дату. Попробуй так: <code>реферат до 3 ноября</code> или <code>тест завтра в 9</code>.")
        if parsed.due <= local_now:
            return Reply(f"{humanize.when(parsed.due, local_now)} уже прошло — проверь дату.")

        moments = plan(parsed.due, local_now, offsets)
        d = await self.storage.add(chat_id, parsed.title, parsed.due, moments)
        if moments:
            labels = [humanize.offset(parsed.due - m) for m in moments]
            remind = "Напомню " + _join(labels) + "."
        else:
            remind = "Напоминать уже некогда — удачи!"
        text = (
            f"Записал: <b>{escape(d.title)}</b>\n"
            f"{humanize.when(parsed.due, local_now)} — {humanize.left(parsed.due, local_now)}.\n{remind}"
        )
        return Reply(text, [[("Удалить", f"del:{d.id}")]])

    async def list_upcoming(self, chat_id: int, now: datetime) -> Reply:
        tz = await self._tz(chat_id)
        local_now = now.astimezone(tz)
        items = await self.storage.upcoming(chat_id)
        if not items:
            return Reply("Дедлайнов нет. Можно выдохнуть.")

        sections: dict[str, list[str]] = {}
        buttons: list[list[Button]] = []
        for n, d in enumerate(items, 1):
            due = d.due.astimezone(tz)
            sections.setdefault(_bucket(due, local_now), []).append(
                f"{n}. <b>{escape(d.title)}</b> — {humanize.when(due, local_now)}, {humanize.left(due, local_now)}"
            )
            buttons.append([(f"{n}. Сделано", f"done:{d.id}")])
        text = "\n\n".join(f"<i>{name}</i>\n" + "\n".join(lines) for name, lines in sections.items())
        return Reply(text, buttons)

    async def done(self, chat_id: int, deadline_id: int) -> str:
        d = await self.storage.get(chat_id, deadline_id)
        if d is None or not await self.storage.mark_done(chat_id, deadline_id):
            return "Это уже закрыто."
        return f"Готово: {escape(d.title)}. Напоминаний больше не будет."

    async def delete(self, chat_id: int, deadline_id: int) -> str:
        return "Удалил." if await self.storage.delete(chat_id, deadline_id) else "Уже удалено."

    async def snooze(self, chat_id: int, deadline_id: int, now: datetime) -> str:
        d = await self.storage.get(chat_id, deadline_id)
        if d is None or d.done:
            return "Это уже закрыто."
        at = now + timedelta(hours=1)
        if at >= d.due:
            return "До срока меньше часа — откладывать некуда."
        await self.storage.snooze(deadline_id, at)
        return "Напомню через час."

    async def set_offsets(self, chat_id: int, text: str) -> str:
        offsets = parse_offsets(text)
        if offsets is None:
            _, current = await self.storage.settings(chat_id)
            return (
                "Сейчас напоминаю " + _join([humanize.offset(o) for o in current]) + ".\n"
                "Поменять: <code>/remind 2д 5ч 30м</code> (м — минуты, ч — часы, д — дни, н — недели)."
            )
        await self.storage.set_offsets(chat_id, offsets)
        return "Теперь напоминаю " + _join([humanize.offset(o) for o in offsets]) + ". Касается новых дедлайнов."

    async def set_tz(self, chat_id: int, name: str) -> str:
        name = name.strip()
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return "Не знаю такого пояса. Примеры: <code>Europe/Moscow</code>, <code>Asia/Yekaterinburg</code>."
        await self.storage.set_tz(chat_id, name)
        return f"Часовой пояс: {name}."


def reminder_text(d: Deadline, now: datetime, tz: ZoneInfo) -> Reply:
    due = d.due.astimezone(tz)
    local_now = now.astimezone(tz)
    text = f"Напоминаю: <b>{escape(d.title)}</b>\nСрок — {humanize.when(due, local_now)}, {humanize.left(due, local_now)}."
    return Reply(text, [[("Сделано", f"done:{d.id}"), ("Через час", f"snooze:{d.id}")]])


def _bucket(due: datetime, now: datetime) -> str:
    days = (due.date() - now.date()).days
    if days <= 0:
        return "Сегодня"
    if days == 1:
        return "Завтра"
    week_end = now.date() + timedelta(days=6 - now.weekday())
    if due.date() <= week_end:
        return "На этой неделе"
    if due.date() <= week_end + timedelta(days=7):
        return "На следующей"
    return "Позже"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " и " + items[-1]
