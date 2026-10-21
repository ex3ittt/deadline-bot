from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot.parse import parse_deadline

MSK = ZoneInfo("Europe/Moscow")
# Wednesday, 21 October 2026, 14:30
NOW = datetime(2026, 10, 21, 14, 30, tzinfo=MSK)


def at(*args):
    return datetime(*args, tzinfo=MSK)


@pytest.mark.parametrize(
    ("text", "title", "due"),
    [
        ("лаба 3 по физике до 25.10 в 18:00", "Лаба 3 по физике", at(2026, 10, 25, 18, 0)),
        ("Курсовая 15.12", "Курсовая", at(2026, 12, 15, 23, 59)),
        ("реферат до 10.01", "Реферат", at(2027, 1, 10, 23, 59)),
        ("эссе 05.11.2026 10:30", "Эссе", at(2026, 11, 5, 10, 30)),
        ("отчёт по практике до 3 ноября", "Отчёт по практике", at(2026, 11, 3, 23, 59)),
        ("курсач через 2 недели", "Курсач", at(2026, 11, 4, 23, 59)),
        ("через неделю коллоквиум", "Коллоквиум", at(2026, 10, 28, 23, 59)),
        ("позвонить старосте через 3 часа", "Позвонить старосте", at(2026, 10, 21, 17, 30)),
        ("через полчаса созвон", "Созвон", at(2026, 10, 21, 15, 0)),
        ("завтра в 9 тест по матану", "Тест по матану", at(2026, 10, 22, 9, 0)),
        ("послезавтра к 6 вечера презентация", "Презентация", at(2026, 10, 23, 18, 0)),
        ("в пятницу к 9 утра коллоквиум", "Коллоквиум", at(2026, 10, 23, 9, 0)),
        ("в среду семинар", "Семинар", at(2026, 10, 28, 23, 59)),
        ("сдать долг в 16:00", "Сдать долг", at(2026, 10, 21, 16, 0)),
        ("созвон в 10:00", "Созвон", at(2026, 10, 22, 10, 0)),
    ],
)
def test_parses(text, title, due):
    p = parse_deadline(text, NOW)
    assert p is not None, text
    assert (p.title, p.due) == (title, due)


@pytest.mark.parametrize("text", ["привет", "лаба по физике", "32.13 что-то", "до 25.10"])
def test_returns_none_without_date_or_title(text):
    assert parse_deadline(text, NOW) is None


def test_lab_number_is_not_a_time():
    p = parse_deadline("лаба 3 до пятницы", NOW)
    # "пятницы" is genitive; still Friday, and "3" stays in the title.
    assert p is not None and p.title == "Лаба 3"
    assert p.due == at(2026, 10, 23, 23, 59)


def test_reports_whether_time_was_given():
    assert parse_deadline("тест завтра в 9", NOW).had_time
    assert not parse_deadline("тест завтра", NOW).had_time
