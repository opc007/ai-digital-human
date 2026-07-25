"""待机片后处理：只做无缝循环，不做会发糊的混合。

历史教训：
- still_mix 与首帧 blend → 重影发糊（已禁用）
- 首尾同图生成 → 模型中间推拉再缩回（在 prompts 里关闭）
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from .ffmpeg_util import find_ffmpeg, run_ffmpeg
from .i2v_prompts import load_idle_prompt_config

logger = logging.getLogger("broadcast.idle_loop")

# 正放 + 倒放（去掉倒放首帧，避免中点双帧）
_PINGPONG = (
    "[0:v]split=2[f0][r0];"
    "[r0]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[r1];"
    "[f0][r1]concat=n=2:v=1:a=0[vout]"
)


def _still_mix_from_cfg() -> float:
    cfg = load_idle_prompt_config()
    try:
        v = float(cfg.get("still_mix") if cfg.get("still_mix") is not None else 0.0)
    except (TypeError, ValueError):
        v = 0.0
    # 硬上限压低：即使误配也不要再糊成一片
    return max(0.0, min(0.25, v))


def polish_idle_clip(video_path: Path, *, still_mix: float | None = None) -> Path:
    """原地后处理：默认仅乒乓循环；still_mix 仅在显式很小值时启用且带警告。"""
    path = Path(video_path)
    if not path.is_file() or path.stat().st_size < 1000:
        raise FileNotFoundError(f"idle 视频不存在或过小: {path}")

    if not find_ffmpeg():
        logger.warning("无 ffmpeg，跳过 idle 后处理")
        return path

    mix = _still_mix_from_cfg() if still_mix is None else max(0.0, min(0.25, float(still_mix)))
    if mix > 0.01:
        logger.warning(
            "still_mix=%.2f 易导致发糊，仅作弱压制；推荐配置为 0",
            mix,
        )
        motion = 1.0 - mix
        filt = (
            "[0:v]split=2[dyn][fr];"
            "[fr]trim=end_frame=1,setpts=PTS-STARTPTS,"
            "loop=loop=-1:size=1:start=0,setpts=N/FRAME_RATE/TB[still];"
            f"[dyn][still]blend=all_expr='A*{motion:.4f}+B*{mix:.4f}':shortest=1[soft];"
            "[soft]split=2[f0][r0];"
            "[r0]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[r1];"
            "[f0][r1]concat=n=2:v=1:a=0[vout]"
        )
    else:
        filt = _PINGPONG

    with tempfile.TemporaryDirectory(prefix="idle_loop_") as td:
        tmp = Path(td) / "polished.mp4"
        args = [
            "-y",
            "-i",
            str(path),
            "-filter_complex",
            filt,
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "15",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
        proc = run_ffmpeg(args, capture_output=True, text=True)
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 1000:
            err = (proc.stderr or "")[-600:]
            logger.error("polish_idle_clip ffmpeg failed: %s", err)
            raise RuntimeError(f"待机后处理失败: {err[-200:]}")

        bak = path.with_suffix(".mp4.bak_raw")
        try:
            if bak.exists():
                bak.unlink()
            path.replace(bak)
            path.write_bytes(tmp.read_bytes())
            if bak.exists():
                bak.unlink()
        except Exception:
            if not path.exists() and bak.exists():
                bak.replace(path)
            raise

    logger.info("polished idle (pingpong, mix=%.2f): %s", mix, path)
    return path


def seal_idle_loop(video_path: Path) -> Path:
    return polish_idle_clip(video_path)
