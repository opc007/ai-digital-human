"""形象 / 动作素材管理。"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .avatar_meta import ActionMeta, AvatarMeta, load_avatar_meta
from .config import project_root
from .ffmpeg_util import find_ffmpeg

logger = logging.getLogger("broadcast.assets")

DEFAULT_ACTIONS = [
    {"name": "idle", "category": "idle", "label": "待机循环", "duration_ms": 3000},
    {"name": "wave", "category": "greeting", "label": "挥手打招呼", "duration_ms": 3000},
    {"name": "nod", "category": "emotion", "label": "点头", "duration_ms": 2500},
    {"name": "thinking", "category": "emotion", "label": "思考", "duration_ms": 3000},
    {"name": "thanks_wave", "category": "thanks", "label": "感谢挥手", "duration_ms": 3000},
]


def safe_avatar_id(avatar_id: str) -> str:
    """avatar_id 会拼进文件路径，必须防止 ../ 穿越。"""
    safe = re.sub(r"[^a-z0-9_\-]+", "_", (avatar_id or "").strip().lower())
    return safe[:48] or "demo"


def avatar_root(avatar_id: str = "demo") -> Path:
    return project_root() / "data" / "avatars" / safe_avatar_id(avatar_id)


def ensure_avatar_dirs(avatar_id: str = "demo") -> Path:
    root = avatar_root(avatar_id)
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "actions").mkdir(parents=True, exist_ok=True)
    (root / "generated").mkdir(parents=True, exist_ok=True)
    meta_path = root / "meta.json"
    # 直接写文件，避免 save_meta ↔ ensure_avatar_dirs 互相调用导致递归
    if not meta_path.is_file():
        meta = AvatarMeta(
            id=safe_avatar_id(avatar_id),
            name="演示形象",
            source_image="source/photo.jpg",
            actions=[
                ActionMeta(
                    name=a["name"],
                    file=f"actions/{a['name']}.mp4",
                    duration_ms=a["duration_ms"],
                    category=a["category"],
                )
                for a in DEFAULT_ACTIONS
            ],
        )
        meta_path.write_text(
            json.dumps(meta.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return root


def save_meta(meta: AvatarMeta, avatar_id: str = "demo") -> None:
    root = avatar_root(avatar_id)
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "actions").mkdir(parents=True, exist_ok=True)
    (root / "generated").mkdir(parents=True, exist_ok=True)
    path = root / "meta.json"
    path.write_text(
        json.dumps(meta.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_or_create_meta(avatar_id: str = "demo") -> AvatarMeta:
    ensure_avatar_dirs(avatar_id)
    try:
        return load_avatar_meta(avatar_root(avatar_id))
    except Exception:
        ensure_avatar_dirs(avatar_id)
        return load_avatar_meta(avatar_root(avatar_id))


def probe_duration_ms(video_path: Path) -> int | None:
    ff = find_ffmpeg()
    if not ff or not video_path.is_file():
        return None
    # ffprobe 通常与 ffmpeg 同目录
    probe = str(Path(ff).with_name("ffprobe.exe" if ff.lower().endswith(".exe") else "ffprobe"))
    if not Path(probe).is_file():
        probe = shutil.which("ffprobe") or ""
    if not probe:
        return None
    try:
        r = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        sec = float((r.stdout or "0").strip() or "0")
        if sec > 0:
            return int(sec * 1000)
    except Exception as e:
        logger.warning("ffprobe failed: %s", e)
    return None


def safe_action_name(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9_\-]+", "_", name)
    return name[:48] or "action"


def list_assets(avatar_id: str = "demo") -> dict[str, Any]:
    root = ensure_avatar_dirs(avatar_id)
    meta = get_or_create_meta(avatar_id)
    source_path = root / meta.source_image
    actions_out = []
    known = {a["name"]: a for a in DEFAULT_ACTIONS}

    # 合并 meta 与默认清单，缺的也列出
    by_name = {a.name: a for a in meta.actions}
    for d in DEFAULT_ACTIONS:
        a = by_name.get(d["name"]) or ActionMeta(
            name=d["name"],
            file=f"actions/{d['name']}.mp4",
            duration_ms=d["duration_ms"],
            category=d["category"],
        )
        fpath = root / a.file
        actions_out.append(
            {
                "name": a.name,
                "label": known.get(a.name, {}).get("label", a.name),
                "category": a.category,
                "file": a.file,
                "duration_ms": a.duration_ms,
                "exists": fpath.is_file(),
                "size": fpath.stat().st_size if fpath.is_file() else 0,
                "url": f"/media/avatars/{avatar_id}/{a.file}" if fpath.is_file() else None,
            }
        )
    # 额外自定义动作
    for a in meta.actions:
        if a.name in known:
            continue
        fpath = root / a.file
        actions_out.append(
            {
                "name": a.name,
                "label": a.name,
                "category": a.category,
                "file": a.file,
                "duration_ms": a.duration_ms,
                "exists": fpath.is_file(),
                "size": fpath.stat().st_size if fpath.is_file() else 0,
                "url": f"/media/avatars/{avatar_id}/{a.file}" if fpath.is_file() else None,
            }
        )

    ready = sum(1 for x in actions_out if x["exists"])
    return {
        "avatar_id": avatar_id,
        "name": meta.name,
        "source_image": meta.source_image,
        "source_exists": source_path.is_file(),
        "source_url": f"/media/avatars/{avatar_id}/{meta.source_image}"
        if source_path.is_file()
        else None,
        "actions": actions_out,
        "ready_count": ready,
        "total_count": len(actions_out),
        "ready": ready >= 3 and any(x["name"] == "idle" and x["exists"] for x in actions_out),
        "root": str(root),
    }


def save_source_image(data: bytes, filename: str, avatar_id: str = "demo") -> dict[str, Any]:
    root = ensure_avatar_dirs(avatar_id)
    ext = Path(filename).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    rel = f"source/photo{ext}"
    path = root / rel
    path.write_bytes(data)
    meta = get_or_create_meta(avatar_id)
    meta.source_image = rel
    save_meta(meta, avatar_id)
    return {
        "ok": True,
        "path": rel,
        "url": f"/media/avatars/{avatar_id}/{rel}",
    }


def save_action_video(
    data: bytes,
    action_name: str,
    avatar_id: str = "demo",
    category: str | None = None,
) -> dict[str, Any]:
    root = ensure_avatar_dirs(avatar_id)
    name = safe_action_name(action_name)
    rel = f"actions/{name}.mp4"
    path = root / rel
    path.write_bytes(data)
    dur = probe_duration_ms(path) or 3000

    meta = get_or_create_meta(avatar_id)
    found = False
    for a in meta.actions:
        if a.name == name:
            a.file = rel
            a.duration_ms = dur
            if category:
                a.category = category
            found = True
            break
    if not found:
        cat = category or next(
            (d["category"] for d in DEFAULT_ACTIONS if d["name"] == name), "emotion"
        )
        meta.actions.append(
            ActionMeta(name=name, file=rel, duration_ms=dur, category=cat)
        )
    save_meta(meta, avatar_id)
    return {
        "ok": True,
        "name": name,
        "path": rel,
        "duration_ms": dur,
        "url": f"/media/avatars/{avatar_id}/{rel}",
    }


def delete_action(action_name: str, avatar_id: str = "demo") -> dict[str, Any]:
    name = safe_action_name(action_name)
    root = ensure_avatar_dirs(avatar_id)
    meta = get_or_create_meta(avatar_id)
    meta.actions = [a for a in meta.actions if a.name != name]
    # 保留默认清单里的条目但删文件
    path = root / "actions" / f"{name}.mp4"
    if path.is_file():
        path.unlink()
    # 若是默认动作，写回空占位条目
    defaults = {d["name"]: d for d in DEFAULT_ACTIONS}
    if name in defaults and not any(a.name == name for a in meta.actions):
        d = defaults[name]
        meta.actions.append(
            ActionMeta(
                name=name,
                file=f"actions/{name}.mp4",
                duration_ms=d["duration_ms"],
                category=d["category"],
            )
        )
    save_meta(meta, avatar_id)
    return {"ok": True, "name": name}
