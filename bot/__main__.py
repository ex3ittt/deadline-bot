"""Entry point: `python -m bot`. Needs BOT_TOKEN in the environment."""

import asyncio
import logging
import os
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import scheduler
from bot.service import HELP, Reply, Service
from bot.storage import Storage


def markup(reply: Reply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=data) for label, data in row] for row in reply.buttons]
    )


def build_router(service: Service) -> Router:
    router = Router()
    now = lambda: datetime.now(UTC)  # noqa: E731

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def start(message: Message) -> None:
        await message.answer(HELP)

    @router.message(Command("list"))
    async def list_(message: Message) -> None:
        reply = await service.list_upcoming(message.chat.id, now())
        await message.answer(reply.text, reply_markup=markup(reply))

    @router.message(Command("remind"))
    async def remind(message: Message, command: CommandObject) -> None:
        await message.answer(await service.set_offsets(message.chat.id, command.args or ""))

    @router.message(Command("tz"))
    async def tz(message: Message, command: CommandObject) -> None:
        await message.answer(await service.set_tz(message.chat.id, command.args or ""))

    @router.message(F.text & ~F.text.startswith("/"))
    async def add(message: Message) -> None:
        reply = await service.add_from_text(message.chat.id, message.text, now())
        await message.answer(reply.text, reply_markup=markup(reply))

    @router.callback_query(F.data.regexp(r"^(done|del|snooze):\d+$"))
    async def button(query: CallbackQuery) -> None:
        action, raw_id = query.data.split(":")
        chat_id = query.message.chat.id
        if action == "done":
            text = await service.done(chat_id, int(raw_id))
        elif action == "del":
            text = await service.delete(chat_id, int(raw_id))
        else:
            text = await service.snooze(chat_id, int(raw_id), now())
        await query.answer(text.replace("<b>", "").replace("</b>", ""))
        if action in ("done", "del"):
            await query.message.edit_reply_markup(reply_markup=None)

    return router


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Set BOT_TOKEN (get one from @BotFather).")

    storage = await Storage.open(os.environ.get("DB_PATH", "deadlines.db"))
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(build_router(Service(storage)))

    async def send(chat_id: int, reply: Reply) -> None:
        await bot.send_message(chat_id, reply.text, reply_markup=markup(reply))

    ticker = asyncio.create_task(scheduler.run(storage, send))
    try:
        await dp.start_polling(bot)
    finally:
        ticker.cancel()
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
