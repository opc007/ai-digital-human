"""平台与算力模式预设加载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import project_root


def _load(name: str) -> dict[str, Any]:
    path = project_root() / "configs" / name
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def list_platforms() -> list[dict[str, Any]]:
    data = _load("platforms.yaml")
    platforms = data.get("platforms") or {}
    # 稳定顺序
    order = ["preview", "douyin", "kuaishou", "wechat", "xiaohongshu", "tiktok"]
    items = []
    for key in order:
        if key in platforms:
            items.append(platforms[key])
    for key, val in platforms.items():
        if key not in order:
            items.append(val)
    return items


def get_platform(platform_id: str) -> dict[str, Any] | None:
    data = _load("platforms.yaml")
    return (data.get("platforms") or {}).get(platform_id)


def list_runtime_modes() -> list[dict[str, Any]]:
    data = _load("runtime_modes.yaml")
    modes = data.get("modes") or {}
    order = ["cloud", "local", "hybrid"]
    items = []
    for key in order:
        if key in modes:
            items.append(modes[key])
    for key, val in modes.items():
        if key not in order:
            items.append(val)
    return items


def get_runtime_mode(mode_id: str) -> dict[str, Any] | None:
    data = _load("runtime_modes.yaml")
    return (data.get("modes") or {}).get(mode_id)
