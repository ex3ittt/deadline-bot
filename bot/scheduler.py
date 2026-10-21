import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from bot.service import Reply, reminder_text
from bot.storage import Storage

log = logging.getLogger(__name__)

Send = Callable[[int, Reply], Awaitable[None]]


async def tick(storage: Storage, send: Send, now: datetime) -> int:
    """Sends what's due. Returns how many messages went out."""
    due = await storage.due_reminders(now)
    # If several reminders for one deadline piled up (bot was down), only the
    # latest one matters — "за 3 дня" is pointless once "за 3 часа" is due.
    latest = {r.deadline.id: r for r in due}
    sent = 0
    for r in latest.values():
        tz, _ = await storage.settings(r.deadline.chat_id)
        try:
            await send(r.deadline.chat_id, reminder_text(r.deadline, now, ZoneInfo(tz)))
            sent += 1
        except Exception:
            # A user who blocked the bot must not stall everyone else's reminders.
            log.exception("failed to send reminder %s", r.reminder_id)
        await storage.skip_stale(r.deadline.id, now)
    return sent


async def run(storage: Storage, send: Send, every: float = 30) -> None:
    while True:
        try:
            await tick(storage, send, datetime.now(UTC))
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(every)
