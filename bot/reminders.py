import re
from datetime import datetime, timedelta

DEFAULT_OFFSETS = (timedelta(days=3), timedelta(days=1), timedelta(hours=3))
LAST_CALL = timedelta(minutes=10)


def plan(due: datetime, now: datetime, offsets: tuple[timedelta, ...] = DEFAULT_OFFSETS) -> list[datetime]:
    """Reminder moments that are still ahead. A deadline added too late for
    all of them still gets one nudge 10 minutes before, if there's time."""
    moments = sorted({due - o for o in offsets if due - o > now})
    if not moments and due - LAST_CALL > now:
        moments = [due - LAST_CALL]
    return moments


_OFFSET = re.compile(r"^(\d+)\s*(м|мин|ч|час|д|дн|день|дня|дней|н|нед)$")


def parse_offsets(text: str) -> tuple[timedelta, ...] | None:
    """'3д 1д 3ч' → (3 days, 1 day, 3 hours). None if any part is unreadable."""
    parts = text.lower().replace(",", " ").split()
    if not parts:
        return None
    out = []
    for p in parts:
        m = _OFFSET.match(p)
        if not m:
            return None
        n, unit = int(m[1]), m[2]
        if unit.startswith("м"):
            out.append(timedelta(minutes=n))
        elif unit.startswith("ч"):
            out.append(timedelta(hours=n))
        elif unit.startswith("н"):
            out.append(timedelta(weeks=n))
        else:
            out.append(timedelta(days=n))
    if any(o <= timedelta(0) or o > timedelta(days=60) for o in out) or len(out) > 6:
        return None
    return tuple(sorted(set(out), reverse=True))
