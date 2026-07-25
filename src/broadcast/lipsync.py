"""口型引擎：MuseTalk 外部脚本 + Mock。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from .ffmpeg_util import ffmpeg_available, run_ffmpeg

logger = logging.getLogger("broadcast.lipsync")


class LipSyncEngine(ABC):
    @abstractmethod
    def run(
        self,
        audio_path: Path,
        reference_video: Path,
        out_path: Path,
    ) -> Path:
        ...


def _vf_scale_pad(width: int, height: int, fit: str = "contain") -> str:
    """
    输出固定画幅：contain=完整人物+黑边；cover=铺满裁剪。
    抖音竖屏 1080x1920 / 横屏 1920x1080 都走这里。
    """
    w, h = max(16, int(width)), max(16, int(height))
    fit = (fit or "contain").lower()
    if fit == "cover":
        # 铺满后居中裁剪
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps=25"
        )
    # 默认 contain：等比缩放到画幅内，黑边填充，人物完整
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=25"
    )


class MockLipSyncEngine(LipSyncEngine):
    """参考视频画面 + TTS 音轨混流（无真实口型），并规范到输出画幅。"""

    def __init__(
        self,
        prefer_mux_audio: bool = True,
        width: int = 1080,
        height: int = 1920,
        fit: str = "contain",
    ):
        self.prefer_mux_audio = prefer_mux_audio
        self.width = int(width or 1080)
        self.height = int(height or 1920)
        self.fit = (fit or "contain").lower()

    def run(
        self,
        audio_path: Path,
        reference_video: Path,
        out_path: Path,
    ) -> Path:
        if not reference_video.is_file():
            raise FileNotFoundError(f"参考视频不存在: {reference_video}")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if self.prefer_mux_audio and audio_path.is_file() and ffmpeg_available():
            try:
                vf = _vf_scale_pad(self.width, self.height, self.fit)
                logger.info(
                    "MockLipSync mux -> %s size=%sx%s fit=%s",
                    out_path.name,
                    self.width,
                    self.height,
                    self.fit,
                )
                proc = run_ffmpeg(
                    [
                        "-y",
                        "-i",
                        str(reference_video),
                        "-i",
                        str(audio_path),
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0?",
                        "-vf",
                        vf,
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-shortest",
                        str(out_path),
                    ],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr[-800:] if proc.stderr else "ffmpeg failed")
                return out_path
            except Exception as e:
                logger.warning("ffmpeg 混流失败，改为复制视频: %s", e)

        shutil.copy2(reference_video, out_path)
        return out_path


class MuseTalkLipSyncEngine(LipSyncEngine):
    """
    通过外部推理脚本调用 MuseTalk。
    未配置 MUSETALK_ROOT 时直接 mock，避免无意义的失败日志。
    """

    def __init__(
        self,
        model_path: str = "models/musetalk",
        device: str = "cuda",
        script_path: str | None = None,
        python_exe: str | None = None,
        timeout_sec: int = 600,
        fallback_mock: bool = True,
        width: int = 1080,
        height: int = 1920,
        fit: str = "contain",
    ):
        self.model_path = model_path
        self.device = device
        root = Path(__file__).resolve().parents[2]
        self.script_path = Path(
            script_path
            or os.getenv("MUSETALK_SCRIPT")
            or (root / "tools" / "musetalk_infer.py")
        )
        self.python_exe = python_exe or os.getenv("MUSETALK_PYTHON") or sys.executable
        self.timeout_sec = timeout_sec
        self.fallback_mock = fallback_mock
        self._mock = MockLipSyncEngine(width=width, height=height, fit=fit)
        self.musetalk_root = os.getenv("MUSETALK_ROOT") or ""

    def run(
        self,
        audio_path: Path,
        reference_video: Path,
        out_path: Path,
    ) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # 未配置真模型仓库：直接混流，不刷错误日志
        if not self.musetalk_root and self.fallback_mock:
            return self._mock.run(audio_path, reference_video, out_path)

        if not self.script_path.is_file():
            logger.warning("MuseTalk 脚本不存在，使用 mock: %s", self.script_path)
            if self.fallback_mock:
                return self._mock.run(audio_path, reference_video, out_path)
            raise FileNotFoundError(self.script_path)

        cmd = [
            self.python_exe,
            str(self.script_path),
            "--audio",
            str(audio_path),
            "--video",
            str(reference_video),
            "--out",
            str(out_path),
            "--model-path",
            self.model_path,
            "--device",
            self.device,
        ]
        env = os.environ.copy()
        if self.musetalk_root:
            env["MUSETALK_ROOT"] = self.musetalk_root

        logger.info("MuseTalk infer: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                env=env,
            )
        except FileNotFoundError as e:
            logger.error("无法启动 MuseTalk 进程: %s", e)
            if self.fallback_mock:
                return self._mock.run(audio_path, reference_video, out_path)
            raise
        except subprocess.TimeoutExpired:
            logger.error("MuseTalk 超时")
            if self.fallback_mock:
                return self._mock.run(audio_path, reference_video, out_path)
            raise

        if proc.returncode != 0 or not out_path.is_file():
            logger.error(
                "MuseTalk 失败 code=%s stderr=%s",
                proc.returncode,
                (proc.stderr or proc.stdout or "")[-800:],
            )
            if self.fallback_mock:
                logger.warning("回落 MockLipSync")
                return self._mock.run(audio_path, reference_video, out_path)
            raise RuntimeError(f"MuseTalk failed: {proc.stderr}")

        logger.info("MuseTalk ok -> %s", out_path)
        return out_path


def resolve_output_size(app_avatar: dict | None = None) -> tuple[int, int, str]:
    """
    解析输出画幅。
    OUTPUT_ORIENTATION: portrait(竖屏 9:16) | landscape(横屏 16:9) | square
    也可用 width/height 直接指定。
    """
    cfg = app_avatar or {}
    orient = (
        str(cfg.get("orientation") or os.getenv("OUTPUT_ORIENTATION") or "portrait")
        .strip()
        .lower()
    )
    fit = str(cfg.get("fit") or os.getenv("OUTPUT_FIT") or "contain").strip().lower()
    if fit not in ("contain", "cover"):
        fit = "contain"

    presets = {
        "portrait": (1080, 1920),  # 抖音/快手/视频号常见竖屏
        "vertical": (1080, 1920),
        "landscape": (1920, 1080),
        "horizontal": (1920, 1080),
        "square": (1080, 1080),
    }
    if orient in presets:
        w, h = presets[orient]
    else:
        w = int(cfg.get("width") or os.getenv("OUTPUT_WIDTH") or 1080)
        h = int(cfg.get("height") or os.getenv("OUTPUT_HEIGHT") or 1920)
    # 显式 width/height 优先覆盖
    if cfg.get("width"):
        w = int(cfg["width"])
    if cfg.get("height"):
        h = int(cfg["height"])
    return w, h, fit


def create_lipsync_engine(app_avatar: dict, mock: bool = False) -> LipSyncEngine:
    w, h, fit = resolve_output_size(app_avatar or {})
    if mock or (app_avatar.get("provider") or "").lower() == "mock":
        return MockLipSyncEngine(width=w, height=h, fit=fit)
    provider = (app_avatar.get("provider") or "musetalk").lower()
    if provider == "mock":
        return MockLipSyncEngine(width=w, height=h, fit=fit)
    if provider == "musetalk":
        return MuseTalkLipSyncEngine(
            model_path=str(app_avatar.get("model_path") or "models/musetalk"),
            device=str(app_avatar.get("device") or "cuda"),
            fallback_mock=bool(app_avatar.get("fallback_mock", True)),
            width=w,
            height=h,
            fit=fit,
        )
    raise ValueError(f"未知 avatar provider: {provider}")
