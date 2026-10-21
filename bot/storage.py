from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiosqlite

from bot.reminders import DEFAULT_OFFSETS

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id   INTEGER PRIMARY KEY,
    tz        TEXT NOT NULL DEFAULT 'Europe/Moscow',
    offsets   TEXT NOT NULL            -- minutes, comma-separated
);
CREATE TABLE IF NOT EXISTS deadlines (
    id        INTEGER PRIMARY KEY,
    chat_id   INTEGER NOT NULL,
    title     TEXT NOT NULL,
    due       TEXT NOT NULL,           -- ISO, UTC
    done      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY,
    deadline_id INTEGER NOT NULL REFERENCES deadlines(id) ON DELETE CASCADE,
    at          TEXT NOT NULL,         -- ISO, UTC
    sent        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_reminders_due ON reminders(sent, at);
CREATE INDEX IF NOT EXISTS ix_deadlines_chat ON deadlines(chat_id, done, due);
"""


@dataclass(frozen=True)
class Deadline:
    id: int
    chat_id: int
    title: str
    due: datetime
    done: bool


@dataclass(frozen=True)
class DueReminder:
    reminder_id: int
    deadline: Deadline


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _deadline(row) -> Deadline:
    return Deadline(id=row["id"], chat_id=row["chat_id"], title=row["title"], due=_dt(row["due"]), done=bool(row["done"]))


class Storage:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._db = conn

    @classmethod
    async def open(cls, path: str) -> "Storage":
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(SCHEMA)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self._db.close()

    # ── chat settings ────────────────────────────────────────────────────

    async def settings(self, chat_id: int) -> tuple[str, tuple[timedelta, ...]]:
        async with self._db.execute("SELECT tz, offsets FROM chats WHERE chat_id = ?", (chat_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return "Europe/Moscow", DEFAULT_OFFSETS
        return row["tz"], tuple(timedelta(minutes=int(m)) for m in row["offsets"].split(","))

    async def set_offsets(self, chat_id: int, offsets: tuple[timedelta, ...]) -> None:
        minutes = ",".join(str(int(o.total_seconds() // 60)) for o in offsets)
        await self._db.execute(
            "INSERT INTO chats (chat_id, offsets) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET offsets = excluded.offsets",
            (chat_id, minutes),
        )
        await self._db.commit()

    async def set_tz(self, chat_id: int, tz: str) -> None:
        _, offsets = await self.settings(chat_id)
        minutes = ",".join(str(int(o.total_seconds() // 60)) for o in offsets)
        await self._db.execute(
            "INSERT INTO chats (chat_id, tz, offsets) VALUES (?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET tz = excluded.tz",
            (chat_id, tz, minutes),
        )
        await self._db.commit()

    # ── deadlines ────────────────────────────────────────────────────────

    async def add(self, chat_id: int, title: str, due: datetime, remind_at: list[datetime]) -> Deadline:
        cur = await self._db.execute("INSERT INTO deadlines (chat_id, title, due) VALUES (?, ?, ?)", (chat_id, title, _iso(due)))
        deadline_id = cur.lastrowid
        await self._db.executemany("INSERT INTO reminders (deadline_id, at) VALUES (?, ?)", [(deadline_id, _iso(a)) for a in remind_at])
        await self._db.commit()
        return Deadline(id=deadline_id, chat_id=chat_id, title=title, due=due.astimezone(UTC), done=False)

    async def get(self, chat_id: int, deadline_id: int) -> Deadline | None:
        async with self._db.execute("SELECT * FROM deadlines WHERE id = ? AND chat_id = ?", (deadline_id, chat_id)) as cur:
            row = await cur.fetchone()
        return _deadline(row) if row else None

    async def upcoming(self, chat_id: int) -> list[Deadline]:
        async with self._db.execute("SELECT * FROM deadlines WHERE chat_id = ? AND done = 0 ORDER BY due", (chat_id,)) as cur:
            return [_deadline(r) for r in await cur.fetchall()]

    async def mark_done(self, chat_id: int, deadline_id: int) -> bool:
        cur = await self._db.execute("UPDATE deadlines SET done = 1 WHERE id = ? AND chat_id = ? AND done = 0", (deadline_id, chat_id))
        await self._db.commit()
        return cur.rowcount > 0

    async def delete(self, chat_id: int, deadline_id: int) -> bool:
        cur = await self._db.execute("DELETE FROM deadlines WHERE id = ? AND chat_id = ?", (deadline_id, chat_id))
        await self._db.commit()
        return cur.rowcount > 0

    async def snooze(self, deadline_id: int, at: datetime) -> None:
        await self._db.execute("INSERT INTO reminders (deadline_id, at) VALUES (?, ?)", (deadline_id, _iso(at)))
        await self._db.commit()

    # ── reminders ────────────────────────────────────────────────────────

    async def due_reminders(self, now: datetime) -> list[DueReminder]:
        query = """
            SELECT r.id AS reminder_id, d.* FROM reminders r
            JOIN deadlines d ON d.id = r.deadline_id
            WHERE r.sent = 0 AND r.at <= ? AND d.done = 0
            ORDER BY r.at
        """
        async with self._db.execute(query, (_iso(now),)) as cur:
            return [DueReminder(reminder_id=r["reminder_id"], deadline=_deadline(r)) for r in await cur.fetchall()]

    async def mark_sent(self, reminder_id: int) -> None:
        await self._db.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        await self._db.commit()

    async def skip_stale(self, deadline_id: int, now: datetime) -> None:
        """When the bot was offline, several reminders can come due at once —
        send only the latest and drop the rest."""
        await self._db.execute("UPDATE reminders SET sent = 1 WHERE deadline_id = ? AND sent = 0 AND at <= ?", (deadline_id, _iso(now)))
        await self._db.commit()
