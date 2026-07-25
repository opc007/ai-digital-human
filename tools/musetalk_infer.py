#!/usr/bin/env python3
"""
MuseTalk 推理入口（可替换实现）。

默认行为：
1. 若设置 MUSETALK_ROOT 且存在 inference 入口，则转调；
2. 否则用 ffmpeg 做「参考视频 + 音频」混流。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_ffmpeg() -> str | None:
    env = os.getenv("FFMPEG_PATH")
    if env and Path(env).is_file():
        return env
    which = shutil.which("ffmpeg")
    if which:
        return which
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        base = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if base.is_dir():
            for c in base.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"):
                if c.is_file():
                    return str(c)
    for c in [
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
    ]:
        if c.is_file():
            return str(c)
    return None


def run_ffmpeg_mux(audio: Path, video: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = find_ffmpeg()
    if not ff:
        raise SystemExit("ffmpeg not found")
    cmd = [
        ff,
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-shortest",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or "ffmpeg failed")


def run_real_musetalk(audio: Path, video: Path, out: Path, model_path: str, device: str) -> bool:
    root = os.getenv("MUSETALK_ROOT")
    if not root:
        return False
    root_p = Path(root)
    candidates = [
        root_p / "inference.py",
        root_p / "scripts" / "inference.py",
        root_p / "infer.py",
    ]
    script = next((c for c in candidates if c.is_file()), None)
    if not script:
        print(f"[musetalk_infer] MUSETALK_ROOT 下未找到 inference: {root}", file=sys.stderr)
        return False

    alt_cmds = [
        [
            sys.executable,
            str(script),
            "--audio_path",
            str(audio),
            "--video_path",
            str(video),
            "--result_dir",
            str(out.parent),
            "--output_vid_name",
            out.stem,
        ],
        [
            sys.executable,
            str(script),
            "--audio",
            str(audio),
            "--video",
            str(video),
            "--outfile",
            str(out),
        ],
    ]
    for c in alt_cmds:
        print("[musetalk_infer] try:", " ".join(c), file=sys.stderr)
        proc = subprocess.run(c, cwd=str(root_p))
        if proc.returncode == 0 and out.is_file():
            return True
        guess = out.parent / f"{out.stem}.mp4"
        if proc.returncode == 0 and guess.is_file():
            if guess != out:
                guess.replace(out)
            return True
    return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", required=True)
    p.add_argument("--video", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--model-path", default="models/musetalk")
    p.add_argument("--device", default="cuda")
    args = p.parse_args()

    audio = Path(args.audio)
    video = Path(args.video)
    out = Path(args.out)

    if not audio.is_file() or not video.is_file():
        print("audio/video 不存在", file=sys.stderr)
        return 2

    if run_real_musetalk(audio, video, out, args.model_path, args.device):
        print("real musetalk ok", out)
        return 0

    print("[musetalk_infer] 使用 ffmpeg 混流占位", file=sys.stderr)
    run_ffmpeg_mux(audio, video, out)
    print("ffmpeg mux ok", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
