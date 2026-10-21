"""Pulls a deadline out of a free-form Russian message.

    "лаба 3 по физике до 25.10 в 18:00"   → «Лаба 3 по физике», 25 Oct 18:00
    "курсач через 2 недели"               → «Курсач», now + 14 days, 23:59
    "в пятницу к 9 утра коллоквиум"       → «Коллоквиум», next Friday 09:00

The date and time are found by patterns and cut out; whatever is left is the
title. With no time given, a deadline means "by the end of that day" — 23:59.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
WEEKDAYS = {"понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4, "суббот": 5, "воскресенье": 6}
NUMBERS = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "пол": 0.5}
END_OF_DAY = time(23, 59)

_PREP = r"(?:(?:до|к|ко|в|во|на)\s+)?"

RELATIVE = re.compile(
    _PREP + r"через\s+(?P<n>\d+|" + "|".join(NUMBERS) + r")?\s*(?P<unit>минут\w*|час\w*|дн\w*|день|недел\w*|месяц\w*)",
)
NUMERIC_DATE = re.compile(_PREP + r"(?<![\d:])(?P<d>\d{1,2})[./](?P<m>\d{1,2})(?:[./](?P<y>\d{4}|\d{2}))?(?![\d:])")
WORD_DATE = re.compile(_PREP + r"(?<!\d)(?P<d>\d{1,2})\s+(?P<m>" + "|".join(MONTHS) + r")(?:\s+(?P<y>\d{4}))?")
DAY_WORD = re.compile(_PREP + r"\b(?P<w>сегодня|послезавтра|завтра)\b")
WEEKDAY = re.compile(_PREP + r"\b(?P<w>понедельник|вторник|сред[уаы]|четверг|пятниц[уаы]|суббот[уаы]|воскресенье)\b")
CLOCK = re.compile(_PREP + r"(?<![\d.])(?P<h>\d{1,2}):(?P<min>\d{2})(?!\d)")
HOUR = re.compile(r"\b(?:в|к|до)\s+(?P<h>\d{1,2})(?:\s*(?:ч|час\w*))?(?:\s+(?P<part>утра|дня|вечера|ночи))?(?![\d.:/])")


@dataclass(frozen=True)
class Parsed:
    title: str
    due: datetime
    had_time: bool


def parse_deadline(text: str, now: datetime) -> Parsed | None:
    """`now` must be timezone-aware; the result is in the same timezone."""
    rest = " " + text.strip() + " "
    low = rest.lower()

    day: date | None = None
    at: time | None = None
    relative: timedelta | None = None

    def cut(m: re.Match[str]) -> None:
        nonlocal rest, low
        s, e = m.span()
        rest = rest[:s] + " " + rest[e:]
        low = low[:s] + " " + low[e:]

    if m := RELATIVE.search(low):
        relative = _relative(m)
        cut(m)

    if relative is None:
        if m := NUMERIC_DATE.search(low):
            day = _date(now.date(), int(m["d"]), int(m["m"]), m["y"])
            if day:
                cut(m)
        if day is None and (m := WORD_DATE.search(low)):
            day = _date(now.date(), int(m["d"]), MONTHS[m["m"]], m["y"])
            if day:
                cut(m)
        if day is None and (m := DAY_WORD.search(low)):
            day = now.date() + timedelta(days={"сегодня": 0, "завтра": 1, "послезавтра": 2}[m["w"]])
            cut(m)
        if day is None and (m := WEEKDAY.search(low)):
            target = next(v for k, v in WEEKDAYS.items() if m["w"].startswith(k))
            # "в пятницу", said on a Friday, means next week's.
            ahead = (target - now.weekday()) % 7 or 7
            day = now.date() + timedelta(days=ahead)
            cut(m)

    if m := CLOCK.search(low):
        h, mi = int(m["h"]), int(m["min"])
        if h < 24 and mi < 60:
            at = time(h, mi)
            cut(m)
    if at is None and (m := HOUR.search(low)):
        h = int(m["h"])
        if m["part"] in ("дня", "вечера") and h < 12:
            h += 12
        if m["part"] == "ночи" and h == 12:
            h = 0
        if h < 24:
            at = time(h)
            cut(m)

    if relative is not None:
        due = now + relative
        if at is not None:
            due = due.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        elif relative >= timedelta(days=1):
            due = due.replace(hour=END_OF_DAY.hour, minute=END_OF_DAY.minute, second=0, microsecond=0)
        else:
            due = due.replace(second=0, microsecond=0)
    elif day is not None:
        due = datetime.combine(day, at or END_OF_DAY, tzinfo=now.tzinfo)
    elif at is not None:
        # Just a time: today if it's still ahead, otherwise tomorrow.
        due = datetime.combine(now.date(), at, tzinfo=now.tzinfo)
        if due <= now:
            due += timedelta(days=1)
    else:
        return None

    title = _clean_title(rest)
    if not title:
        return None
    return Parsed(title=title, due=due, had_time=at is not None or (relative is not None and relative < timedelta(days=1)))


def _relative(m: re.Match[str]) -> timedelta:
    raw = m["n"]
    n = 1.0 if raw is None else float(NUMBERS.get(raw, raw))
    unit = m["unit"]
    if unit.startswith("минут"):
        return timedelta(minutes=n)
    if unit.startswith("час"):
        return timedelta(hours=n)
    if unit.startswith("недел"):
        return timedelta(weeks=n)
    if unit.startswith("месяц"):
        return timedelta(days=30 * n)
    return timedelta(days=n)


def _date(today: date, d: int, m: int, y: str | None) -> date | None:
    year = today.year if y is None else int(y) + (2000 if len(y) == 2 else 0)
    try:
        result = date(year, m, d)
    except ValueError:
        return None
    # "до 10.01" written in October means next January.
    if y is None and result < today:
        try:
            result = date(year + 1, m, d)
        except ValueError:
            return None
    return result


_EDGE = re.compile(r"^[\s,.;:—–-]+|[\s,.;:—–-]+$")
_DANGLING = re.compile(r"(?:^|\s)(?:до|к|ко|в|во|на|по|сдать до)$|^(?:до|к|в|на)\s", re.IGNORECASE)


def _clean_title(raw: str) -> str:
    title = re.sub(r"\s+", " ", raw)
    for _ in range(3):
        title = _EDGE.sub("", title)
        title = _DANGLING.sub(" ", title).strip()
    return title[:1].upper() + title[1:] if title else ""
