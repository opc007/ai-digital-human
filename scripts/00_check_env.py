#!/usr/bin/env python3
"""环境自检：Python / FFmpeg / GPU / 配置 / 密钥（脱敏）。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def warn(msg: str) -> None:
    print(f"  [!!]  {msg}")


def fail(msg: str) -> None:
    print(f"  [NG]  {msg}")


def check_python() -> bool:
    v = sys.version_info
    print("\n== Python ==")
    if v >= (3, 10):
        ok(f"{sys.version.split()[0]} @ {sys.executable}")
        return True
    fail(f"需要 Python >= 3.10，当前 {sys.version}")
    return False


def check_ffmpeg() -> bool:
    print("\n== FFmpeg ==")
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from broadcast.ffmpeg_util import find_ffmpeg

        path = find_ffmpeg()
    except Exception:
        path = shutil.which("ffmpeg")
    if not path:
        fail("未找到 ffmpeg。请 winget install Gyan.FFmpeg 或设置 FFMPEG_PATH")
        return False
    try:
        r = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            check=True,
        )
        line = (r.stdout or "").splitlines()[0]
        ok(f"{line} ({path})")
        return True
    except subprocess.CalledProcessError:
        fail("ffmpeg 无法运行")
        return False


def check_gpu() -> bool:
    print("\n== GPU (可选，口型/生成需要) ==")
    path = shutil.which("nvidia-smi")
    if not path:
        warn("未找到 nvidia-smi（无 NVIDIA 驱动或未装）。阶段 0 生成/口型需要 GPU。")
        return True  # 不阻断纯工程自检
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in (r.stdout or "").strip().splitlines():
            ok(line.strip())
        return True
    except subprocess.CalledProcessError:
        warn("nvidia-smi 执行失败")
        return True


def check_deps() -> bool:
    print("\n== Python 包 ==")
    required = ["yaml", "dotenv", "httpx", "pydantic"]
    good = True
    for name in required:
        mod = "yaml" if name == "yaml" else ("dotenv" if name == "dotenv" else name)
        try:
            __import__(mod if mod != "dotenv" else "dotenv")
            ok(name)
        except ImportError:
            fail(f"缺少 {name}，请 pip install -r requirements.txt")
            good = False
    return good


def check_dirs() -> bool:
    print("\n== 目录 ==")
    for rel in [
        "configs/default.yaml",
        "configs/rooms/demo.yaml",
        "data/avatars/demo/meta.json",
        "scripts",
        "src/broadcast",
    ]:
        p = ROOT / rel
        if p.exists():
            ok(rel)
        else:
            fail(f"缺失 {rel}")
            return False
    return True


def check_config() -> bool:
    print("\n== 配置加载 ==")
    try:
        from broadcast.config import load_app_config, load_room_config, mask_secret

        app = load_app_config()
        room = load_room_config("demo", app)
        ok(f"app.env={app.raw.get('app', {}).get('env')} data_dir={app.data_dir}")
        ok(f"room={room.room_id} script_lines={len(room.script)}")
        key = room.stream.rtmp_key
        if key:
            ok(f"rtmp_key 已配置 ({mask_secret(key)})")
        else:
            warn("未设置 ROOM_DEMO_RTMP_KEY（推流前需要）")
        api = os.getenv("MINIMAX_API_KEY")
        if api:
            ok(f"MINIMAX_API_KEY 已配置 ({mask_secret(api)})")
        else:
            warn("未设置 MINIMAX_API_KEY（可用 --mock TTS）")
        return True
    except Exception as e:
        fail(str(e))
        return False


def check_avatar_assets() -> bool:
    print("\n== Demo 素材 ==")
    try:
        from broadcast.avatar_meta import load_avatar_meta
        from broadcast.config import load_app_config, load_room_config

        app = load_app_config()
        room = load_room_config("demo", app)
        adir = room.avatar_path(app.root)
        meta = load_avatar_meta(adir)
        ok(f"meta actions={len(meta.actions)}")
        missing = []
        for a in meta.actions:
            p = adir / a.file
            if p.is_file():
                ok(f"视频 {a.name}: {a.file}")
            else:
                missing.append(a.file)
                warn(f"待放置视频: {a.file}")
        src = adir / meta.source_image
        if src.is_file():
            ok(f"原图 {meta.source_image}")
        else:
            warn(f"待放置原图: {meta.source_image}")
        if missing:
            warn("阶段 0：用 ComfyUI/Wan 生成动作后放入 actions/")
        return True
    except Exception as e:
        fail(str(e))
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="环境自检")
    parser.add_argument(
        "--config",
        action="store_true",
        help="额外做配置与素材检查",
    )
    args = parser.parse_args()

    print(f"项目根目录: {ROOT}")
    results = [
        check_python(),
        check_ffmpeg(),
        check_gpu(),
        check_deps(),
        check_dirs(),
    ]
    if args.config or True:
        results.append(check_config())
        results.append(check_avatar_assets())

    print("\n== 汇总 ==")
    if all(results):
        ok("关键检查通过（素材/密钥警告可稍后处理）")
        return 0
    fail("存在阻断项，请根据上方 NG 修复")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
