#!/usr/bin/env python3
"""宣讲模式一键配置 + 冒烟测试。

用法：
    python scripts/13_promo_setup.py --room promo          # 生成网站截图等物料
    python scripts/13_promo_setup.py --room promo --smoke  # 再加：KB检索/分屏合成/mock全链路

不需要任何 Key 也能跑（截图无浏览器时降级为占位图，LLM/TTS/口型走 mock）。
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("promo_setup")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", default="promo")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    from broadcast.config import load_app_config, load_room_config

    app = load_app_config()
    room = load_room_config(args.room, app)
    promo = {**(app.section("promo") or {}), **room.promo.model_dump(exclude_none=True)}
    print("== 宣讲配置 ==")
    for k in ("enabled", "layout", "product_name", "website_url", "idle_seconds",
              "knowledge_dir", "kb_top_k"):
        print(f"  {k}: {promo.get(k)}")
    if not promo.get("enabled"):
        print("!! promo.enabled=false，本房间未开启宣讲模式")
        return 2

    # 1) 知识库
    from engines.knowledge import KnowledgeBase

    kb_path = Path(str(promo.get("knowledge_dir") or "knowledge"))
    if not kb_path.is_absolute():
        kb_path = app.root / kb_path
    _ua = promo.get("kb_aliases")
    kb = KnowledgeBase(kb_path, use_aliases=True if _ua is None else bool(_ua))
    print(f"== 知识库 == {len(kb.files)} 文件 / {len(kb.chunks)} 片段")
    lines = kb.promo_lines(str(app.root / str(promo.get("promo_script") or "knowledge/promo_script.md")))
    print(f"== 宣讲稿 == {len(lines)} 条")

    # 2) 网站截图
    from broadcast import compose

    out_img = app.output_dir / "promo" / "website.png"
    url = str(promo.get("website_url") or "")
    img = compose.capture_website(url, out_img, product_name=str(promo.get("product_name") or ""))
    print(f"== 网站截图 == {img} ({img.stat().st_size // 1024} KB)")

    if not args.smoke:
        print("\n下一步：python scripts/07_run_api.py  起控制台，或看 README 宣讲模式章节")
        return 0

    # 3) KB 检索冒烟
    print("== KB 检索冒烟 ==")
    top_k = int(promo.get("kb_top_k") or 3)
    for q in ("怎么收费", "和剪映有什么区别", "新手不会用怎么办"):
        hits = kb.search(q, top_k=top_k)
        tag = hits[0].heading if hits else "(无命中)"
        print(f"  Q: {q}  -> 命中{len(hits)}条，首条[{tag}]")
        assert hits, f"检索无命中: {q}"

    # 3b) 同义召回：观众问法与知识库用词不同，靠同义组兜底（关掉别名则应零命中）
    print("== 同义召回冒烟 ==")
    if promo.get("kb_aliases", True):
        hit = kb.search("贵不贵", top_k=top_k)
        print(f"  Q: 贵不贵  -> 命中{len(hit)}条，首条[{hit[0].heading if hit else '(无命中)'}]")
        assert hit and "价格" in hit[0].heading, "同义召回失效：问「贵不贵」没命中价格段"
        kb_noalias = KnowledgeBase(kb_path, use_aliases=False)
        assert not kb_noalias.search("贵不贵", top_k=top_k), \
            "关闭别名后仍命中，说明别名开关没生效"
        print("  关闭别名后「贵不贵」零命中 ✅（开关生效）")

    # 3c) IDF 防假阳性：无关闲聊不得命中任何知识库段，否则会把错内容喂给模型
    print("== 无关问题防误命中冒烟 ==")
    for q in ("今天天气怎么样", "你会唱歌吗"):
        noise = kb.search(q, top_k=top_k)
        print(f"  Q: {q}  -> 命中{len(noise)}条")
        assert not noise, f"无关问题误命中知识库: {q} -> {noise[0].heading if noise else ''}"

    # 4) 分屏合成冒烟（需要 ffmpeg + 占位动作视频）
    print("== 分屏合成冒烟 ==")
    import subprocess

    actions = app.root / "data" / "avatars" / "demo" / "actions"
    if not (actions / "idle.mp4").is_file():
        print("  生成占位动作视频...")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_placeholder_actions.py")],
                       check=True, capture_output=True)
    split_out = app.output_dir / "promo" / "smoke_split.mp4"
    compose.compose_split(img, actions / "idle.mp4", split_out, duration=3.0)
    print(f"  分屏成片: {split_out} ({split_out.stat().st_size // 1024} KB)")

    # 5) mock 全链路：起编排器，走 greeting + 提问 + 闲时宣讲
    print("== mock 全链路冒烟 ==")
    from broadcast.config import RoomConfig  # noqa
    from orchestrator.live import LiveOrchestrator, InputItem

    events: list[dict] = []
    orc = LiveOrchestrator(app, room, mock=True, dry_run_stream=True,
                           on_event=events.append)
    assert orc.promo_enabled and orc.kb is not None
    orc.promo_cfg["idle_seconds"] = 2  # 冒烟加速
    orc.start(mode="interactive")
    time.sleep(6)   # greeting(TTS mock 1.5s音频+合成) + 一次闲时宣讲
    ok, _ = orc.enqueue(InputItem(text="你们平台怎么收费", user_key="u1"))
    assert ok
    time.sleep(8)   # 等回答播完
    orc.stop()
    replies = [e.get("text", "") for e in events if e.get("type") == "ai_response"]
    print(f"  收到 {len(replies)} 条 AI 回复")
    for r in replies:
        print(f"    - {r[:60]}")
    assert any("梦梦" in r or "AI电影梦" in r or "收费" in r or "扣费" in r for r in replies), \
        "回复未体现知识库/宣讲内容"
    print("\n全部冒烟通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
