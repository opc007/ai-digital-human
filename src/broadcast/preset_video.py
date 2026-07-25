"""
从一张正脸图生成「可直接用于直播」的预设动作视频。

观感目标（对齐 Vidu 式「活人感」）：
- 待机 = 慢、小、顺的「呼吸」：几乎察觉不到位移，但人是活的
- 禁止明显抖、晃、Ken Burns 拉扯
- 竖屏 1080×1920，时长取完整呼吸周期，便于无缝循环

实现要点：
- zoompan 在整数像素上会抖 → 先 2× 分辨率做微动，再 lanczos 缩回
- 呼吸周期放慢（约 5s），幅度极小；并叠一点点亮度起伏
- 不依赖 ComfyUI；本机 FFmpeg 即可
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from .assets import (
    DEFAULT_ACTIONS,
    avatar_root,
    ensure_avatar_dirs,
    get_or_create_meta,
    list_assets,
    save_meta,
)
from .avatar_meta import ActionMeta, AvatarMeta
from .ffmpeg_util import find_ffmpeg

logger = logging.getLogger("broadcast.preset_video")

# fps 与呼吸周期对齐：period_frames = round(period_sec * fps)
# 时长 = 整周期，保证首尾相位相同，循环不跳
PRESET_FPS = 30

# 各动作：以「慢呼吸」为基线；其它动作只略加强，仍避免抖
ACTION_MOTIONS: dict[str, dict[str, Any]] = {
    "idle": {
        "label": "待机呼吸",
        # 约 5s 一个呼吸；缩放幅度 ≈0.35%；几乎无平移
        "period_sec": 5.0,
        "z_base": 1.006,
        "z_amp": 0.0035,
        "y_amp": 1.2,  # 在 2× 画布上的像素，缩回后约 0.6px
        "x_amp": 0.4,
        "bright_amp": 0.012,
        "cycles": 1,
    },
    "wave": {
        "label": "打招呼",
        "period_sec": 4.0,
        "z_base": 1.008,
        "z_amp": 0.006,
        "y_amp": 2.0,
        "x_amp": 1.2,
        "bright_amp": 0.01,
        "cycles": 1,
    },
    "nod": {
        "label": "点头感",
        "period_sec": 3.2,
        "z_base": 1.007,
        "z_amp": 0.004,
        "y_amp": 3.5,  # 略偏上下，仍很克制
        "x_amp": 0.2,
        "bright_amp": 0.008,
        "cycles": 1,
    },
    "thinking": {
        "label": "思考微动",
        "period_sec": 5.5,
        "z_base": 1.007,
        "z_amp": 0.003,
        "y_amp": 1.0,
        "x_amp": 0.6,
        "bright_amp": 0.01,
        "cycles": 1,
    },
    "thanks_wave": {
        "label": "感谢",
        "period_sec": 3.8,
        "z_base": 1.008,
        "z_amp": 0.0055,
        "y_amp": 2.2,
        "x_amp": 1.0,
        "bright_amp": 0.01,
        "cycles": 1,
    },
}


def _motion_seconds(motion: dict[str, Any]) -> float:
    period = float(motion.get("period_sec") or 5.0)
    cycles = int(motion.get("cycles") or 1)
    return max(period * cycles, 2.0)


# 兼容旧代码读取 seconds
for _name, _m in ACTION_MOTIONS.items():
    _m["seconds"] = _motion_seconds(_m)


def _find_source_image(avatar_id: str) -> Path | None:
    root = avatar_root(avatar_id)
    meta = get_or_create_meta(avatar_id)
    candidates = [
        root / meta.source_image,
        root / "source" / "photo.jpg",
        root / "source" / "photo.png",
        root / "source" / "photo.jpeg",
        root / "source" / "photo.webp",
    ]
    src_dir = root / "source"
    if src_dir.is_dir():
        for p in sorted(src_dir.iterdir()):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.is_file():
                candidates.append(p)
    for c in candidates:
        if c.is_file() and c.stat().st_size > 100:
            return c
    return None


def generate_action_from_image(
    image_path: Path,
    out_path: Path,
    *,
    action: str = "idle",
    width: int = 1080,
    height: int = 1920,
    fps: int = PRESET_FPS,
) -> Path:
    """单张图 → 指定动作的微动 mp4（慢呼吸、抗抖）。"""
    ff = find_ffmpeg()
    if not ff:
        raise FileNotFoundError("未找到 FFmpeg，无法生成预设视频")
    if not image_path.is_file():
        raise FileNotFoundError(f"原图不存在: {image_path}")

    motion = ACTION_MOTIONS.get(action) or ACTION_MOTIONS["idle"]
    period = float(motion.get("period_sec") or 5.0)
    seconds = _motion_seconds(motion)
    # 周期帧数取整，保证 sin 首尾相位闭合
    period_frames = max(int(round(period * fps)), fps)
    z_base = float(motion.get("z_base") or 1.006)
    z_amp = float(motion.get("z_amp") or 0.0035)
    y_amp = float(motion.get("y_amp") or 1.2)
    x_amp = float(motion.get("x_amp") or 0.4)
    bright_amp = float(motion.get("bright_amp") or 0.01)

    # 2× 超采样：减轻 zoompan 整数像素台阶造成的「抖」
    sw, sh = width * 2, height * 2
    z_expr = f"{z_base}+{z_amp}*sin(2*PI*on/{period_frames})"
    x_expr = f"iw/2-(iw/zoom/2)+({x_amp}*sin(2*PI*on/{period_frames}*0.85))"
    y_expr = f"ih/2-(ih/zoom/2)+({y_amp}*sin(2*PI*on/{period_frames}))"
    # 亮度与缩放同相：吸气略亮，更像「活」
    bright_expr = f"{bright_amp}*sin(2*PI*t/{period})"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    vf = (
        # 铺满竖屏（contain 逻辑：先 enlarge 再 crop 中心）
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={sw}:{sh},"
        # 慢呼吸微动（在 2× 画布上）
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
        f":d=1:s={sw}x{sh}:fps={fps},"
        # 缩回输出分辨率 + 轻微亮度呼吸
        f"scale={width}:{height}:flags=lanczos,"
        f"eq=brightness='{bright_expr}':contrast=1.01,"
        f"trim=duration={seconds},setpts=PTS-STARTPTS,"
        f"format=yuv420p"
    )

    cmd = [
        ff,
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=mono:sample_rate=44100",
        "-vf",
        vf,
        "-t",
        str(seconds),
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    logger.info(
        "preset breath action=%s period=%.1fs amp=z%.4f -> %s",
        action,
        period,
        z_amp,
        out_path.name,
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.is_file():
        err = (proc.stderr or proc.stdout or "")[-1200:]
        raise RuntimeError(f"生成 {action} 失败: {err}")
    return out_path


def generate_preset_pack(
    avatar_id: str = "demo",
    *,
    actions: list[str] | None = None,
    force: bool = True,
    width: int = 1080,
    height: int = 1920,
) -> dict[str, Any]:
    """
    一键：用已上传正脸图生成整套预设动作。
    force=True 时覆盖已有动作视频。
    """
    ensure_avatar_dirs(avatar_id)
    root = avatar_root(avatar_id)
    source = _find_source_image(avatar_id)
    if not source:
        raise FileNotFoundError("请先上传一张正脸照片（素材中心 → 形象）")

    names = actions or [a["name"] for a in DEFAULT_ACTIONS]
    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    errors: list[str] = []

    for name in names:
        rel = f"actions/{name}.mp4"
        out = root / rel
        if out.is_file() and not force:
            skipped.append(name)
            continue
        try:
            generate_action_from_image(
                source,
                out,
                action=name if name in ACTION_MOTIONS else "idle",
                width=width,
                height=height,
            )
            created.append(
                {
                    "name": name,
                    "path": rel,
                    "url": f"/media/avatars/{avatar_id}/{rel}",
                    "size": out.stat().st_size,
                    "label": (ACTION_MOTIONS.get(name) or {}).get("label") or name,
                }
            )
        except Exception as e:
            logger.exception("preset %s failed", name)
            errors.append(f"{name}: {e}")

    meta = get_or_create_meta(avatar_id)
    by_default = {a["name"]: a for a in DEFAULT_ACTIONS}
    actions_meta: list[ActionMeta] = []
    for d in DEFAULT_ACTIONS:
        n = d["name"]
        actions_meta.append(
            ActionMeta(
                name=n,
                file=f"actions/{n}.mp4",
                duration_ms=int(_motion_seconds(ACTION_MOTIONS.get(n) or ACTION_MOTIONS["idle"]) * 1000),
                category=d.get("category") or "gesture",
            )
        )
    for a in meta.actions:
        if a.name not in by_default:
            actions_meta.append(a)

    src_rel = meta.source_image or "source/photo.jpg"
    try:
        src_rel = source.relative_to(root).as_posix()
    except Exception:
        pass

    save_meta(
        AvatarMeta(
            id=avatar_id,
            name=meta.name or "我的形象",
            source_image=src_rel,
            actions=actions_meta,
        ),
        avatar_id,
    )

    assets = list_assets(avatar_id)
    ok = bool(created) and assets.get("ready")
    return {
        "ok": ok or (not errors and assets.get("ready")),
        "source": str(source),
        "source_url": assets.get("source_url"),
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "assets": assets,
        "message": (
            f"已从照片生成 {len(created)} 个慢呼吸微动视频，可直接开播"
            if created
            else ("未生成新文件" + (f"：{errors[0]}" if errors else ""))
        ),
        "tips": [
            "待机是慢而小的呼吸感，不是晃头抖屏。",
            "有弹幕时再切「说话」口型视频；合成过程不遮挡画面。",
            "若仍不满意，可上传真人动作视频覆盖对应动作。",
        ],
    }
