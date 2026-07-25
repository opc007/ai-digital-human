"""本地 ComfyUI 对接：健康检查、提交工作流、拉取结果。"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import project_root

logger = logging.getLogger("broadcast.comfyui")


def comfy_base() -> str:
    return (os.getenv("COMFYUI_BASE_URL") or "http://127.0.0.1:8188").rstrip("/")


def workflow_path() -> Path:
    custom = os.getenv("COMFYUI_WORKFLOW_PATH")
    if custom:
        return Path(custom)
    return project_root() / "configs" / "comfyui" / "action_workflow.json"


class ComfyUIClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base = (base_url or comfy_base()).rstrip("/")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=3.0) as c:
                # 不同版本接口不一，多试几个
                for path in ("/system_stats", "/queue", "/object_info"):
                    try:
                        r = c.get(f"{self.base}{path}")
                        if r.status_code == 200:
                            return {
                                "ok": True,
                                "base_url": self.base,
                                "probe": path,
                                "message": "ComfyUI 在线",
                            }
                    except Exception:
                        continue
            return {"ok": False, "base_url": self.base, "message": "无法连接 ComfyUI"}
        except Exception as e:
            return {"ok": False, "base_url": self.base, "message": str(e)}

    def upload_image(self, image_path: Path, name: str | None = None) -> dict[str, Any]:
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        fname = name or image_path.name
        with httpx.Client(timeout=60.0) as c:
            with image_path.open("rb") as f:
                r = c.post(
                    f"{self.base}/upload/image",
                    files={"image": (fname, f, "application/octet-stream")},
                    data={"overwrite": "true"},
                )
            r.raise_for_status()
            return r.json() if r.content else {"name": fname}

    def queue_prompt(self, workflow: dict[str, Any], client_id: str | None = None) -> str:
        client_id = client_id or uuid.uuid4().hex
        payload = {"prompt": workflow, "client_id": client_id}
        with httpx.Client(timeout=self.timeout) as c:
            r = c.post(f"{self.base}/prompt", json=payload)
            if r.status_code >= 400:
                raise RuntimeError(f"ComfyUI /prompt {r.status_code}: {r.text[:400]}")
            data = r.json()
        pid = data.get("prompt_id") or data.get("promptId")
        if not pid:
            raise RuntimeError(f"ComfyUI 未返回 prompt_id: {data}")
        return str(pid)

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(f"{self.base}/history/{prompt_id}")
            r.raise_for_status()
            data = r.json()
        return data.get(prompt_id) or data

    def download_view(
        self,
        filename: str,
        subfolder: str = "",
        folder_type: str = "output",
        out_path: Path | None = None,
    ) -> Path:
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        with httpx.Client(timeout=120.0) as c:
            r = c.get(f"{self.base}/view", params=params)
            r.raise_for_status()
            if out_path is None:
                out_path = project_root() / "data" / "temp" / filename
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(r.content)
            return out_path

    def wait_result(
        self,
        prompt_id: str,
        timeout_sec: float = 600.0,
        poll: float = 2.0,
    ) -> dict[str, Any]:
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            hist = self.get_history(prompt_id)
            if hist and hist.get("outputs"):
                return hist
            # status completed
            status = (hist or {}).get("status") or {}
            if status.get("completed") or status.get("status_str") == "success":
                if hist.get("outputs"):
                    return hist
            time.sleep(poll)
        raise TimeoutError(f"ComfyUI 任务超时: {prompt_id}")


def load_workflow_template() -> dict[str, Any] | None:
    path = workflow_path()
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def inject_workflow(
    workflow: dict[str, Any],
    *,
    image_name: str,
    prompt: str,
    negative: str = "blurry, distorted face, extra fingers",
) -> dict[str, Any]:
    """
    启发式替换工作流里的占位：
    - 字符串 __IMAGE__ / __PROMPT__ / __NEGATIVE__
    - 或常见字段 inputs.image / inputs.text
    """
    raw = json.dumps(workflow, ensure_ascii=False)
    raw = raw.replace("__IMAGE__", image_name)
    raw = raw.replace("__PROMPT__", prompt.replace('"', '\\"'))
    raw = raw.replace("__NEGATIVE__", negative.replace('"', '\\"'))
    data = json.loads(raw)

    # 额外：遍历节点改 text 类
    if isinstance(data, dict):
        for node in data.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            if "text" in inputs and inputs.get("text") in ("__PROMPT__", "", None):
                inputs["text"] = prompt
            if inputs.get("image") == "__IMAGE__":
                inputs["image"] = image_name
    return data


# 内存任务表（进程内）
_JOBS: dict[str, dict[str, Any]] = {}


def get_job(job_id: str) -> dict[str, Any] | None:
    return _JOBS.get(job_id)


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    items = sorted(_JOBS.values(), key=lambda x: x.get("created_at", 0), reverse=True)
    return items[:limit]


def create_job(meta: dict[str, Any]) -> dict[str, Any]:
    jid = uuid.uuid4().hex[:12]
    job = {
        "id": jid,
        "status": "queued",
        "created_at": time.time(),
        "message": "",
        **meta,
    }
    _JOBS[jid] = job
    return job


def update_job(job_id: str, **kwargs: Any) -> None:
    if job_id in _JOBS:
        _JOBS[job_id].update(kwargs)
