"""产品侧图生视频提示词（用户不可改）。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from .config import project_root

logger = logging.getLogger("broadcast.i2v_prompts")

_DEFAULT_IDLE = {
    "seconds": "4",
    "size": "9:16",
    "same_last_frame": False,
    "still_mix": 0,
    "prompt": (
        "[Subject action] Stay almost still, natural blink, very soft shallow breath only.\n"
        "[Secondary motion] Hair strands shift slightly.\n"
        "[Camera] Static locked-off shot, no zoom, no dolly, no pan. Preserve exact framing.\n"
        "[Identity] Maintain exact appearance from the reference image."
    ),
    "negative": (
        "camera move, zoom, dolly, pan, handheld, warp, face drift, blur, "
        "deep sigh, talking, waving, walking, watermark"
    ),
}


def _prompt_path() -> Path:
    return project_root() / "configs" / "i2v" / "idle_prompts.yaml"


def load_idle_prompt_config() -> dict[str, Any]:
    """返回 idle 配置：prompt / negative / seconds / size。"""
    override = (os.getenv("VIDEO_I2V_IDLE_PROMPT_OVERRIDE") or "").strip()
    cfg: dict[str, Any] = dict(_DEFAULT_IDLE)
    path = _prompt_path()
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            idle = data.get("idle") if isinstance(data, dict) else None
            if isinstance(idle, dict):
                cfg.update({k: v for k, v in idle.items() if v is not None})
        except Exception as e:
            logger.warning("load idle_prompts.yaml failed: %s", e)
    if override:
        cfg["prompt"] = override
    # 环境可覆盖时长/比例（不进普通 UI）
    if os.getenv("VIDEO_I2V_SECONDS"):
        cfg["seconds"] = str(os.getenv("VIDEO_I2V_SECONDS")).strip()
    if os.getenv("VIDEO_I2V_SIZE"):
        cfg["size"] = str(os.getenv("VIDEO_I2V_SIZE")).strip()
    return cfg


def build_idle_prompt() -> str:
    cfg = load_idle_prompt_config()
    prompt = str(cfg.get("prompt") or "").strip()
    negative = str(cfg.get("negative") or "").strip()
    if negative:
        prompt = f"{prompt}\n\n不要出现：{negative}"
    return prompt.strip()
