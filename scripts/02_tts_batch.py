#!/usr/bin/env python3
"""文案脚本 → 批量 TTS 音频。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from broadcast.config import load_app_config, load_room_config
from broadcast.logging_utils import setup_logging
from broadcast.pipeline import run_tts_batch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", default="demo")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="生成静音 wav，不调用云端 TTS",
    )
    args = parser.parse_args()
    log = setup_logging()

    app = load_app_config()
    room = load_room_config(args.room, app)
    if not room.script:
        log.error("房间脚本为空: %s", args.room)
        return 1

    paths = run_tts_batch(app, room, mock=args.mock)
    log.info("完成 %s/%s 条 -> %s", len(paths), len(room.script), app.audio_dir / room.room_id)
    return 0 if paths else 1


if __name__ == "__main__":
    raise SystemExit(main())
