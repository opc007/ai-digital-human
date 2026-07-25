#!/usr/bin/env python3
"""音频 + 参考动作 → 口型片段（默认需 --mock 直到 MuseTalk 接入）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from broadcast.config import load_app_config, load_room_config
from broadcast.logging_utils import setup_logging
from broadcast.pipeline import run_lipsync_batch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", default="demo")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="用参考视频+音轨混流占位，不跑 MuseTalk",
    )
    args = parser.parse_args()
    log = setup_logging()

    app = load_app_config()
    room = load_room_config(args.room, app)

    # 未实现真实引擎时强制提示
    if not args.mock and (app.section("avatar").get("provider") == "musetalk"):
        log.warning("MuseTalk 尚未接入，自动使用 mock。显式传 --mock 可消除此提示。")
        args.mock = True

    try:
        paths = run_lipsync_batch(app, room, mock=args.mock)
    except FileNotFoundError as e:
        log.error("%s", e)
        log.error("请先放置动作视频，见 scripts/01_gen_actions.md")
        return 1
    except NotImplementedError as e:
        log.error("%s", e)
        return 1

    log.info("完成 %s 个 clip -> %s", len(paths), app.clips_dir / room.room_id)
    return 0 if paths else 1


if __name__ == "__main__":
    raise SystemExit(main())
