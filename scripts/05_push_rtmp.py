#!/usr/bin/env python3
"""将 broadcast.mp4（或指定文件）推到 RTMP。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from broadcast.config import load_app_config, load_room_config, mask_secret
from broadcast.logging_utils import setup_logging
from broadcast.stream import push_rtmp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", default="demo")
    parser.add_argument(
        "--input",
        default="",
        help="默认 data/output/{room}/broadcast.mp4",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--loop", action="store_true", help="循环推流")
    args = parser.parse_args()
    log = setup_logging()

    app = load_app_config()
    room = load_room_config(args.room, app)
    input_path = Path(args.input) if args.input else app.output_dir / room.room_id / "broadcast.mp4"
    if not input_path.is_absolute():
        input_path = app.root / input_path

    rtmp = room.full_rtmp_url()
    if not room.stream.rtmp_key and not args.dry_run:
        log.error("未配置 RTMP key。请在 .env 设置 ROOM_DEMO_RTMP_KEY")
        return 1

    log.info("input=%s", input_path)
    log.info("rtmp=%s/***", (room.stream.rtmp_url or "")[:48])
    if room.stream.rtmp_key:
        log.info("key=%s", mask_secret(room.stream.rtmp_key))

    if not input_path.is_file() and not args.dry_run:
        log.error("输入文件不存在: %s （请先 04_compose_playlist）", input_path)
        return 1

    code = push_rtmp(
        input_path,
        rtmp or "rtmp://example.com/live/KEY",
        app.section("stream"),
        dry_run=args.dry_run,
        loop=args.loop,
    )
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
