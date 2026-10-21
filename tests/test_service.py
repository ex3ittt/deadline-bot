from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bot import humanize
from bot.reminders import parse_offsets, plan
from bot.scheduler import tick
from bot.service import Service
from bot.storage import Storage

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 21, 14, 30, tzinfo=MSK)  # Wednesday
CHAT = 42


@pytest.fixture
async def storage():
    s = await Storage.open(":memory:")
    yield s
    await s.close()


@pytest.fixture
def service(storage):
    return Service(storage)


class Outbox:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def __call__(self, chat_id, reply) -> None:
        self.messages.append((chat_id, reply.text))


async def test_add_confirms_with_date_and_reminders(service):
    reply = await service.add_from_text(CHAT, "лаба 3 по физике до 25.10 18:00", NOW)
    assert "<b>Лаба 3 по физике</b>" in reply.text
    assert "вс, 25 октября, 18:00 — через 4 дня" in reply.text
    assert "Напомню за 3 дня, за день и за 3 часа." in reply.text
    assert reply.buttons[0][0][1].startswith("del:")


async def test_add_close_deadline_gets_last_call_only(service):
    reply = await service.add_from_text(CHAT, "сдать долг в 15:00", NOW)
    assert "Напомню за 10 минут." in reply.text


async def test_add_without_date_explains(service):
    reply = await service.add_from_text(CHAT, "привет", NOW)
    assert "Не нашёл тут дату" in reply.text


async def test_titles_are_html_escaped(service):
    reply = await service.add_from_text(CHAT, "<script> завтра", NOW)
    assert "&lt;script&gt;" in reply.text


async def test_list_groups_by_week(service):
    for text in ["тест завтра в 9", "семинар в пятницу", "курсач через 2 недели", "сегодня в 20:00 созвон"]:
        await service.add_from_text(CHAT, text, NOW)
    reply = await service.list_upcoming(CHAT, NOW)
    assert reply.text.index("Сегодня") < reply.text.index("Завтра") < reply.text.index("На этой неделе") < reply.text.index("Позже")
    assert "1. <b>Созвон</b>" in reply.text
    assert len(reply.buttons) == 4


async def test_done_stops_reminders(service, storage):
    await service.add_from_text(CHAT, "тест завтра в 9", NOW)
    [d] = await storage.upcoming(CHAT)
    assert "Готово" in await service.done(CHAT, d.id)
    assert await storage.due_reminders(NOW + timedelta(days=2)) == []
    assert await service.done(CHAT, d.id) == "Это уже закрыто."


async def test_other_chats_cannot_touch_a_deadline(service, storage):
    await service.add_from_text(CHAT, "тест завтра в 9", NOW)
    [d] = await storage.upcoming(CHAT)
    assert await service.delete(CHAT + 1, d.id) == "Уже удалено."
    assert len(await storage.upcoming(CHAT)) == 1


async def test_scheduler_sends_due_and_only_once(service, storage):
    await service.add_from_text(CHAT, "тест завтра в 9", NOW)  # reminders: 22.10 06:00 (за 3 часа); others passed
    out = Outbox()
    assert await tick(storage, out, datetime(2026, 10, 22, 5, 59, tzinfo=MSK)) == 0
    assert await tick(storage, out, datetime(2026, 10, 22, 6, 0, tzinfo=MSK)) == 1
    assert await tick(storage, out, datetime(2026, 10, 22, 6, 1, tzinfo=MSK)) == 0
    chat, text = out.messages[0]
    assert chat == CHAT and "Тест" in text and "через 3 часа" in text


async def test_scheduler_collapses_missed_reminders(service, storage):
    await service.add_from_text(CHAT, "курсовая 30.10 12:00", NOW)  # три напоминания
    out = Outbox()
    # Bot was down for days; on wake-up only one message must go out.
    assert await tick(storage, out, datetime(2026, 10, 30, 10, 0, tzinfo=MSK)) == 1
    assert await tick(storage, out, datetime(2026, 10, 30, 11, 0, tzinfo=MSK)) == 0


async def test_failed_send_does_not_block_others(service, storage):
    await service.add_from_text(CHAT, "тест завтра в 9", NOW)
    await service.add_from_text(CHAT + 1, "зачёт завтра в 9", NOW)
    out = Outbox()

    async def flaky(chat_id, reply):
        if chat_id == CHAT:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        await out(chat_id, reply)

    assert await tick(storage, flaky, datetime(2026, 10, 22, 6, 0, tzinfo=MSK)) == 1
    assert out.messages[0][0] == CHAT + 1


async def test_snooze_adds_a_reminder(service, storage):
    await service.add_from_text(CHAT, "курсовая 30.10 12:00", NOW)
    [d] = await storage.upcoming(CHAT)
    assert await service.snooze(CHAT, d.id, NOW) == "Напомню через час."
    assert len(await storage.due_reminders(NOW + timedelta(hours=1))) == 1


async def test_custom_offsets_and_timezone(service, storage):
    assert "за 2 дня и за 30 минут" in await service.set_offsets(CHAT, "30м 2д")
    assert "Часовой пояс: Asia/Yekaterinburg" in await service.set_tz(CHAT, "Asia/Yekaterinburg")
    reply = await service.add_from_text(CHAT, "зачёт 30.10 10:00", NOW)
    assert "Напомню за 2 дня и за 30 минут." in reply.text
    [d] = await storage.upcoming(CHAT)
    assert d.due == datetime(2026, 10, 30, 5, 0, tzinfo=UTC)  # 10:00 по Екатеринбургу


async def test_bad_timezone(service):
    assert "Не знаю такого пояса" in await service.set_tz(CHAT, "Mars/Olympus")


def test_parse_offsets():
    assert parse_offsets("3д 1д 3ч") == (timedelta(days=3), timedelta(days=1), timedelta(hours=3))
    assert parse_offsets("1н, 2ч") == (timedelta(weeks=1), timedelta(hours=2))
    assert parse_offsets("потом") is None
    assert parse_offsets("0ч") is None


def test_plan_skips_past_moments():
    due = NOW + timedelta(hours=20)
    assert plan(due, NOW) == [due - timedelta(hours=3)]


@pytest.mark.parametrize(
    ("delta", "text"),
    [(timedelta(minutes=5), "через 5 минут"), (timedelta(hours=2), "через 2 часа"), (timedelta(days=21), "через 3 недели")],
)
def test_left(delta, text):
    assert humanize.left(NOW + delta, NOW) == text
