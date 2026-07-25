#!/usr/bin/env python3
"""生成纯色占位动作视频，仅用于工程联调（非真实数字人）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = {
    "idle": "0x224466",
    "wave": "0x336655",
    "nod": "0x554433",
    "thinking": "0x443366",
    "thanks_wave": "0x663344",
}


def main() -> int:
    out_dir = ROOT / "data" / "avatars" / "demo" / "actions"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, color in ACTIONS.items():
        out = out_dir / f"{name}.mp4"
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=960x540:d=3",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-t",
            "3",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ]
        print(" ".join(cmd))
        subprocess.run(cmd, check=True)
        print("wrote", out)
    print("注意：这些是纯色占位，阶段 0 请换成 Wan2.2 真实动作。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
