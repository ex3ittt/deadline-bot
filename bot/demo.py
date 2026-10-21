"""`python -m bot.demo` — a conversation with the bot in the terminal, no Telegram needed."""

import asyncio
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.service import Service
from bot.storage import Storage

NOW = datetime(2026, 10, 21, 14, 30, tzinfo=ZoneInfo("Europe/Moscow"))


def plain(html: str) -> str:
    return re.sub(r"</?(b|i|code)>", "", html).replace("&lt;", "<").replace("&gt;", ">")


async def main() -> None:
    storage = await Storage.open(":memory:")
    service = Service(storage)
    for text in ["лаба 3 по физике до 25.10 18:00", "курсач через 2 недели", "в пятницу к 9 утра коллоквиум"]:
        print(f"> {text}")
        print(plain((await service.add_from_text(1, text, NOW)).text), end="\n\n")
    print("> /list")
    print(plain((await service.list_upcoming(1, NOW)).text))
    await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
