#!/usr/bin/env python3
"""启动 FastAPI 控制台与 API。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    # 默认 8100：本机 ComfyUI 常占用 8000（Comfy Desktop）
    import os

    default_port = int(os.getenv("APP_PORT") or "8100")
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn

    print(f"数字人控制台: http://127.0.0.1:{args.port}")
    print(f"素材中心:     http://127.0.0.1:{args.port}/materials")
    print("（ComfyUI 若在 8000，请勿与本服务抢端口）")
    uvicorn.run(
        "api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(ROOT / "src"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
