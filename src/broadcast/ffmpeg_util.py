"""定位并调用 ffmpeg，避免 PATH 未刷新导致找不到。"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def find_ffmpeg() -> str | None:
    env = os.getenv("FFMPEG_PATH")
    if env and Path(env).is_file():
        return env
    which = shutil.which("ffmpeg")
    if which:
        return which
    # winget 常见安装路径
    local = os.environ.get("LOCALAPPDATA", "")
    candidates: list[Path] = []
    if local:
        base = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if base.is_dir():
            candidates.extend(base.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"))
    candidates.extend(
        [
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        ]
    )
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def ffmpeg_available() -> bool:
    return find_ffmpeg() is not None


@lru_cache(maxsize=1)
def find_ffprobe() -> str | None:
    env = os.getenv("FFPROBE_PATH")
    if env and Path(env).is_file():
        return env
    which = shutil.which("ffprobe")
    if which:
        return which
    exe = find_ffmpeg()
    if exe:
        cand = Path(exe).with_name("ffprobe" + Path(exe).suffix)
        if cand.is_file():
            return str(cand)
    return None


def run_ffmpeg(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    exe = find_ffmpeg()
    if not exe:
        raise FileNotFoundError(
            "未找到 ffmpeg。请安装并加入 PATH，或设置环境变量 FFMPEG_PATH"
        )
    cmd = [exe, *args]
    return subprocess.run(cmd, **kwargs)
