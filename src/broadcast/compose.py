"""宣讲模式画面合成：声卡 / 网站截图 / 分屏混流。

所有函数都可在无 GPU、无浏览器、无 Key 的环境下降级运行，
保证 `scripts/13_promo_setup.py --smoke` 能跑通。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .ffmpeg_util import find_ffmpeg, find_ffprobe

logger = logging.getLogger("broadcast.compose")

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
DEFAULT_FPS = 25.0

CJK_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]


def find_cjk_font() -> str | None:
    for p in CJK_FONT_CANDIDATES:
        if Path(p).is_file():
            return p
    return None


def _run(cmd: list[str], timeout: int = 120) -> None:
    logger.info("compose: %s", " ".join(cmd[:6]) + " ...")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)


# ---------- 网站截图 ----------

def capture_website(url: str, out_path: Path, *, width: int = 540, height: int = 1920,
                    product_name: str = "") -> Path:
    """抓取网站首屏。playwright/chromium 优先，缺失时降级为品牌占位图。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    err = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page(viewport={"width": width, "height": height})
            pg.goto(url, wait_until="networkidle", timeout=30000)
            pg.wait_for_timeout(1500)
            pg.screenshot(path=str(out_path), full_page=False)
            b.close()
        logger.info("网站截图成功(playwright): %s", url)
        return out_path
    except Exception as e:
        err = e
        logger.warning("playwright 截图失败: %s", e)

    for exe in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if shutil.which(exe):
            try:
                subprocess.run(
                    [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
                     f"--window-size={width},{height}",
                     f"--screenshot={out_path}", url],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=60,
                )
                logger.info("网站截图成功(%s): %s", exe, url)
                return out_path
            except Exception as e2:
                err = e2
                logger.warning("%s 截图失败: %s", exe, e2)

    logger.warning("无可用浏览器，生成品牌占位图 (%s)", err)
    return make_website_placeholder(out_path, url, product_name, width=width, height=height)


