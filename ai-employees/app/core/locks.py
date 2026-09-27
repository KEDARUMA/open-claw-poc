"""Task単位の非同期排他制御を提供する。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator


class TaskLockRegistry:
    """同じTask IDの実行を直列化する。"""

    def __init__(self) -> None:
        """TaskごとのLock辞書を初期化する。"""
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def hold(self, task_id: str) -> AsyncIterator[None]:
        """指定TaskのLockを保持している間だけ処理を許可する。"""
        lock = self._locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            yield
