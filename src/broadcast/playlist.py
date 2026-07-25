"""根据脚本条目生成 FFmpeg concat 播放列表。"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("broadcast.playlist")


def write_concat_list(video_paths: list[Path], list_path: Path) -> Path:
    """
    生成 ffmpeg concat demuxer 列表。
    注意：路径使用正斜杠，并对单引号转义。
    """
    list_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for p in video_paths:
        if not p.is_file():
            raise FileNotFoundError(f"列表中的视频不存在: {p}")
        # concat demuxer 要求：file 'path'
        resolved = p.resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{resolved}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("playlist %s items -> %s", len(video_paths), list_path)
    return list_path


def concat_to_file(
    list_path: Path,
    out_path: Path,
    reencode: bool = False,
) -> Path:
    """可选：把列表合成单个 mp4。"""
    from .ffmpeg_util import run_ffmpeg

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if reencode:
        args = [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(out_path),
        ]
    else:
        args = [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(out_path),
        ]
    logger.info("concat: ffmpeg %s", " ".join(args))
    proc = run_ffmpeg(args, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        # copy 失败则重编码
        if not reencode:
            logger.warning("concat copy 失败，尝试重编码: %s", (proc.stderr or "")[-500:])
            return concat_to_file(list_path, out_path, reencode=True)
        raise RuntimeError(f"ffmpeg concat 失败: {(proc.stderr or '')[-800:]}")
    return out_path
