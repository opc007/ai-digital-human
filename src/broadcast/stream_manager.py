"""直播推流进程管理：idle 循环 / 插播一次回复 / 停止。"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from enum import Enum
from pathlib import Path

from .ffmpeg_util import find_ffmpeg
from .stream import build_push_command, mask_rtmp

logger = logging.getLogger("broadcast.stream_manager")


class StreamPhase(str, Enum):
    STOPPED = "stopped"
    IDLE = "idle"
    SPEAKING = "speaking"


class StreamManager:
    """
    简化策略：
    - idle：循环推 idle 视频
    - speak：打断后推一段 clip，再回 idle
    """

    def __init__(self, rtmp_url: str, stream_cfg: dict | None = None):
        self.rtmp_url = rtmp_url or ""
        self.stream_cfg = stream_cfg or {}
        self._proc: subprocess.Popen | None = None
        self._phase = StreamPhase.STOPPED
        self._lock = threading.Lock()
        self._idle_path: Path | None = None
        self._monitor: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._want_idle = False

    @property
    def phase(self) -> StreamPhase:
        return self._phase

    def start_idle_loop(self, idle_video: Path) -> None:
        if not idle_video.is_file():
            raise FileNotFoundError(f"idle 视频不存在: {idle_video}")
        with self._lock:
            self._idle_path = idle_video
            self._want_idle = True
            self._stop_flag.clear()
            self._start_process(idle_video, loop=True, phase=StreamPhase.IDLE)
        if not self._monitor or not self._monitor.is_alive():
            self._monitor = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor.start()

    def play_once(self, clip: Path, resume_idle: bool = True) -> None:
        if not clip.is_file():
            raise FileNotFoundError(clip)
        with self._lock:
            self._want_idle = False
            self._start_process(clip, loop=False, phase=StreamPhase.SPEAKING)
        proc = self._proc
        if proc:
            while proc.poll() is None:
                if self._stop_flag.is_set():
                    self._kill_process()
                    return
                time.sleep(0.05)
        with self._lock:
            if (
                resume_idle
                and self._idle_path
                and not self._stop_flag.is_set()
            ):
                self._want_idle = True
                self._start_process(self._idle_path, loop=True, phase=StreamPhase.IDLE)

    def stop(self) -> None:
        self._stop_flag.set()
        self._want_idle = False
        with self._lock:
            self._kill_process()
            self._phase = StreamPhase.STOPPED

    def abort_to_idle(self) -> None:
        """打断当前 SPEAKING 片段，立即切回 idle 循环。"""
        if self._stop_flag.is_set():
            return
        with self._lock:
            if self._phase != StreamPhase.SPEAKING:
                return
            self._kill_process()
            if self._idle_path:
                self._want_idle = True
                self._start_process(self._idle_path, loop=True, phase=StreamPhase.IDLE)
            else:
                self._phase = StreamPhase.STOPPED

    def _start_process(self, path: Path, loop: bool, phase: StreamPhase) -> None:
        self._kill_process()
        if not self.rtmp_url:
            logger.info("dry 推流 phase=%s file=%s", phase.value, path.name)
            self._phase = phase
            return
        if not find_ffmpeg():
            logger.error("未找到 ffmpeg，无法推流")
            self._phase = phase
            return
        cmd = build_push_command(
            path,
            self.rtmp_url,
            video_bitrate=str(self.stream_cfg.get("video_bitrate") or "4000k"),
            audio_bitrate=str(self.stream_cfg.get("audio_bitrate") or "128k"),
            video_codec=str(self.stream_cfg.get("video_codec") or "libx264"),
            preset=str(self.stream_cfg.get("preset") or "ultrafast"),
            tune=str(self.stream_cfg.get("tune") or "zerolatency"),
            loop=loop,
        )
        logger.info(
            "stream start phase=%s file=%s url=%s",
            phase.value,
            path.name,
            mask_rtmp(self.rtmp_url),
        )
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._phase = phase
        except Exception:
            logger.exception("启动 ffmpeg 失败")
            self._phase = StreamPhase.STOPPED

    def _kill_process(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                try:
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
        self._proc = None

    def _monitor_loop(self) -> None:
        while not self._stop_flag.is_set():
            time.sleep(1.0)
            with self._lock:
                if not self._want_idle or not self._idle_path:
                    continue
                if self._phase == StreamPhase.SPEAKING:
                    continue
                if self._proc is None or self._proc.poll() is not None:
                    if self.rtmp_url and not self._stop_flag.is_set():
                        logger.warning("idle 推流退出，尝试重启")
                        try:
                            self._start_process(
                                self._idle_path, loop=True, phase=StreamPhase.IDLE
                            )
                        except Exception:
                            logger.exception("idle 重启失败")
