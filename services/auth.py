from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class AdminOnlyMiddleware(BaseMiddleware):
    """Drops messages and callbacks from users that are not in the admin whitelist."""

    def __init__(self, admin_ids: frozenset[int]) -> None:
        super().__init__()
        self._admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id not in self._admin_ids:
            if isinstance(event, Message):
                await event.answer(
                    "Доступ закрыт. Этот бот работает только для админов.\n"
                    f"Твой Telegram ID: <code>{user.id if user else 'неизвестен'}</code>"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("Доступ закрыт", show_alert=True)
            return None
        return await handler(event, data)
