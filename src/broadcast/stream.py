"""FFmpeg RTMP 推流。"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

from .ffmpeg_util import find_ffmpeg

logger = logging.getLogger("broadcast.stream")


def build_push_command(
    input_path: Path | str,
    rtmp_url: str,
    *,
    video_bitrate: str = "4000k",
    audio_bitrate: str = "128k",
    video_codec: str = "libx264",
    preset: str = "ultrafast",
    tune: str = "zerolatency",
    loop: bool = False,
) -> list[str]:
    exe = find_ffmpeg() or "ffmpeg"
    cmd = [exe, "-y"]
    if loop:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-re", "-i", str(input_path)]
    cmd += [
        "-c:v",
        video_codec,
        "-preset",
        preset,
        "-tune",
        tune,
        "-b:v",
        video_bitrate,
        "-maxrate",
        video_bitrate,
        "-bufsize",
        "8000k",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "50",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-ar",
        "44100",
        "-f",
        "flv",
        rtmp_url,
    ]
    return cmd


def mask_rtmp(rtmp_url: str) -> str:
    if not rtmp_url or "/" not in rtmp_url:
        return rtmp_url or ""
    parts = rtmp_url.rsplit("/", 1)
    if len(parts) == 2 and parts[1]:
        return parts[0] + "/" + ("*" * min(8, len(parts[1])))
    return rtmp_url


def push_rtmp(
    input_path: Path,
    rtmp_url: str,
    stream_cfg: dict | None = None,
    *,
    dry_run: bool = False,
    loop: bool = False,
    reconnect_max: int = 5,
    reconnect_base_sec: float = 2.0,
    stop_event: threading.Event | None = None,
) -> int:
    """
    阻塞推流直到结束、失败或 stop_event 被置位。
    dry_run 只打印命令。
    """
    stream_cfg = stream_cfg or {}
    if not dry_run and not input_path.is_file():
        raise FileNotFoundError(f"推流输入不存在: {input_path}")

    if not dry_run and not find_ffmpeg():
        raise FileNotFoundError("未找到 ffmpeg，无法推流")

    cmd = build_push_command(
        input_path,
        rtmp_url,
        video_bitrate=str(stream_cfg.get("video_bitrate") or "4000k"),
        audio_bitrate=str(stream_cfg.get("audio_bitrate") or "128k"),
        video_codec=str(stream_cfg.get("video_codec") or "libx264"),
        preset=str(stream_cfg.get("preset") or "ultrafast"),
        tune=str(stream_cfg.get("tune") or "zerolatency"),
        loop=loop,
    )

    safe_url = mask_rtmp(rtmp_url)
    logger.info("push cmd (key masked): %s", " ".join(cmd[:-1] + [safe_url]))

    if dry_run:
        print("DRY-RUN:", " ".join(cmd[:-1] + [safe_url]))
        return 0

    if not rtmp_url:
        raise ValueError("rtmp_url 为空，请配置 stream.rtmp_url 与 RTMP key")

    attempt = 0
    max_retry = int(stream_cfg.get("reconnect_max") or reconnect_max)
    base = float(stream_cfg.get("reconnect_base_sec") or reconnect_base_sec)

    def _run_once() -> int:
        """跑一次 ffmpeg；stop_event 置位时终止子进程并返回 0。"""
        proc = subprocess.Popen(cmd)
        try:
            while proc.poll() is None:
                if stop_event is not None and stop_event.is_set():
                    logger.warning("收到停止信号，终止推流进程")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)
                    return 0
                time.sleep(0.2)
            return int(proc.returncode or 0)
        finally:
            if proc.poll() is None:
                proc.kill()

    while True:
        code = _run_once()
        if code == 0:
            return 0
        attempt += 1
        if attempt > max_retry:
            logger.error("推流失败，已重试 %s 次", max_retry)
            return code
        sleep_s = base * (2 ** (attempt - 1))
        logger.warning(
            "推流退出 code=%s，%.1fs 后重试 (%s/%s)",
            code,
            sleep_s,
            attempt,
            max_retry,
        )
        # 退避等待也可被停止信号打断
        if stop_event is not None and stop_event.wait(timeout=sleep_s):
            logger.warning("收到停止信号，放弃重连")
            return 0
        if stop_event is None:
            time.sleep(sleep_s)
