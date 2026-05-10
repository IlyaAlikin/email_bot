from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "👋 Привет!\n\n"
        "Это бот для email-рассылок по базе клиентов в Google Sheets.\n"
        "Каждое письмо персонализируется через GPT.\n\n"
        "Команды:\n"
        "/new — новая рассылка\n"
        "/cancel — отменить текущий черновик\n"
        "/whoami — показать твой Telegram ID"
    )


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    user = message.from_user
    if user is None:
        return
    await message.answer(f"Твой Telegram ID: <code>{user.id}</code>\nUsername: @{user.username or '—'}")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Черновик отменён. Можно начинать заново через /new.")
