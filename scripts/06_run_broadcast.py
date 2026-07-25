#!/usr/bin/env python3
"""一键：TTS → 口型 → 播放列表 → 推流。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from broadcast.config import load_app_config, load_room_config
from broadcast.logging_utils import setup_logging
from broadcast.pipeline import build_room_playlist, run_lipsync_batch, run_tts_batch
from broadcast.stream import push_rtmp


def main() -> int:
    parser = argparse.ArgumentParser(description="一键播报推流")
    parser.add_argument("--room", default="demo")
    parser.add_argument("--mock", action="store_true", help="TTS+口型均 mock")
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--skip-lipsync", action="store_true")
    parser.add_argument("--skip-compose", action="store_true")
    parser.add_argument("--skip-push", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="推流只打印命令")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    log = setup_logging()

    app = load_app_config()
    room = load_room_config(args.room, app)

    if not args.skip_tts:
        log.info("=== TTS ===")
        run_tts_batch(app, room, mock=args.mock)
    else:
        log.info("跳过 TTS")

    if not args.skip_lipsync:
        log.info("=== LipSync ===")
        mock_ls = args.mock
        if not mock_ls:
            log.warning("真实 MuseTalk 未接入，口型使用 mock")
            mock_ls = True
        try:
            run_lipsync_batch(app, room, mock=mock_ls)
        except FileNotFoundError as e:
            log.error("%s", e)
            return 1
    else:
        log.info("跳过 LipSync")

    broadcast_mp4 = app.output_dir / room.room_id / "broadcast.mp4"
    if not args.skip_compose:
        log.info("=== Compose ===")
        try:
            _, single = build_room_playlist(app, room, make_single_file=True)
            if single:
                broadcast_mp4 = single
        except Exception as e:
            log.exception("合成失败: %s", e)
            return 1
    else:
        log.info("跳过 Compose")

    if args.skip_push:
        log.info("跳过推流，成片: %s", broadcast_mp4)
        return 0

    log.info("=== Push ===")
    rtmp = room.full_rtmp_url()
    if not room.stream.rtmp_key and not args.dry_run:
        log.error("未配置 ROOM_DEMO_RTMP_KEY")
        return 1
    if not broadcast_mp4.is_file() and not args.dry_run:
        log.error("成片不存在: %s", broadcast_mp4)
        return 1

    return int(
        push_rtmp(
            broadcast_mp4,
            rtmp or "rtmp://example.com/live/KEY",
            app.section("stream"),
            dry_run=args.dry_run,
            loop=args.loop,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
