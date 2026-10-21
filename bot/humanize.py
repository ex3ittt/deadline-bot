"""Russian date phrasing: «пт, 25 октября, 18:00», «через 3 дня», «завтра»."""

from datetime import datetime, timedelta

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def plural(n: int, one: str, few: str, many: str) -> str:
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return one
    if 2 <= m10 <= 4 and not 12 <= m100 <= 14:
        return few
    return many


def when(due: datetime, now: datetime, with_time: bool = True) -> str:
    text = f"{WEEKDAYS_SHORT[due.weekday()]}, {due.day} {MONTHS_GEN[due.month - 1]}"
    if due.year != now.year:
        text += f" {due.year}"
    if with_time and (due.hour, due.minute) != (23, 59):
        text += f", {due:%H:%M}"
    return text


def left(due: datetime, now: datetime) -> str:
    delta = due - now
    if delta <= timedelta(0):
        return "срок прошёл"
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"через {minutes} {plural(minutes, 'минуту', 'минуты', 'минут')}"
    hours = minutes // 60
    if hours < 24:
        return f"через {hours} {plural(hours, 'час', 'часа', 'часов')}"
    days = (due.date() - now.date()).days
    if days == 1:
        return "завтра"
    if days == 2:
        return "послезавтра"
    if days < 14:
        return f"через {days} {plural(days, 'день', 'дня', 'дней')}"
    weeks = days // 7
    return f"через {weeks} {plural(weeks, 'неделю', 'недели', 'недель')}"


def offset(d: timedelta) -> str:
    minutes = int(d.total_seconds() // 60)
    if minutes % 1440 == 0:
        n = minutes // 1440
        return "за день" if n == 1 else f"за {n} {plural(n, 'день', 'дня', 'дней')}"
    if minutes % 60 == 0:
        n = minutes // 60
        return "за час" if n == 1 else f"за {n} {plural(n, 'час', 'часа', 'часов')}"
    return f"за {minutes} {plural(minutes, 'минуту', 'минуты', 'минут')}"
