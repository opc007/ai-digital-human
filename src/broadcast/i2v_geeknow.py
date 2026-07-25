"""Geeknow / NewAPI 兼容：Seedance 1.5 图生视频。"""

from __future__ import annotations

import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import httpx

from .i2v_prompts import build_idle_prompt, load_idle_prompt_config

logger = logging.getLogger("broadcast.i2v_geeknow")


def i2v_base_url() -> str:
    return (os.getenv("VIDEO_I2V_BASE_URL") or "").rstrip("/")


def i2v_api_key() -> str:
    return (os.getenv("VIDEO_I2V_API_KEY") or "").strip()


def i2v_model() -> str:
    return (os.getenv("VIDEO_I2V_MODEL") or "doubao-seedance-1-5-pro_720p").strip()


def i2v_configured() -> bool:
    return bool(i2v_api_key())


class GeeknowSeedanceProvider:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ):
        self.base = (base_url or i2v_base_url()).rstrip("/")
        self.api_key = (api_key if api_key is not None else i2v_api_key()).strip()
        self.model = (model or i2v_model()).strip()
        self.timeout = timeout
        if not self.api_key:
            raise RuntimeError("未配置 VIDEO_I2V_API_KEY，请到控制台「配置」填写图生视频 API Key")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def upload_image(self, image_path: Path) -> str:
        """本地图 → 预签名上传 → 返回 public_url。"""
        if not image_path.is_file():
            raise FileNotFoundError(f"图片不存在: {image_path}")
        ctype = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        with httpx.Client(timeout=60.0) as c:
            r = c.post(
                f"{self.base}/api/upload/presign",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={
                    "file_name": image_path.name,
                    "content_type": ctype,
                    "expires_in": 900,
                },
            )
            if r.status_code >= 400:
                raise RuntimeError(f"预签名上传失败 {r.status_code}: {r.text[:500]}")
            data = r.json() if r.content else {}
            # 兼容 success/data 包装或扁平结构
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
            if data.get("success") is False:
                raise RuntimeError(data.get("message") or "预签名失败")
            upload_url = payload.get("upload_url") or payload.get("uploadUrl")
            public_url = payload.get("public_url") or payload.get("publicUrl")
            method = (payload.get("method") or "PUT").upper()
            if not upload_url or not public_url:
                raise RuntimeError(f"预签名响应缺少 upload_url/public_url: {data}")

            raw = image_path.read_bytes()
            put_headers = {"Content-Type": ctype}
            if method == "POST":
                up = c.post(upload_url, content=raw, headers=put_headers)
            else:
                up = c.put(upload_url, content=raw, headers=put_headers)
            if up.status_code >= 400:
                raise RuntimeError(f"上传图片失败 {up.status_code}: {up.text[:400]}")
        logger.info("i2v image uploaded -> %s", public_url[:120])
        return str(public_url)

    def create_video_task(
        self,
        *,
        first_frame_image_url: str,
        prompt: str | None = None,
        seconds: str | None = None,
        size: str | None = None,
        last_frame_image_url: str | None = None,
    ) -> str:
        cfg = load_idle_prompt_config()
        prompt = (prompt or build_idle_prompt()).strip()
        seconds = str(seconds or cfg.get("seconds") or "4")
        size = str(size or cfg.get("size") or "9:16")
        # 待机默认不用尾帧同图：同图常导致中间推近/拉远再缩回
        same_last = cfg.get("same_last_frame", False)
        last_url = last_frame_image_url
        if last_url is None and same_last:
            last_url = first_frame_image_url

        with httpx.Client(timeout=self.timeout) as c:
            # Seedance 1.5 要求 multipart/form-data（不能用 x-www-form-urlencoded）
            files = {
                "model": (None, self.model),
                "prompt": (None, prompt),
                "seconds": (None, seconds),
                "size": (None, size),
                "first_frame_image": (None, first_frame_image_url),
            }
            if last_url:
                files["last_frame_image"] = (None, last_url)
            # 部分网关支持锁镜头；忽略未知字段错误由下方 status 处理
            files["camera_fixed"] = (None, "true")
            r = c.post(
                f"{self.base}/v1/videos",
                headers=self._headers(),
                files=files,
            )
            # 若网关拒收 camera_fixed，去掉后重试一次
            if r.status_code >= 400 and "camera_fixed" in (r.text or ""):
                files.pop("camera_fixed", None)
                r = c.post(
                    f"{self.base}/v1/videos",
                    headers=self._headers(),
                    files=files,
                )
            if r.status_code >= 400:
                raise RuntimeError(f"创建视频任务失败 {r.status_code}: {r.text[:600]}")
            data = r.json() if r.content else {}
        if isinstance(data.get("error"), dict):
            err = data["error"]
            msg = err.get("message") or str(err)
            if "camera_fixed" in msg.lower() or "unknown" in msg.lower():
                # 再试无 camera_fixed
                with httpx.Client(timeout=self.timeout) as c:
                    files.pop("camera_fixed", None)
                    r = c.post(
                        f"{self.base}/v1/videos",
                        headers=self._headers(),
                        files=files,
                    )
                    if r.status_code >= 400:
                        raise RuntimeError(f"创建视频任务失败 {r.status_code}: {r.text[:600]}")
                    data = r.json() if r.content else {}
                    if isinstance(data.get("error"), dict):
                        err2 = data["error"]
                        raise RuntimeError(err2.get("message") or str(err2))
            else:
                raise RuntimeError(msg)
        task_id = data.get("id") or data.get("task_id") or data.get("taskId")
        if not task_id:
            raise RuntimeError(f"创建任务未返回 id: {data}")
        logger.info(
            "i2v task created id=%s model=%s last_frame=%s",
            task_id,
            self.model,
            bool(last_url),
        )
        return str(task_id)

    def poll_task(self, task_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=60.0) as c:
            r = c.get(f"{self.base}/v1/videos/{task_id}", headers=self._headers())
            if r.status_code >= 400:
                raise RuntimeError(f"查询任务失败 {r.status_code}: {r.text[:500]}")
            data = r.json() if r.content else {}
        if isinstance(data.get("error"), dict):
            return {
                "status": "failed",
                "error": data["error"].get("message") or str(data["error"]),
                "raw": data,
            }
        status = str(data.get("status") or "").lower()
        video_url = data.get("video_url") or data.get("videoUrl") or ""
        result = data.get("result")
        if not video_url and isinstance(result, dict):
            video_url = result.get("video_url") or result.get("videoUrl") or ""
        if not video_url and isinstance(data.get("output"), dict):
            video_url = data["output"].get("video_url") or data["output"].get("url") or ""
        return {
            "status": status or "unknown",
            "progress": data.get("progress"),
            "video_url": video_url or "",
            "raw": data,
        }

    def wait_for_video(
        self,
        task_id: str,
        *,
        timeout_sec: float = 600.0,
        interval_sec: float = 3.0,
        on_progress: Any = None,
    ) -> str:
        deadline = time.time() + timeout_sec
        last_status = ""
        while time.time() < deadline:
            info = self.poll_task(task_id)
            status = info.get("status") or ""
            if status != last_status:
                logger.info("i2v task %s status=%s progress=%s", task_id, status, info.get("progress"))
                last_status = status
            if on_progress:
                try:
                    on_progress(info)
                except Exception:
                    pass
            if status in ("completed", "succeeded", "success", "done"):
                url = (info.get("video_url") or "").strip()
                if url:
                    return url
                # 无 url 时仍可走 content 下载
                return ""
            if status in ("failed", "error", "cancelled", "canceled"):
                raise RuntimeError(info.get("error") or f"视频生成失败: {status}")
            time.sleep(interval_sec)
        raise TimeoutError(f"等待视频超时（>{int(timeout_sec)}s）task={task_id}")

    def download_video(self, task_id: str, video_url: str = "") -> bytes:
        with httpx.Client(timeout=180.0, follow_redirects=True) as c:
            if video_url:
                r = c.get(video_url, headers=self._headers())
                if r.status_code < 400 and r.content and len(r.content) > 1000:
                    return r.content
            r2 = c.get(f"{self.base}/v1/videos/{task_id}/content", headers=self._headers())
            if r2.status_code >= 400:
                raise RuntimeError(f"下载视频失败 {r2.status_code}: {r2.text[:400]}")
            if not r2.content or len(r2.content) < 1000:
                raise RuntimeError("下载到的视频内容过小或为空")
            return r2.content

    def generate_idle_from_image(self, image_path: Path, on_progress: Any = None) -> bytes:
        public_url = self.upload_image(image_path)
        if on_progress:
            on_progress({"stage": "uploaded", "message": "照片已上传，正在提交视频任务…"})
        task_id = self.create_video_task(first_frame_image_url=public_url)
        if on_progress:
            on_progress({"stage": "queued", "task_id": task_id, "message": "视频任务已提交，生成中…"})

        def _prog(info: dict[str, Any]) -> None:
            if on_progress:
                on_progress(
                    {
                        "stage": "polling",
                        "task_id": task_id,
                        "status": info.get("status"),
                        "progress": info.get("progress"),
                        "message": f"生成中… {info.get('status') or ''} {info.get('progress') or ''}",
                    }
                )

        video_url = self.wait_for_video(task_id, on_progress=_prog)
        if on_progress:
            on_progress({"stage": "downloading", "task_id": task_id, "message": "正在下载视频…"})
        return self.download_video(task_id, video_url)
