"""角色 / 造型（对齐 Vidu 心智：先建人、再挂图、再生微动）。

目录约定：
  data/avatars/{character_id}/
    meta.json
    source/ + actions/     ← 默认造型（default）
    looks/{look_id}/       ← 额外造型
      source/
      actions/
      meta.json
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .assets import (
    DEFAULT_ACTIONS,
    delete_action,
    ensure_avatar_dirs,
    get_or_create_meta,
    list_assets,
    save_action_video,
    save_meta,
    save_source_image,
    safe_avatar_id,
    avatar_root,
)
from .config import project_root, slugify

logger = logging.getLogger("broadcast.characters")


def _unique_character_id(name: str) -> str:
    """中文名无法变成 ascii slug 时，用短 id；保证目录唯一。"""
    base = safe_avatar_id(slugify(name) or name)
    # 纯下划线/横线、或以下划线开头（中文被洗成 _xxx）视为无效
    if (
        base in ("", "demo", "item", "_")
        or set(base) <= {"_", "-"}
        or base.startswith("_")
        or base.startswith("-")
    ):
        base = f"c{uuid.uuid4().hex[:8]}"
    root_base = project_root() / "data" / "avatars"
    cand = base
    n = 2
    while (root_base / cand).exists():
        cand = f"{base}_{n}"
        n += 1
        if n > 50:
            cand = f"c{uuid.uuid4().hex[:10]}"
            break
    return cand


def look_root(character_id: str, look_id: str = "default") -> Path:
    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    if lid == "default":
        return avatar_root(cid)
    return avatar_root(cid) / "looks" / lid


def ensure_look_dirs(character_id: str, look_id: str = "default") -> Path:
    root = look_root(character_id, look_id)
    (root / "source").mkdir(parents=True, exist_ok=True)
    (root / "actions").mkdir(parents=True, exist_ok=True)
    meta_path = root / "meta.json"
    if meta_path.is_file():
        return root
    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    if lid == "default":
        ensure_avatar_dirs(cid)
        return root
    payload = {
        "id": f"{cid}_{lid}",
        "name": lid,
        "source_image": "source/photo.jpg",
        "actions": [
            {
                "name": a["name"],
                "file": f"actions/{a['name']}.mp4",
                "duration_ms": a["duration_ms"],
                "category": a["category"],
            }
            for a in DEFAULT_ACTIONS
        ],
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def _read_char_meta(character_id: str) -> dict[str, Any]:
    root = ensure_avatar_dirs(character_id)
    path = root / "meta.json"
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if "looks" not in data or not isinstance(data["looks"], list):
        data["looks"] = [{"id": "default", "name": "默认造型"}]
    data.setdefault("id", safe_avatar_id(character_id))
    data.setdefault("name", character_id)
    data.setdefault("default_look", "default")
    return data


def _write_char_meta(character_id: str, data: dict[str, Any]) -> None:
    root = ensure_avatar_dirs(character_id)
    # 保留 actions / source_image 给默认造型用
    meta = get_or_create_meta(character_id)
    payload = {
        **meta.model_dump(),
        "name": data.get("name") or meta.name,
        "looks": data.get("looks") or [{"id": "default", "name": "默认造型"}],
        "default_look": data.get("default_look") or "default",
    }
    (root / "meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_character(name: str) -> dict[str, Any]:
    name = (name or "").strip() or "未命名角色"
    cid = _unique_character_id(name)
    ensure_avatar_dirs(cid)
    ensure_look_dirs(cid, "default")
    data = _read_char_meta(cid)
    data["id"] = cid
    data["name"] = name
    data["looks"] = [{"id": "default", "name": "默认造型"}]
    data["default_look"] = "default"
    _write_char_meta(cid, data)

    # 同步 DB
    try:
        from db.session import get_session
        from db.models import Avatar

        with get_session() as db:
            db.add(
                Avatar(
                    name=name,
                    root_path=f"data/avatars/{cid}",
                    status=1,
                )
            )
            db.commit()
    except Exception as e:
        logger.warning("DB avatar insert skipped: %s", e)

    return summarize_character(cid)


def list_characters() -> list[dict[str, Any]]:
    base = project_root() / "data" / "avatars"
    base.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    for p in sorted(base.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        if not (p / "meta.json").is_file() and not (p / "source").is_dir():
            continue
        try:
            out.append(summarize_character(p.name))
        except Exception as e:
            logger.warning("skip character %s: %s", p.name, e)
    if not out:
        # 确保至少有 demo
        ensure_avatar_dirs("demo")
        out.append(summarize_character("demo"))
    return out


def summarize_character(character_id: str) -> dict[str, Any]:
    cid = safe_avatar_id(character_id)
    data = _read_char_meta(cid)
    looks_out = []
    for lk in data.get("looks") or []:
        lid = str(lk.get("id") or "default")
        assets = list_look_assets(cid, lid)
        looks_out.append(
            {
                "id": lid,
                "name": lk.get("name") or lid,
                "source_url": assets.get("source_url"),
                "source_exists": assets.get("source_exists"),
                "ready": assets.get("ready"),
                "idle_url": next(
                    (
                        a.get("url")
                        for a in (assets.get("actions") or [])
                        if a.get("name") == "idle" and a.get("exists")
                    ),
                    None,
                ),
            }
        )
    default_look = data.get("default_look") or "default"
    default_assets = list_look_assets(cid, default_look)
    any_ready = any(bool(x.get("ready")) for x in looks_out)
    # 展示优先：已就绪造型 > 默认造型
    show = next((x for x in looks_out if x.get("ready")), None) or next(
        (x for x in looks_out if x.get("id") == default_look), None
    ) or (looks_out[0] if looks_out else None)
    return {
        "id": cid,
        "name": data.get("name") or cid,
        "default_look": default_look,
        "looks": looks_out,
        "ready": any_ready,
        "source_url": (show or {}).get("source_url") or default_assets.get("source_url"),
        "idle_url": (show or {}).get("idle_url")
        or next(
            (
                a.get("url")
                for a in (default_assets.get("actions") or [])
                if a.get("name") == "idle" and a.get("exists")
            ),
            None,
        ),
        "portrait_url": (show or {}).get("source_url") or default_assets.get("source_url"),
        "root": str(avatar_root(cid)),
    }


def list_look_assets(character_id: str, look_id: str = "default") -> dict[str, Any]:
    """列出某造型素材；default 复用现有 list_assets。"""
    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    if lid == "default":
        return list_assets(cid)

    root = ensure_look_dirs(cid, lid)
    meta_path = root / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    except Exception:
        meta = {}
    source_rel = meta.get("source_image") or "source/photo.jpg"
    source_path = root / source_rel
    # 找任意 source 图
    if not source_path.is_file():
        src_dir = root / "source"
        if src_dir.is_dir():
            for p in sorted(src_dir.iterdir()):
                if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.is_file():
                    source_path = p
                    source_rel = f"source/{p.name}"
                    break

    actions_out = []
    for d in DEFAULT_ACTIONS:
        rel = f"actions/{d['name']}.mp4"
        fpath = root / rel
        actions_out.append(
            {
                "name": d["name"],
                "label": d["label"],
                "category": d["category"],
                "file": rel,
                "duration_ms": d["duration_ms"],
                "exists": fpath.is_file(),
                "size": fpath.stat().st_size if fpath.is_file() else 0,
                "url": f"/media/avatars/{cid}/looks/{lid}/{rel}" if fpath.is_file() else None,
            }
        )
    ready = sum(1 for x in actions_out if x["exists"])
    return {
        "avatar_id": cid,
        "look_id": lid,
        "name": meta.get("name") or lid,
        "source_image": source_rel,
        "source_exists": source_path.is_file(),
        "source_url": f"/media/avatars/{cid}/looks/{lid}/{source_rel}"
        if source_path.is_file()
        else None,
        "actions": actions_out,
        "ready_count": ready,
        "total_count": len(actions_out),
        "ready": ready >= 1 and any(x["name"] == "idle" and x["exists"] for x in actions_out),
        "root": str(root),
    }


def add_look(character_id: str, look_name: str) -> dict[str, Any]:
    cid = safe_avatar_id(character_id)
    ensure_avatar_dirs(cid)
    name = (look_name or "").strip() or f"造型{int(time.time()) % 10000}"
    lid = safe_avatar_id(slugify(name) or name)
    # 中文等非 ascii 会被收成下划线前缀（如 _a），视为无效
    if (
        lid in ("", "default", "item", "_")
        or set(lid) <= {"_", "-"}
        or lid.startswith("_")
        or lid.startswith("-")
    ):
        lid = f"look_{uuid.uuid4().hex[:6]}"
    # 唯一
    data = _read_char_meta(cid)
    existing = {str(x.get("id")) for x in (data.get("looks") or [])}
    base = lid
    n = 2
    while lid in existing:
        lid = f"{base}_{n}"
        n += 1
    ensure_look_dirs(cid, lid)
    looks = list(data.get("looks") or [])
    looks.append({"id": lid, "name": name})
    data["looks"] = looks
    _write_char_meta(cid, data)
    return {"ok": True, "character_id": cid, "look_id": lid, "look_name": name}


def save_look_image(
    character_id: str,
    look_id: str,
    data: bytes,
    filename: str,
) -> dict[str, Any]:
    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    if lid == "default":
        return {**save_source_image(data, filename, avatar_id=cid), "look_id": "default"}

    root = ensure_look_dirs(cid, lid)
    ext = Path(filename).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    rel = f"source/photo{ext}"
    path = root / rel
    path.write_bytes(data)
    meta_path = root / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    except Exception:
        meta = {}
    meta["source_image"] = rel
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "path": rel,
        "url": f"/media/avatars/{cid}/looks/{lid}/{rel}",
        "look_id": lid,
        "character_id": cid,
    }


def generate_look_videos(character_id: str, look_id: str = "default", force: bool = True) -> dict[str, Any]:
    """从图生成该造型的小幅微动视频（idle 等）。"""
    from .preset_video import generate_action_from_image, ACTION_MOTIONS

    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    root = ensure_look_dirs(cid, lid)

    # 找原图
    source = None
    for cand in [
        root / "source" / "photo.jpg",
        root / "source" / "photo.jpeg",
        root / "source" / "photo.png",
        root / "source" / "photo.webp",
    ]:
        if cand.is_file():
            source = cand
            break
    if source is None:
        src_dir = root / "source"
        if src_dir.is_dir():
            for p in sorted(src_dir.iterdir()):
                if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.is_file():
                    source = p
                    break
    if source is None:
        raise FileNotFoundError("请先上传造型照片")

    created = []
    errors = []
    for name in ACTION_MOTIONS:
        out = root / "actions" / f"{name}.mp4"
        if out.is_file() and not force:
            continue
        try:
            generate_action_from_image(source, out, action=name)
            created.append(
                {
                    "name": name,
                    "url": (
                        f"/media/avatars/{cid}/actions/{name}.mp4"
                        if lid == "default"
                        else f"/media/avatars/{cid}/looks/{lid}/actions/{name}.mp4"
                    ),
                    "size": out.stat().st_size,
                }
            )
        except Exception as e:
            errors.append({"name": name, "error": str(e)})
            logger.warning("generate %s/%s failed: %s", cid, name, e)

    # 更新默认造型 meta duration
    if lid == "default":
        meta = get_or_create_meta(cid)
        for a in meta.actions:
            p = root / a.file
            if p.is_file() and a.name in ACTION_MOTIONS:
                a.duration_ms = int(float(ACTION_MOTIONS[a.name].get("seconds") or 3) * 1000)
        save_meta(meta, cid)

    assets = list_look_assets(cid, lid)
    return {
        "ok": len(created) > 0 and not errors,
        "character_id": cid,
        "look_id": lid,
        "created": created,
        "errors": errors,
        "assets": assets,
        "message": f"已生成 {len(created)} 个微动视频"
        + (f"，{len(errors)} 个失败" if errors else "，可直接开播待机"),
    }


def resolve_live_avatar_dir(character_id: str, look_id: str = "default") -> str:
    """返回相对项目根的目录，供房间 avatar.dir 使用。"""
    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    if lid == "default":
        return f"data/avatars/{cid}"
    return f"data/avatars/{cid}/looks/{lid}"


def look_has_idle(character_id: str, look_id: str = "default") -> bool:
    assets = list_look_assets(character_id, look_id)
    return any(a.get("name") == "idle" and a.get("exists") for a in (assets.get("actions") or []))


def save_look_action(
    character_id: str,
    look_id: str,
    data: bytes,
    action_name: str,
    category: str | None = None,
) -> dict[str, Any]:
    """上传动作视频到指定造型（非 default 写到 looks/{id}/actions）。"""
    from .assets import probe_duration_ms, safe_action_name

    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    if lid == "default":
        return {
            **save_action_video(data, action_name, avatar_id=cid, category=category),
            "look_id": "default",
            "character_id": cid,
        }

    root = ensure_look_dirs(cid, lid)
    name = safe_action_name(action_name)
    rel = f"actions/{name}.mp4"
    path = root / rel
    path.write_bytes(data)
    dur = probe_duration_ms(path) or 3000

    meta_path = root / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    except Exception:
        meta = {}
    actions = list(meta.get("actions") or [])
    found = False
    for a in actions:
        if a.get("name") == name:
            a["file"] = rel
            a["duration_ms"] = dur
            if category:
                a["category"] = category
            found = True
            break
    if not found:
        cat = category or next(
            (d["category"] for d in DEFAULT_ACTIONS if d["name"] == name), "emotion"
        )
        actions.append(
            {"name": name, "file": rel, "duration_ms": dur, "category": cat}
        )
    meta["actions"] = actions
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "name": name,
        "path": rel,
        "duration_ms": dur,
        "url": f"/media/avatars/{cid}/looks/{lid}/{rel}",
        "look_id": lid,
        "character_id": cid,
    }


def delete_look_action(character_id: str, look_id: str, action_name: str) -> dict[str, Any]:
    from .assets import safe_action_name

    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    if lid == "default":
        return {**delete_action(action_name, avatar_id=cid), "look_id": "default"}

    name = safe_action_name(action_name)
    root = ensure_look_dirs(cid, lid)
    path = root / "actions" / f"{name}.mp4"
    if path.is_file():
        path.unlink()
    meta_path = root / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    except Exception:
        meta = {}
    actions = [a for a in (meta.get("actions") or []) if a.get("name") != name]
    defaults = {d["name"]: d for d in DEFAULT_ACTIONS}
    if name in defaults and not any(a.get("name") == name for a in actions):
        d = defaults[name]
        actions.append(
            {
                "name": name,
                "file": f"actions/{name}.mp4",
                "duration_ms": d["duration_ms"],
                "category": d["category"],
            }
        )
    meta["actions"] = actions
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "name": name, "look_id": lid, "character_id": cid}


def delete_look(character_id: str, look_id: str) -> dict[str, Any]:
    import shutil

    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    if lid == "default":
        raise ValueError("默认造型不能删除，可删除整个角色或覆盖上传")
    data = _read_char_meta(cid)
    looks = [x for x in (data.get("looks") or []) if str(x.get("id")) != lid]
    if not looks:
        looks = [{"id": "default", "name": "默认造型"}]
    data["looks"] = looks
    if data.get("default_look") == lid:
        data["default_look"] = "default"
    _write_char_meta(cid, data)
    root = look_root(cid, lid)
    if root.exists() and "looks" in str(root):
        shutil.rmtree(root, ignore_errors=True)
    return {"ok": True, "character_id": cid, "look_id": lid, "deleted": True}


def delete_character(character_id: str) -> dict[str, Any]:
    import shutil

    cid = safe_avatar_id(character_id)
    if cid == "demo":
        raise ValueError("演示角色不能删除")
    root = avatar_root(cid)
    if not root.exists():
        raise FileNotFoundError("角色不存在")
    shutil.rmtree(root, ignore_errors=True)
    try:
        from db.session import get_session
        from db.models import Avatar

        with get_session() as db:
            for a in db.query(Avatar).filter(Avatar.root_path.like(f"%/{cid}")).all():
                db.delete(a)
            db.commit()
    except Exception as e:
        logger.warning("DB avatar delete skipped: %s", e)
    return {"ok": True, "id": cid, "deleted": True}
