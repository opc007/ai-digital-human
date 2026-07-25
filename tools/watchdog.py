#!/usr/bin/env python3
"""
简单进程守护：子进程退出后按退避策略重启。

示例：
  python tools/watchdog.py -- python scripts/05_push_rtmp.py --room demo
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="子进程守护重启")
    parser.add_argument("--max-restarts", type=int, default=10)
    parser.add_argument("--base-delay", type=float, default=2.0)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="要守护的命令，前加 -- ",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    log = logging.getLogger("watchdog")

    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        log.error("请提供命令，例如: python tools/watchdog.py -- python scripts/05_push_rtmp.py")
        return 2

    restarts = 0
    while True:
        log.info("启动: %s", " ".join(cmd))
        proc = subprocess.run(cmd)
        code = proc.returncode
        if code == 0:
            log.info("进程正常退出")
            return 0
        restarts += 1
        if restarts > args.max_restarts:
            log.error("超过最大重启次数 %s，放弃", args.max_restarts)
            return code or 1
        delay = args.base_delay * (2 ** min(restarts - 1, 4))
        log.warning("退出 code=%s，%.1fs 后第 %s 次重启", code, delay, restarts)
        time.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(main())
