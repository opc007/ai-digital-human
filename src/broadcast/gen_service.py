"""动作生成任务：ComfyUI 或说明性失败。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml

from .assets import avatar_root, get_or_create_meta, save_action_video
from .comfyui_client import (
    ComfyUIClient,
    create_job,
    get_job,
    inject_workflow,
    list_jobs,
    load_workflow_template,
    update_job,
)
from .config import project_root

logger = logging.getLogger("broadcast.gen_service")


def load_action_prompts() -> dict[str, Any]:
    path = project_root() / "configs" / "comfyui" / "action_prompts.yaml"
    if not path.is_file():
        return {"actions": {}, "negative": ""}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def start_generate_action(
    action_name: str,
    avatar_id: str = "demo",
    prompt_override: str | None = None,
) -> dict[str, Any]:
    prompts = load_action_prompts()
    actions = prompts.get("actions") or {}
    info = actions.get(action_name) or {}
    prompt = prompt_override or info.get("prompt") or f"person doing {action_name}"
    negative = prompts.get("negative") or "blurry, distorted face"

    meta = get_or_create_meta(avatar_id)
    root = avatar_root(avatar_id)
    source = root / meta.source_image
    if not source.is_file():
        raise FileNotFoundError("请先上传形象原图（正脸照片）")

    workflow = load_workflow_template()
    if not workflow:
        raise FileNotFoundError(
            "未找到 ComfyUI 工作流。请把 API 格式工作流保存为 configs/comfyui/action_workflow.json，"
            "或直接在素材中心手动上传做好的动作视频。"
        )

    client = ComfyUIClient()
    health = client.health()
    if not health.get("ok"):
        raise ConnectionError(health.get("message") or "ComfyUI 未连接")

    job = create_job(
        {
            "type": "comfyui_action",
            "action": action_name,
            "avatar_id": avatar_id,
            "prompt": prompt,
            "status": "running",
            "message": "上传参考图…",
        }
    )

    def _run() -> None:
        try:
            update_job(job["id"], status="running", message="上传参考图到 ComfyUI…")
            up = client.upload_image(source, name=f"{avatar_id}_source{source.suffix}")
            image_name = up.get("name") or source.name

            wf = inject_workflow(
                workflow,
                image_name=image_name,
                prompt=prompt,
                negative=negative,
            )
            update_job(job["id"], message="提交工作流…")
            pid = client.queue_prompt(wf)
            update_job(job["id"], prompt_id=pid, message=f"生成中 prompt_id={pid}")

            hist = client.wait_result(pid, timeout_sec=900)
            outputs = hist.get("outputs") or {}
            # 找第一个视频/动图输出
            video_file = None
            subfolder = ""
            folder_type = "output"
            for node_out in outputs.values():
                for key in ("gifs", "videos", "images"):
                    items = node_out.get(key) or []
                    for it in items:
                        fn = it.get("filename") or ""
                        if fn.lower().endswith((".mp4", ".webm", ".gif", ".png", ".webp")):
                            video_file = fn
                            subfolder = it.get("subfolder") or ""
                            folder_type = it.get("type") or "output"
                            break
                    if video_file:
                        break
                if video_file:
                    break

            if not video_file:
                raise RuntimeError("工作流完成但未找到视频输出，请检查 ComfyUI 工作流保存节点")

            tmp = project_root() / "data" / "temp" / f"{job['id']}_{video_file}"
            client.download_view(
                video_file,
                subfolder=subfolder,
                folder_type=folder_type,
                out_path=tmp,
            )
            # gif/png 也可先落盘，用户后续可替换；优先 mp4
            data = tmp.read_bytes()
            if not video_file.lower().endswith(".mp4"):
                # 非 mp4 仍保存，扩展名跟原文件
                out_name = action_name
                dest = avatar_root(avatar_id) / "actions" / f"{out_name}{Path(video_file).suffix}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                # 若不是 mp4，仍尝试写入 meta 指向该文件——开播偏好 mp4
                update_job(
                    job["id"],
                    status="done",
                    message=f"已生成 {dest.name}（建议转成 mp4 后上传覆盖）",
                    result_url=f"/media/avatars/{avatar_id}/actions/{dest.name}",
                )
                return

            result = save_action_video(data, action_name, avatar_id=avatar_id)
            update_job(
                job["id"],
                status="done",
                message="生成完成并已写入动作库",
                result_url=result.get("url"),
            )
        except Exception as e:
            logger.exception("generate failed")
            update_job(job["id"], status="error", message=str(e))

    threading.Thread(target=_run, daemon=True).start()
    return job
