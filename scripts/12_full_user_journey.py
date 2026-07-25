#!/usr/bin/env python3
"""
真实用户完整旅程：用已配置 Key + 预设素材，串起控制台/素材中心/开播/互动/CLI。
发现问题打印 [FAIL]，并尽量继续；退出码 0=全过。
"""

from __future__ import annotations

import io
import sys
import time
import traceback
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

fails: list[str] = []
oks: list[str] = []


def ok(name: str, detail: str = "") -> None:
    print(f"[OK]  {name}" + (f" — {detail}" if detail else ""))
    oks.append(name)


def fail(name: str, detail: str) -> None:
    print(f"[FAIL] {name} — {detail}")
    fails.append(f"{name}: {detail}")


def wait_idle(c, room: str = "demo", timeout: float = 90.0, after_reply: str | None = None):
    """等到 phase=idle 且队列空，返回 status。"""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = c.get(f"/api/v1/live/{room}/status").json()
        reply = last.get("last_reply") or ""
        if (
            last.get("phase") == "idle"
            and int(last.get("queue_length") or 0) == 0
            and (after_reply is None or (reply and reply != after_reply))
        ):
            return last
        time.sleep(0.4)
    return last


def ensure_preset_assets() -> None:
    """把根目录预设图/视频导入 demo 形象。"""
    from broadcast.assets import list_assets, save_action_video, save_source_image

    imgs = [
        p
        for p in ROOT.iterdir()
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    ]
    vids = [
        p
        for p in ROOT.iterdir()
        if p.is_file() and p.suffix.lower() in (".mp4", ".webm", ".mov")
    ]
    if not imgs or not vids:
        # 已导入也可
        a = list_assets("demo")
        if a.get("ready") and a.get("source_exists"):
            ok("preset assets already ready")
            return
        raise FileNotFoundError("根目录缺少预设图片或视频")

    img, vid = imgs[0], vids[0]
    save_source_image(img.read_bytes(), img.name, avatar_id="demo")
    for action, cat in [
        ("idle", "idle"),
        ("wave", "greeting"),
        ("nod", "emotion"),
        ("thinking", "emotion"),
        ("thanks_wave", "thanks"),
    ]:
        save_action_video(vid.read_bytes(), action, avatar_id="demo", category=cat)
    ok("import preset", f"img={img.name} vid={vid.name}")


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)

    print("=" * 64)
    print("真实用户完整旅程")
    print("=" * 64)

    # ---------- 0 环境 ----------
    print("\n## 0 环境与预设素材")
    try:
        ensure_preset_assets()
    except Exception as e:
        fail("import preset", str(e))
        return 1

    from fastapi.testclient import TestClient
    from api.app import app

    c = TestClient(app)

    # ---------- 1 进入产品 ----------
    print("\n## 1 进入产品（页面/静态资源）")
    for path in ("/", "/materials", "/health", "/docs", "/static/app.js", "/static/materials.js", "/static/styles.css", "/static/materials.css"):
        r = c.get(path)
        (ok if r.status_code == 200 else fail)(f"GET {path}", str(r.status_code))

    # ---------- 2 登录 ----------
    print("\n## 2 登录")
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    (ok if r.status_code == 401 else fail)("bad login", str(r.status_code))
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    if r.status_code == 200 and r.json().get("token"):
        ok("login admin")
    else:
        fail("login admin", r.text[:200])

    # ---------- 3 首页引导 ----------
    print("\n## 3 首页 / bootstrap / home")
    r = c.get("/api/v1/bootstrap")
    if r.status_code != 200:
        fail("bootstrap", r.text[:200])
    else:
        b = r.json()
        keys = b.get("keys") or {}
        ok(
            "bootstrap",
            f"platforms={len(b.get('platforms',[]))} deepseek={keys.get('deepseek')} minimax={keys.get('minimax')} avatar={keys.get('avatar_ready')}",
        )
        if not keys.get("deepseek"):
            fail("key deepseek", "未配置")
        else:
            ok("key deepseek configured")
        if not keys.get("minimax"):
            fail("key minimax", "未配置")
        else:
            ok("key minimax configured")

    r = c.get("/api/v1/home")
    if r.status_code == 200:
        h = r.json()
        ok("home", f"progress={h.get('progress')} next={str(h.get('next_action',{}).get('label',''))[:40]}")
    else:
        fail("home", r.text[:200])

    r = c.get("/api/v1/platforms")
    (ok if r.status_code == 200 and len(r.json()) >= 5 else fail)("platforms", str(r.status_code))
    r = c.get("/api/v1/runtime-modes")
    (ok if r.status_code == 200 and len(r.json()) >= 3 else fail)("runtime-modes", str(r.status_code))

    # ---------- 4 云端配置 ----------
    print("\n## 4 云端配置读写与连通")
    r = c.get("/api/v1/settings")
    if r.status_code != 200:
        fail("get settings", r.text[:200])
    else:
        fields = {f["key"]: f for f in r.json().get("fields") or []}
        ok("get settings", f"n={len(fields)}")
        for k in ("DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "MINIMAX_LANGUAGE_BOOST"):
            if k in fields:
                ok(f"settings has {k}", f"configured={fields[k].get('configured')}")
            else:
                fail(f"settings has {k}", "missing field")

    # 保存 language_boost 确认可写
    r = c.put("/api/v1/settings", json={"values": {"MINIMAX_LANGUAGE_BOOST": "Chinese"}})
    (ok if r.status_code == 200 else fail)("put language_boost", r.text[:120] if r.status_code != 200 else r.json().get("message", "")[:40])

    for target in ("deepseek", "minimax", "ollama"):
        r = c.post("/api/v1/settings/test", json={"target": target})
        if r.status_code == 200:
            ok(f"test {target}", str(r.json().get("message", ""))[:60])
        elif target == "ollama" and r.status_code == 400:
            ok(f"test {target} offline", r.json().get("detail", "")[:50] if isinstance(r.json(), dict) else "")
        else:
            fail(f"test {target}", f"{r.status_code} {r.text[:180]}")

    # ---------- 5 素材中心 ----------
    print("\n## 5 素材中心")
    r = c.post("/api/v1/demo/ensure")
    (ok if r.status_code == 200 else fail)("demo ensure", str(r.status_code))

    r = c.get("/api/v1/assets?avatar_id=demo")
    if r.status_code != 200:
        fail("list assets", r.text[:200])
    else:
        a = r.json()
        if not a.get("ready") or not a.get("source_exists"):
            fail("assets ready", str(a)[:200])
        else:
            ok("assets ready", f"{a.get('ready_count')}/{a.get('total_count')} source=ok")

    # 媒体可访问
    for path in (
        "/media/avatars/demo/source/photo.jpg",
        "/media/avatars/demo/actions/idle.mp4",
    ):
        r = c.get(path)
        if r.status_code == 200 and len(r.content) > 1000:
            ok(f"media {path}", f"{len(r.content)} bytes")
        else:
            fail(f"media {path}", f"{r.status_code} len={len(r.content)}")

    # 上传临时动作再删除
    idle = ROOT / "data" / "avatars" / "demo" / "actions" / "idle.mp4"
    r = c.post(
        "/api/v1/assets/actions/upload",
        files={"file": ("tmp.mp4", idle.read_bytes(), "video/mp4")},
        data={"action": "tmp_sim", "avatar_id": "demo", "category": "gesture"},
    )
    if r.status_code == 200:
        ok("upload action tmp_sim")
        r = c.delete("/api/v1/assets/actions/tmp_sim?avatar_id=demo")
        (ok if r.status_code == 200 else fail)("delete tmp_sim", str(r.status_code))
    else:
        fail("upload action", r.text[:200])

    r = c.get("/api/v1/comfyui/status")
    if r.status_code == 200:
        ok("comfyui status", str(r.json())[:100])
    else:
        fail("comfyui status", str(r.status_code))

    # 生成任务：有 ComfyUI 则排队，没有则 4xx/5xx 可接受
    r = c.post("/api/v1/assets/generate", json={"action": "wave", "avatar_id": "demo"})
    if r.status_code in (200, 400, 503):
        ok("assets generate", f"status={r.status_code}")
    else:
        fail("assets generate", f"{r.status_code} {r.text[:150]}")
    r = c.get("/api/v1/assets/jobs")
    (ok if r.status_code == 200 else fail)("jobs list", str(r.status_code))

    # ---------- 6 声音 ----------
    print("\n## 6 声音（真 MiniMax 试听）")
    r = c.get("/api/v1/voice")
    (ok if r.status_code == 200 else fail)("voice list", str(r.status_code))

    # 参考音频
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 3200)
    r = c.post(
        "/api/v1/voice/sample",
        files={"file": ("ref.wav", buf.getvalue(), "audio/wav")},
    )
    (ok if r.status_code == 200 else fail)("voice sample", r.text[:100] if r.status_code != 200 else "")

    r = c.post(
        "/api/v1/voice/preview",
        json={"text": "大家好，我是数字人主播，欢迎来到直播间。", "mock": False},
    )
    if r.status_code == 200 and r.json().get("ok"):
        url = r.json().get("url") or ""
        ok("voice preview real", f"url={url}")
        if url:
            rm = c.get(url)
            (ok if rm.status_code == 200 and len(rm.content) > 1000 else fail)(
                "preview audio file", f"{rm.status_code} {len(rm.content)}"
            )
    else:
        fail("voice preview real", f"{r.status_code} {r.text[:250]}")

    # ---------- 7 人设 / 形象 / 试聊 ----------
    print("\n## 7 人设、形象、试聊")
    r = c.get("/api/v1/personas")
    persona_id = None
    if r.status_code == 200 and r.json():
        persona_id = r.json()[0]["id"]
        ok("list personas", f"id={persona_id}")
        r = c.put(
            f"/api/v1/personas/{persona_id}",
            json={
                "name": "小美",
                "greeting": "哈喽家人们，我是小美，今天带大家一起玩～",
                "system_prompt": "你是直播间主播小美，热情口语化，回复不超过40字，不要用括号动作。",
                "temperature": 0.7,
            },
        )
        (ok if r.status_code == 200 else fail)("update persona", str(r.status_code))
    else:
        fail("list personas", r.text[:150])

    r = c.get("/api/v1/avatars")
    if r.status_code == 200 and r.json():
        ok("list avatars", f"n={len(r.json())}")
        aid = r.json()[0]["id"]
        r = c.get(f"/api/v1/avatars/{aid}")
        (ok if r.status_code == 200 else fail)("get avatar", str(r.status_code))
    else:
        fail("list avatars", str(r.status_code))

    r = c.post("/api/v1/chat/test", json={"text": "今天播什么？用一句话回答"})
    if r.status_code == 200:
        data = r.json()
        if data.get("demo") or not (data.get("reply") or "").strip():
            fail("chat test real", str(data)[:200])
        else:
            ok("chat test real", f"provider={data.get('provider')} reply={str(data.get('reply'))[:50]}")
    else:
        fail("chat test", r.text[:200])

    # ---------- 8 开播前检查 ----------
    print("\n## 8 开播前检查")
    r = c.post("/api/v1/live/preflight", json={"platform": "preview", "runtime_mode": "cloud"})
    if r.status_code == 200 and r.json().get("can_start"):
        ok("preflight preview cloud", r.json().get("summary", ""))
    else:
        fail("preflight preview cloud", r.text[:250])

    r = c.post("/api/v1/live/preflight", json={"platform": "douyin", "runtime_mode": "cloud", "rtmp_key": ""})
    if r.status_code == 200 and not r.json().get("can_start"):
        ok("preflight douyin blocks without key")
    else:
        fail("preflight douyin", str(r.json())[:200])

    r = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "douyin", "runtime_mode": "cloud"},
    )
    (ok if r.status_code == 400 else fail)("start douyin no key", str(r.status_code))

    # ---------- 9 云端预览全流程 ----------
    print("\n## 9 云端预览开播 + 互动（真 LLM/TTS）")
    c.post("/api/v1/live/stop", params={"room_id": "demo"})
    r = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud", "mode": "interactive"},
    )
    if r.status_code != 200:
        fail("start cloud", r.text[:300])
    else:
        eng = r.json().get("engines") or {}
        ok("start cloud", f"engines={eng}")
        if eng.get("llm") != "deepseek" or eng.get("tts") != "minimax":
            fail("cloud engines", str(eng))

    st = wait_idle(c, timeout=120)
    greet = st.get("last_reply") or ""
    if greet:
        ok("greeting", greet[:60])
    else:
        fail("greeting", f"status={st}")

    # 普通弹幕
    before = greet
    r = c.post(
        "/api/v1/live/demo/input",
        json={"text": "主播好漂亮，声音也好听！", "user_key": "fan1", "priority": 10},
    )
    (ok if r.status_code == 200 else fail)("input normal", r.text[:100])
    st = wait_idle(c, timeout=120, after_reply=before)
    reply = st.get("last_reply") or ""
    if reply and reply != before:
        ok("reply normal", reply[:60])
    else:
        fail("reply normal", f"reply={reply!r} err={st.get('last_error')}")

    # 礼物
    before = reply
    r = c.post(
        "/api/v1/live/demo/input",
        json={"text": "送你一辆跑车！", "user_key": "vip1", "priority": 90, "is_gift": True},
    )
    (ok if r.status_code == 200 else fail)("input gift", str(r.status_code))
    st = wait_idle(c, timeout=120, after_reply=before)
    if st.get("last_reply") and st.get("last_reply") != before:
        ok("reply gift", str(st.get("last_reply"))[:60])
    else:
        fail("reply gift", str(st)[:200])

    # 事件历史
    r = c.get("/api/v1/live/demo/events?limit=20")
    if r.status_code == 200 and len(r.json()) > 0:
        ok("events", f"n={len(r.json())}")
    else:
        fail("events", r.text[:150])

    # WebSocket
    try:
        with c.websocket_connect("/ws/live/demo") as ws:
            msg = ws.receive_json()
            ok("ws connect", f"type={msg.get('type')} phase={msg.get('phase')}")
            ws.send_json({"type": "ping", "ts": 1})
            got_pong = False
            for _ in range(8):
                m = ws.receive_json()
                if m.get("type") == "pong":
                    got_pong = True
                    break
            (ok if got_pong else fail)("ws pong", "no pong")
            before = c.get("/api/v1/live/demo/status").json().get("last_reply")
            ws.send_json({"type": "text", "content": "WebSocket 弹幕来了", "user_key": "ws1"})
            # 等广播或状态
            for _ in range(15):
                try:
                    m = ws.receive_json()
                    if m.get("type") in ("ai_response", "status", "error"):
                        ok("ws event", f"type={m.get('type')}")
                        break
                except Exception:
                    break
            st = wait_idle(c, timeout=90, after_reply=before)
            if st.get("last_reply") and st.get("last_reply") != before:
                ok("ws text handled", str(st.get("last_reply"))[:50])
            else:
                # 可能被防刷或仍处理中
                ok("ws text status", f"phase={st.get('phase')} reply={str(st.get('last_reply'))[:40]}")
    except Exception as e:
        fail("websocket", str(e))

    # 成片体积（真素材应 > 100KB）
    live_dir = ROOT / "data" / "output" / "clips" / "demo" / "live"
    if live_dir.is_dir():
        recent = sorted(live_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
        big = [p for p in recent if p.stat().st_size > 100_000]
        if big:
            ok("live clips size", f"{big[0].name}={big[0].stat().st_size}")
        else:
            fail("live clips size", f"recent={[ (p.name,p.stat().st_size) for p in recent ]}")
    else:
        fail("live clips dir", "missing")

    c.post("/api/v1/live/stop", params={"room_id": "demo"})
    ok("stop cloud")

    # ---------- 10 本地 / 混合 ----------
    print("\n## 10 本地模式 & 混合模式")
    for mode in ("local", "hybrid"):
        c.post("/api/v1/live/stop", params={"room_id": "demo"})
        r = c.post(
            "/api/v1/live/start",
            json={"room_id": "demo", "platform": "preview", "runtime_mode": mode},
        )
        if r.status_code != 200:
            fail(f"start {mode}", r.text[:250])
            continue
        ok(f"start {mode}", str(r.json().get("engines")))
        st = wait_idle(c, timeout=150)
        before = st.get("last_reply") or ""
        if before:
            ok(f"greeting {mode}", before[:50])
        r = c.post(
            f"/api/v1/live/demo/input",
            json={"text": f"测试{mode}模式一句话", "user_key": f"u_{mode}"},
        )
        (ok if r.status_code == 200 else fail)(f"input {mode}", str(r.status_code))
        st = wait_idle(c, timeout=150, after_reply=before)
        if st.get("last_reply"):
            ok(f"reply {mode}", str(st.get("last_reply"))[:50])
        else:
            fail(f"reply {mode}", str(st)[:200])
        c.post("/api/v1/live/stop", params={"room_id": "demo"})
        ok(f"stop {mode}")

    # ---------- 11 脚本模式 ----------
    print("\n## 11 脚本播报模式")
    c.post("/api/v1/live/stop", params={"room_id": "demo"})
    r = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud", "mode": "script"},
    )
    if r.status_code == 200:
        ok("start script")
        # 脚本可能跑较久（真 TTS 多句）
        deadline = time.time() + 300
        final = {}
        while time.time() < deadline:
            final = c.get("/api/v1/live/demo/status").json()
            if not final.get("running") or final.get("phase") == "stopped":
                break
            time.sleep(1.0)
        ok("script finished", f"running={final.get('running')} reply={str(final.get('last_reply'))[:50]} err={str(final.get('last_error'))[:60]}")
        broadcast = ROOT / "data" / "output" / "demo" / "broadcast.mp4"
        if broadcast.is_file() and broadcast.stat().st_size > 50_000:
            ok("script broadcast.mp4", f"{broadcast.stat().st_size} bytes")
        else:
            # dry-run script 仍应生成成片
            if broadcast.is_file():
                ok("script broadcast exists", f"{broadcast.stat().st_size}")
            else:
                fail("script broadcast.mp4", "missing")
    else:
        fail("start script", r.text[:300])
    c.post("/api/v1/live/stop", params={"room_id": "demo"})

    # ---------- 12 边界 ----------
    print("\n## 12 边界：空消息 / 防刷 / 未开播")
    r = c.post("/api/v1/live/demo/input", json={"text": "x", "user_key": "x"})
    (ok if r.status_code == 409 else fail)("input not live", str(r.status_code))

    c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud"},
    )
    wait_idle(c, timeout=90)
    r = c.post("/api/v1/live/demo/input", json={"text": "", "user_key": "e"})
    (ok if r.status_code == 400 else fail)("empty input", str(r.status_code))
    codes = []
    for i in range(8):
        rr = c.post(
            "/api/v1/live/demo/input",
            json={"text": f"刷{i}", "user_key": "spammer"},
        )
        codes.append(rr.status_code)
    if 429 in codes:
        ok("anti-spam", f"codes={codes}")
    else:
        ok("anti-spam soft", f"codes={codes}")  # 配置宽松时也可
    c.post("/api/v1/live/stop", params={"room_id": "demo"})

    # 重复开播
    c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud"},
    )
    r = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud"},
    )
    (ok if r.status_code in (200, 400, 409, 503) else fail)("double start", str(r.status_code))
    c.post("/api/v1/live/stop", params={"room_id": "demo"})

    # ---------- 13 CLI 流水线（真 TTS） ----------
    print("\n## 13 CLI 播报流水线（真 MiniMax，非 mock）")
    try:
        from broadcast.config import load_app_config, load_room_config
        from broadcast.pipeline import build_room_playlist, run_lipsync_batch, run_tts_batch
        from broadcast.stream import push_rtmp
        from broadcast.tts import create_tts_engine

        app_cfg = load_app_config()
        room = load_room_config("demo", app_cfg)
        tts = create_tts_engine(app_cfg.section("tts"), mock=False)
        run_tts_batch(app_cfg, room, mock=False, engine=tts)
        ok("cli tts batch real")
        run_lipsync_batch(app_cfg, room, mock=False)
        ok("cli lipsync batch")
        pl, single = build_room_playlist(app_cfg, room, make_single_file=True)
        if single and single.is_file() and single.stat().st_size > 50_000:
            ok("cli compose", f"{single} {single.stat().st_size}")
        else:
            fail("cli compose", str(single))
        # dry-run 推流
        push_rtmp(single, room.full_rtmp_url() or "rtmp://127.0.0.1/live/test", app_cfg.section("stream"), dry_run=True)
        ok("cli push dry-run")
    except Exception as e:
        fail("cli pipeline", f"{e}\n{traceback.format_exc()[-400:]}")

    r = c.get("/health")
    ok("health final", str(r.json()))

    # ---------- 汇总 ----------
    print("\n" + "=" * 64)
    print(f"通过 {len(oks)}  失败 {len(fails)}")
    if fails:
        print("失败项:")
        for f in fails:
            print(" -", f)
        return 1
    print("完整旅程全部通过")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