def make_website_placeholder(out_path: Path, url: str, product_name: str = "",
                             *, width: int = 540, height: int = 1920) -> Path:
    """品牌占位图。PIL 可用时画文字版；PIL 缺失时降级为 ffmpeg 纯色图。

    本函数是 capture_website() 的最后一级降级，**不允许抛异常**。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:  # Pillow 未安装
        logger.warning("Pillow 不可用，降级为 ffmpeg 纯色占位图: %s", e)
        return _solid_placeholder(out_path, width=width, height=height)

    img = Image.new("RGB", (width, height), (24, 28, 48))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, 14], fill=(90, 140, 255))
    fb = find_cjk_font()
    try:
        font = ImageFont.truetype(fb, 52) if fb else ImageFont.load_default()
        small = ImageFont.truetype(fb, 30) if fb else ImageFont.load_default()
    except Exception:
        font = small = ImageFont.load_default()

    def center_text(y: int, text: str, fnt, fill=(255, 255, 255)):
        bbox = d.textbbox((0, 0), text, font=fnt)
        d.text(((width - (bbox[2] - bbox[0])) / 2, y), text, font=fnt, fill=fill)

    center_text(height // 2 - 80, product_name or "产品官网", font)
    center_text(height // 2 + 20, url, small, fill=(150, 170, 200))
    center_text(height // 2 + 90, "（浏览器不可用时的占位图）", small, fill=(110, 120, 140))
    img.save(out_path)
    return out_path


def _solid_placeholder(out_path: Path, *, width: int = 540, height: int = 1920) -> Path:
    """连 Pillow 都没有时的最终兜底：用 ffmpeg 拉一张纯色 PNG。"""
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        try:
            _run([
                ffmpeg, "-y",
                "-f", "lavfi", "-i", f"color=c=0x181c30:s={width}x{height}",
                "-frames:v", "1", str(out_path),
            ], timeout=30)
            if out_path.is_file() and out_path.stat().st_size > 0:
                return out_path
        except Exception as e:
            logger.warning("ffmpeg 纯色占位图失败: %s", e)
    # 最后的最后：写一个最小合法 PNG（1x1 深色），保证调用方拿得到文件
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    out_path.write_bytes(png)
    return out_path


# ---------- 分屏合成 ----------

def _scale_crop(tag: str, w: int, h: int) -> str:
    return (
        f"[{tag}]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}[{tag}c]"
    )


def _is_image(p: Path) -> bool:
    return p.suffix.lower() in IMAGE_SUFFIXES


def probe_video(path: Path) -> tuple[float, float]:
    """返回 (fps, duration_sec)；探测不到返回默认值。"""
    exe = find_ffprobe()
    if not exe or not path.is_file() or _is_image(path):
        return (DEFAULT_FPS, 0.0)
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate,duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.split()
    except Exception as e:
        logger.warning("ffprobe 失败 %s: %s", path.name, e)
        return (DEFAULT_FPS, 0.0)
    fps, dur = DEFAULT_FPS, 0.0
    for tok in out:
        if "/" in tok:
            num, _, den = tok.partition("/")
            try:
                n, d = float(num), float(den)
                if d > 0 and n > 0:
                    fps = n / d
            except ValueError:
                pass
        else:
            try:
                dur = float(tok)
            except ValueError:
                pass
    if fps <= 0 or fps > 120:
        fps = DEFAULT_FPS
    return (fps, max(0.0, dur))


def compose_split(
    left: Path,
    right: Path,
    out_path: Path,
    *,
    width: int = 1080,
    height: int = 1920,
    duration: float | None = 30.0,
    audio: Path | None = None,
    use_second_audio: bool = False,
) -> Path:
    """左右分屏合成。left/right 可为视频或图片。

    音频三选一：audio=外部音频文件；use_second_audio=直接用 right 视频自带音频；
    都不给则垫静音。

    实现要点（勿改）：
    图片输入用 `-loop 1` 构成**无限流**，若用 `-t` 或裸 `-shortest` 收尾，
    ffmpeg 会去 drain 这个无限输入 → 挂死不出片；且图片与视频帧率不一致时
    xstack 时间戳会错乱（输出时长远小于帧数）。因此这里：
      1. 图片输入的 -framerate 与右侧视频帧率对齐；
      2. 滤镜链末端用 fps= 归一化时间戳；
      3. 用 -frames:v 精确限定帧数来收尾（不用 -t）。
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError("未找到 ffmpeg，无法合成画面")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    half = width // 2

    right_fps, right_dur = probe_video(right)
    if duration is None or duration <= 0:
        duration = right_dur if right_dur > 0 else 30.0
    fps = right_fps or DEFAULT_FPS
    nframes = max(1, int(round(duration * fps)))

    def inp(p: Path) -> list[str]:
        # 图片用 -loop 1 播成视频流；framerate 必须与右侧视频一致
        if _is_image(p):
            return ["-loop", "1", "-framerate", f"{fps:g}", "-i", str(p)]
        return ["-i", str(p)]

    filt = (
        f"{_scale_crop('0:v', half, height)};"
        f"{_scale_crop('1:v', half, height)};"
        f"[0:vc][1:vc]xstack=inputs=2:layout=0_0|{half}_0,"
        f"fps={fps:g},format=yuv420p[v]"
    )
    cmd = [ffmpeg, "-y", *inp(left), *inp(right)]
    if use_second_audio:
        # right 自带音频（口型成片已混好 TTS 音轨），直接沿用
        amap = ["-map", "[v]", "-map", "1:a", "-c:a", "aac", "-b:a", "128k",
                "-ar", "44100", "-shortest"]
    elif audio and audio.is_file():
        cmd += ["-i", str(audio)]
        amap = ["-map", "[v]", "-map", "2:a", "-c:a", "aac", "-b:a", "128k",
                "-ar", "44100", "-shortest"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        amap = ["-map", "[v]", "-map", "2:a", "-c:a", "aac", "-b:a", "128k",
                "-ar", "44100", "-t", f"{duration:.3f}"]
    cmd += [
        "-filter_complex", filt, *amap,
        "-frames:v", str(nframes),
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", str(out_path),
    ]
    _run(cmd, timeout=300)
    return out_path

