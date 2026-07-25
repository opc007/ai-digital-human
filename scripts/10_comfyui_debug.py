#!/usr/bin/env python3
"""
本机 ComfyUI 调试脚本（5090 + 已装 ComfyUI）

用法：
  python scripts/10_comfyui_debug.py              # 只做连通/模型/工作流检查
  python scripts/10_comfyui_debug.py --smoke      # 提交一条短视频生成（较慢，占显存）
  python scripts/10_comfyui_debug.py --url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="", help="ComfyUI 地址，默认读 .env 或 8000")
    parser.add_argument("--smoke", action="store_true", help="提交一条 Wan I2V 短测")
    parser.add_argument(
        "--image",
        default="",
        help="参考图路径，默认用 data/avatars/demo/source 或生成灰图",
    )
    args = parser.parse_args()

    import os

    base = (args.url or os.getenv("COMFYUI_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    print(f"== ComfyUI 地址: {base}")

    from broadcast.comfyui_client import ComfyUIClient, load_workflow_template, workflow_path
    from broadcast.ffmpeg_util import find_ffmpeg

    client = ComfyUIClient(base)
    h = client.health()
    print("健康检查:", h)
    if not h.get("ok"):
        print(
            "\n未连上。常见原因：\n"
            "1) ComfyUI / Comfy Desktop 没开\n"
            "2) 端口不是 8188（你这台当前是 8000）\n"
            "3) 在「素材中心 / 云端配置」把 COMFYUI_BASE_URL 设成实际地址\n"
        )
        return 1

    # 系统信息
    import httpx

    stats = httpx.get(f"{base}/system_stats", timeout=10).json()
    devs = stats.get("devices") or []
    print("Comfy 版本:", (stats.get("system") or {}).get("comfyui_version"))
    for d in devs:
        print(
            " GPU:",
            d.get("name"),
            "VRAM free",
            round((d.get("vram_free") or 0) / 1024**3, 1),
            "GB /",
            round((d.get("vram_total") or 0) / 1024**3, 1),
            "GB",
        )

    # 关键模型是否在列表里
    info = httpx.get(f"{base}/object_info", timeout=60).json()
    unets = info.get("UNETLoader", {}).get("input", {}).get("required", {}).get("unet_name", [[]])[0]
    vaes = info.get("VAELoader", {}).get("input", {}).get("required", {}).get("vae_name", [[]])[0]
    clips = info.get("CLIPLoader", {}).get("input", {}).get("required", {}).get("clip_name", [[]])[0]
    need = {
        "unet": "wan2.1_i2v_480p_14B_fp16.safetensors",
        "vae": "wan_2.1_vae.safetensors",
        "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "clip_vision": "clip_vision_h.safetensors",
    }
    visions = (
        info.get("CLIPVisionLoader", {})
        .get("input", {})
        .get("required", {})
        .get("clip_name", [[]])[0]
    )
    print("\n== 模型检查（默认工作流需要） ==")
    ok_models = True
    for label, name in need.items():
        pool = {"unet": unets, "vae": vaes, "clip": clips, "clip_vision": visions}[label]
        found = name in pool
        print(("  [OK] " if found else "  [缺] "), label, name)
        if not found:
            ok_models = False
    print("  节点 WanImageToVideo:", "OK" if "WanImageToVideo" in info else "缺")
    print("  节点 CreateVideo/SaveVideo:", "OK" if "CreateVideo" in info and "SaveVideo" in info else "缺")

    wf_path = workflow_path()
    print("\n== 工作流文件 ==")
    print(" ", wf_path, "存在" if wf_path.is_file() else "不存在")
    wf = load_workflow_template()
    if not wf:
        print("  请确认 configs/comfyui/action_workflow.json")
        return 1
    print("  节点数:", len(wf))

    if not args.smoke:
        print("\n检查完成。若要真跑一条生成：")
        print("  python scripts/10_comfyui_debug.py --smoke")
        print("\n素材中心：http://127.0.0.1:8100/materials （数字人控制台默认改到 8100，避免和 Comfy 抢 8000）")
        return 0 if ok_models else 2

    # smoke generate
    if not ok_models:
        print("模型不齐，跳过 smoke")
        return 2

    # 准备参考图
    img = Path(args.image) if args.image else None
    if not img or not img.is_file():
        cand = list((ROOT / "data" / "avatars" / "demo" / "source").glob("*.*"))
        img = cand[0] if cand else None
    if not img or not img.is_file():
        # 生成一张测试图
        from PIL import Image

        img = ROOT / "data" / "temp" / "comfy_smoke.jpg"
        img.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (640, 640), (40, 80, 120)).save(img)
        print("使用纯色测试图:", img)
    else:
        print("参考图:", img)

    print("上传图片…")
    up = client.upload_image(img)
    image_name = up.get("name") or img.name
    print("  uploaded as", image_name)

    from broadcast.comfyui_client import inject_workflow

    prompt = "A friendly person waving right hand, smiling, looking at camera, indoor bright lighting, natural posture, 2 seconds"
    negative = "blurry, distorted face, extra fingers, deformed"
    workflow = inject_workflow(wf, image_name=image_name, prompt=prompt, negative=negative)

    print("提交 /prompt …（Wan 14B 首次加载可能要几分钟，请看 ComfyUI 窗口）")
    t0 = time.time()
    try:
        pid = client.queue_prompt(workflow)
    except Exception as e:
        print("提交失败:", e)
        return 3
    print("  prompt_id =", pid)

    try:
        hist = client.wait_result(pid, timeout_sec=1200, poll=3.0)
    except Exception as e:
        print("等待失败:", e)
        return 4

    outputs = hist.get("outputs") or {}
    print("完成，用时 %.1fs" % (time.time() - t0))
    print("outputs keys:", list(outputs.keys()))
    for nid, out in outputs.items():
        for k, v in out.items():
            if isinstance(v, list) and v:
                print(f"  node {nid} {k}: {v[0]}")

    # 尝试下载第一个视频
    for out in outputs.values():
        for key in ("gifs", "videos", "images"):
            for it in out.get(key) or []:
                fn = it.get("filename")
                if not fn:
                    continue
                dest = ROOT / "data" / "temp" / f"smoke_{fn}"
                try:
                    client.download_view(
                        fn,
                        subfolder=it.get("subfolder") or "",
                        folder_type=it.get("type") or "output",
                        out_path=dest,
                    )
                    print("已下载:", dest, "size", dest.stat().st_size)
                    return 0
                except Exception as e:
                    print("下载失败", e)
    print("未找到可下载文件，请到 ComfyUI output 目录查看")
    return 0


if __name__ == "__main__":
    # 可选依赖
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        pass
    raise SystemExit(main())
