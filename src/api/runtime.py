"""进程内直播会话注册表。"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from orchestrator.live import LiveOrchestrator

logger = logging.getLogger("api.runtime")


class RoomHub:
    def __init__(self) -> None:
        self.orchestrators: dict[str, LiveOrchestrator] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def get(self, room_id: str) -> LiveOrchestrator | None:
        return self.orchestrators.get(room_id)

    def register(self, room_id: str, orch: LiveOrchestrator) -> None:
        with self._lock:
            old = self.orchestrators.pop(room_id, None)
        if old:
            try:
                old.stop()
            except Exception:
                logger.exception("stop old room failed: %s", room_id)
        with self._lock:
            self.orchestrators[room_id] = orch

    def unregister(self, room_id: str) -> None:
        with self._lock:
            orch = self.orchestrators.pop(room_id, None)
        if orch:
            try:
                orch.stop()
            except Exception:
                logger.exception("stop room failed: %s", room_id)

    def subscribe(self, room_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subscribers.setdefault(room_id, set()).add(q)
        return q

    def unsubscribe(self, room_id: str, q: asyncio.Queue) -> None:
        subs = self.subscribers.get(room_id)
        if subs and q in subs:
            subs.discard(q)

    def broadcast(self, room_id: str, event: dict[str, Any]) -> None:
        subs = list(self.subscribers.get(room_id, set()))
        if not subs:
            return

        def _put_all() -> None:
            for q in subs:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(_put_all)
        else:
            _put_all()


hub = RoomHub()
