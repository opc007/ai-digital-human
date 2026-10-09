"""宣讲模式画面合成：声卡 / 网站截图 / 分屏混流。

所有函数都可在无 GPU、无浏览器、无 Key 的环境下降级运行，
保证 `scripts/13_promo_setup.py --smoke` 能跑通。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .ffmpeg_util import find_ffmpeg

logger = logging.getLogger("broadcast.compose")

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
    from PIL import Image, ImageDraw, ImageFont

    out_path.parent.mkdir(parents=True, exist_ok=True)
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


# ---------- 分屏合成 ----------

def _scale_crop(tag: str, w: int, h: int) -> str:
    return (
        f"[{tag}]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}[{tag}c]"
    )


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
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError("未找到 ffmpeg，无法合成画面")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    half = width // 2

    def inp(p: Path) -> list[str]:
        # 图片用 -loop 1 播成视频流
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            return ["-loop", "1", "-framerate", "30", "-i", str(p)]
        return ["-i", str(p)]

    filt = (
        f"{_scale_crop('0:v', half, height)};"
        f"{_scale_crop('1:v', half, height)};"
        f"[0:vc][1:vc]xstack=inputs=2:layout=0_0|{half}_0,format=yuv420p[v]"
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
                "-ar", "44100"]
        if duration:
            amap += ["-t", str(duration)]
    cmd += [
        "-filter_complex", filt, *amap,
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", str(out_path),
    ]
    _run(cmd, timeout=300)
    return out_path

