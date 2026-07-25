#!/usr/bin/env python3
"""clips → playlist.txt + broadcast.mp4。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from broadcast.config import load_app_config, load_room_config
from broadcast.logging_utils import setup_logging
from broadcast.pipeline import build_room_playlist


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", default="demo")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="只写 playlist.txt，不合成单文件",
    )
    args = parser.parse_args()
    log = setup_logging()

    app = load_app_config()
    room = load_room_config(args.room, app)

    try:
        list_path, single = build_room_playlist(
            app,
            room,
            make_single_file=not args.list_only,
        )
    except FileNotFoundError as e:
        log.error("%s", e)
        return 1
    except Exception as e:
        log.exception("合成失败: %s", e)
        return 1

    log.info("playlist: %s", list_path)
    if single:
        log.info("broadcast: %s", single)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
