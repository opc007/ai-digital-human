#!/usr/bin/env python3
"""无 HTTP：本地冒烟互动编排（mock + dry-run）。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from broadcast.config import load_app_config, load_room_config
from broadcast.logging_utils import setup_logging
from orchestrator.live import InputItem, LiveOrchestrator


def main() -> int:
    log = setup_logging()
    app = load_app_config()
    room = load_room_config("demo", app)

    events = []

    def on_event(ev):
        events.append(ev)
        log.info("event %s", ev)

    orch = LiveOrchestrator(app, room, mock=True, dry_run_stream=True, on_event=on_event)
    orch.start(mode="interactive")

    def wait_replies(n: int, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if sum(1 for e in events if e.get("type") == "ai_response") >= n:
                return True
            time.sleep(0.2)
        return False

    # 等开场白
    if not wait_replies(1):
        log.error("未收到开场 ai_response")
        orch.stop()
        return 1

    ok, mid = orch.enqueue(InputItem(text="主播好漂亮", user_key="u1"))
    log.info("enqueue %s %s", ok, mid)
    if not wait_replies(2):
        log.error("未收到第二条 ai_response")
        orch.stop()
        return 1

    orch.stop()
    log.info("smoke interactive OK, events=%s", len(events))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
