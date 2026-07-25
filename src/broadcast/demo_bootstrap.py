"""新手一键体验：确保有可播素材与默认配置。"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from .assets import DEFAULT_ACTIONS, avatar_root, ensure_avatar_dirs, list_assets, save_meta
from .avatar_meta import ActionMeta, AvatarMeta, load_avatar_meta
from .ffmpeg_util import find_ffmpeg

logger = logging.getLogger("broadcast.demo_bootstrap")


def _make_placeholder_mp4(path: Path, color: str = "0x224466", seconds: float = 3.0) -> bool:
    ff = find_ffmpeg()
    if not ff:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ff,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=960x540:d={seconds}",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-t",
        str(seconds),
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode == 0 and path.is_file()
    except Exception as e:
        logger.warning("placeholder ffmpeg failed: %s", e)
        return False


def ensure_demo_ready(avatar_id: str = "demo") -> dict[str, Any]:
    """
    保证新手能直接「仅预览开播」：
    - 有 idle 等动作（没有则生成纯色占位 mp4）
    - meta.json 完整
    """
    ensure_avatar_dirs(avatar_id)
    root = avatar_root(avatar_id)
    colors = {
        "idle": "0x224466",
        "wave": "0x336655",
        "nod": "0x554433",
        "thinking": "0x443366",
        "thanks_wave": "0x663344",
    }
    created: list[str] = []
    actions_meta: list[ActionMeta] = []

    try:
        meta = load_avatar_meta(root)
        name = meta.name or "演示形象"
        source = meta.source_image or "source/photo.jpg"
    except Exception:
        name = "演示形象"
        source = "source/photo.jpg"

    for d in DEFAULT_ACTIONS:
        rel = f"actions/{d['name']}.mp4"
        path = root / rel
        if not path.is_file():
            ok = _make_placeholder_mp4(path, colors.get(d["name"], "0x334455"))
            if ok:
                created.append(d["name"])
        actions_meta.append(
            ActionMeta(
                name=d["name"],
                file=rel,
                duration_ms=d["duration_ms"],
                category=d["category"],
            )
        )

    save_meta(
        AvatarMeta(id=avatar_id, name=name, source_image=source, actions=actions_meta),
        avatar_id,
    )
    assets = list_assets(avatar_id)
    return {
        "ok": assets.get("ready", False),
        "created_placeholders": created,
        "assets": assets,
        "message": (
            "已准备演示素材，可直接预览开播"
            if assets.get("ready")
            else "素材仍不完整，请安装 FFmpeg 后重试或手动上传动作"
        ),
        "is_placeholder": bool(created),
        "hint": "纯色占位仅用于跑通流程；正式直播请在素材中心换成真人动作视频。",
    }
