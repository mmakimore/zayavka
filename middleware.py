from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import RATE_LIMIT_SECONDS


class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, min_delay: float = RATE_LIMIT_SECONDS):
        self.min_delay = max(0.0, float(min_delay))
        self.last_seen: dict[tuple[int, str], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, 'from_user', None)
        if not user or self.min_delay <= 0:
            return await handler(event, data)

        kind = event.__class__.__name__
        key = (user.id, kind)
        now = time.monotonic()
        prev = self.last_seen.get(key, 0.0)
        if now - prev < self.min_delay:
            if isinstance(event, CallbackQuery):
                await event.answer('Слишком быстро. Попробуй через секунду.', show_alert=False)
                return None
            if isinstance(event, Message):
                return None
        self.last_seen[key] = now
        return await handler(event, data)
