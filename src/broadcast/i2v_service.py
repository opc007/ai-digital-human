"""图生视频异步任务：生成造型 idle 待机片。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .assets import safe_avatar_id
from .characters import ensure_look_dirs, look_root, list_look_assets
from .comfyui_client import create_job, update_job
from .i2v_geeknow import GeeknowSeedanceProvider, i2v_configured
from .settings_store import apply_settings_to_engines

logger = logging.getLogger("broadcast.i2v_service")


def _find_look_source(character_id: str, look_id: str) -> Path | None:
    root = ensure_look_dirs(character_id, look_id)
    for name in ("photo.jpg", "photo.jpeg", "photo.png", "photo.webp"):
        p = root / "source" / name
        if p.is_file() and p.stat().st_size > 100:
            return p
    src = root / "source"
    if src.is_dir():
        for p in sorted(src.iterdir()):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.is_file():
                return p
    return None


def start_idle_i2v_job(character_id: str, look_id: str = "default", *, force: bool = True) -> dict[str, Any]:
    """提交异步任务：造型图 → Seedance → idle.mp4。"""
    apply_settings_to_engines()
    if not i2v_configured():
        raise RuntimeError(
            "未配置图生视频 API Key。请到控制台「配置」→「图生视频（待机微动）」填写接口地址、Key 和模型。"
        )

    cid = safe_avatar_id(character_id)
    lid = safe_avatar_id(look_id) or "default"
    source = _find_look_source(cid, lid)
    if not source:
        raise FileNotFoundError("请先上传造型照片，再生成待机视频")

    root = look_root(cid, lid)
    out = root / "actions" / "idle.mp4"
    if out.is_file() and not force:
        return {
            "ok": True,
            "skipped": True,
            "message": "idle 已存在（未强制覆盖）",
            "assets": list_look_assets(cid, lid),
        }

    job = create_job(
        {
            "type": "i2v_idle",
            "character_id": cid,
            "look_id": lid,
            "status": "running",
            "message": "准备上传造型图…",
            "progress": 0,
        }
    )

    def _run() -> None:
        try:
            provider = GeeknowSeedanceProvider()

            def on_progress(info: dict[str, Any]) -> None:
                msg = info.get("message") or info.get("stage") or "生成中…"
                prog = info.get("progress")
                kwargs: dict[str, Any] = {"status": "running", "message": str(msg)}
                if prog is not None:
                    try:
                        kwargs["progress"] = int(prog)
                    except Exception:
                        pass
                remote = info.get("task_id")
                if remote:
                    kwargs["remote_task_id"] = remote
                update_job(job["id"], **kwargs)

            update_job(job["id"], status="running", message="正在调用视频模型…", progress=5)
            data = provider.generate_idle_from_image(source, on_progress=on_progress)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)

            update_job(job["id"], status="running", message="正在压低动作幅度并做无缝循环…", progress=92)
            try:
                from .idle_loop import polish_idle_clip

                polish_idle_clip(out)
            except Exception as seal_err:
                # 后处理失败仍保留原片，可播，只是可能偏「演」或有接缝
                logger.warning("idle polish skipped: %s", seal_err)

            assets = list_look_assets(cid, lid)
            idle_url = next(
                (
                    a.get("url")
                    for a in (assets.get("actions") or [])
                    if a.get("name") == "idle" and a.get("exists")
                ),
                f"/media/avatars/{cid}/actions/idle.mp4"
                if lid == "default"
                else f"/media/avatars/{cid}/looks/{lid}/actions/idle.mp4",
            )
            update_job(
                job["id"],
                status="done",
                message="待机呼吸视频已生成，可回开播台选用",
                progress=100,
                result={
                    "character_id": cid,
                    "look_id": lid,
                    "idle_url": idle_url,
                    "size": out.stat().st_size,
                    "assets": assets,
                },
            )
        except Exception as e:
            logger.exception("i2v idle job failed")
            update_job(job["id"], status="error", message=str(e), progress=0)

    threading.Thread(target=_run, daemon=True).start()
    return {
        "ok": True,
        "async": True,
        "job_id": job["id"],
        "character_id": cid,
        "look_id": lid,
        "message": "已提交视频模型任务，请稍候（通常需数十秒到数分钟）",
    }
