"""读取形象动作 meta.json。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class ActionMeta(BaseModel):
    name: str
    file: str
    duration_ms: int = 3000
    category: str = "emotion"


class AvatarMeta(BaseModel):
    model_config = {"extra": "ignore"}

    id: str
    name: str = ""
    source_image: str = "source/photo.jpg"
    actions: list[ActionMeta] = Field(default_factory=list)

    def action_path(self, root: Path, name: str) -> Path | None:
        for a in self.actions:
            if a.name == name:
                return root / a.file
        return None

    def default_action_path(self, root: Path, preferred: str = "idle") -> Path | None:
        p = self.action_path(root, preferred)
        if p and p.is_file():
            return p
        for a in self.actions:
            cand = root / a.file
            if cand.is_file():
                return cand
        return None


def load_avatar_meta(avatar_dir: Path) -> AvatarMeta:
    meta_path = avatar_dir / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"缺少 meta.json: {meta_path}")
    with meta_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return AvatarMeta.model_validate(data)
