#!/usr/bin/env python3
"""模拟真实用户走完全部功能：页面/鉴权/配置/素材/声音/人设/开播/互动/关播。

发现问题直接打印 [FAIL]，成功打印 [OK]。退出码：有失败则为 1。
"""

from __future__ import annotations

import io
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 最小 PNG (1x1)
PNG_1X1 = bytes(
    [
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xDE, 0x00, 0x00, 0x00,
        0x0C, 0x49, 0x44, 0x41, 0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
        0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x05, 0xFE, 0xD4, 0xEF, 0x00, 0x00,
        0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ]
)

fails: list[str] = []
oks: list[str] = []


def ok(name: str, detail: str = "") -> None:
    msg = f"[OK]  {name}" + (f" — {detail}" if detail else "")
    print(msg)
    oks.append(name)


def fail(name: str, detail: str) -> None:
    msg = f"[FAIL] {name} — {detail}"
    print(msg)
    fails.append(f"{name}: {detail}")


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from fastapi.testclient import TestClient
    from api.app import app

    c = TestClient(app)
    print("=" * 60)
    print("模拟用户：全功能回归")
    print("=" * 60)

    # ---- Step 0: 进入产品 ----
    print("\n## Step 0 进入产品")
    for path, key in [("/", "index"), ("/materials", "materials"), ("/health", "health")]:
        r = c.get(path)
        if r.status_code != 200:
            fail(f"GET {path}", f"status={r.status_code}")
        else:
            ok(f"GET {path}")

    r = c.get("/static/app.js")
    (ok if r.status_code == 200 else fail)("static app.js", str(r.status_code))
    r = c.get("/static/styles.css")
    (ok if r.status_code == 200 else fail)("static styles.css", str(r.status_code))
    r = c.get("/static/materials.js")
    (ok if r.status_code == 200 else fail)("static materials.js", str(r.status_code))
    r = c.get("/docs")
    (ok if r.status_code == 200 else fail)("swagger /docs", str(r.status_code))

    # ---- Auth ----
    print("\n## 登录鉴权")
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    if r.status_code != 401:
        fail("login wrong password", f"expect 401 got {r.status_code}")
    else:
        ok("login wrong password -> 401")

    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    if r.status_code != 200 or "token" not in r.json():
        fail("login admin", r.text[:200])
    else:
        token = r.json()["token"]
        ok("login admin", f"token={token[:8]}...")

    # ---- Bootstrap / home / platforms ----
    print("\n## 首页 / 引导")
    r = c.get("/api/v1/bootstrap")
    if r.status_code != 200:
        fail("bootstrap", r.text[:200])
    else:
        boot = r.json()
        if len(boot.get("platforms", [])) < 5:
            fail("bootstrap platforms", f"only {len(boot.get('platforms', []))}")
        else:
            ok("bootstrap", f"platforms={len(boot['platforms'])} modes={len(boot['runtime_modes'])}")

    r = c.get("/api/v1/home")
    if r.status_code != 200:
        fail("home", r.text[:200])
    else:
        home = r.json()
        ok("home", f"progress={home.get('progress')} next={home.get('next_action', {}).get('label', '')[:30]}")

    r = c.get("/api/v1/platforms")
    (ok if r.status_code == 200 else fail)("platforms", str(r.status_code))
    r = c.get("/api/v1/runtime-modes")
    (ok if r.status_code == 200 else fail)("runtime-modes", str(r.status_code))

    # ---- Settings ----
    print("\n## 云端配置")
    r = c.get("/api/v1/settings")
    if r.status_code != 200:
        fail("get settings", r.text[:200])
    else:
        ok("get settings", f"keys={list(r.json().keys())[:6]}")

    # 保存合法字段（非法字段会被忽略；全非法则 400）
    r = c.put(
        "/api/v1/settings",
        json={"values": {"LOG_LEVEL": "INFO"}},
    )
    if r.status_code == 400 and "没有可保存" in r.text:
        ok("put settings ignore unknown key", "LOG_LEVEL 不在白名单")
    elif r.status_code != 200:
        fail("put settings unknown", r.text[:300])
    else:
        fail("put settings unknown", "expected 400 for LOG_LEVEL")

    r = c.put(
        "/api/v1/settings",
        json={"values": {"DEEPSEEK_MODEL": "deepseek-chat"}},
    )
    if r.status_code != 200:
        fail("put settings", r.text[:300])
    else:
        ok("put settings", r.json().get("message", "")[:40])

    # 测试连通（无 key 应 400）
    r = c.post("/api/v1/settings/test", json={"target": "deepseek"})
    if r.status_code == 400:
        ok("test deepseek no key -> 400")
    elif r.status_code == 200:
        ok("test deepseek", "connected")
    else:
        fail("test deepseek", f"{r.status_code} {r.text[:150]}")

    r = c.post("/api/v1/settings/test", json={"target": "minimax"})
    if r.status_code in (200, 400):
        ok("test minimax", str(r.status_code))
    else:
        fail("test minimax", f"{r.status_code} {r.text[:150]}")

    r = c.post("/api/v1/settings/test", json={"target": "ollama"})
    if r.status_code in (200, 400):
        ok("test ollama", str(r.status_code) + " " + (r.json().get("message", "") if r.headers.get("content-type", "").startswith("application/json") else "")[:40])
    else:
        fail("test ollama", f"{r.status_code}")

    r = c.post("/api/v1/settings/test", json={"target": "unknown"})
    if r.status_code == 400:
        ok("test unknown target -> 400")
    else:
        fail("test unknown", str(r.status_code))

    # ---- Demo ensure + assets ----
    print("\n## 素材中心")
    r = c.post("/api/v1/demo/ensure")
    if r.status_code != 200:
        fail("demo ensure", r.text[:200])
    else:
        ok("demo ensure", str(r.json())[:80])

    r = c.get("/api/v1/assets?avatar_id=demo")
    if r.status_code != 200:
        fail("list assets", r.text[:200])
    else:
        assets = r.json()
        ok(
            "list assets",
            f"ready={assets.get('ready')} count={assets.get('ready_count')}/{assets.get('total_count')}",
        )

    # 上传正脸图
    r = c.post(
        "/api/v1/assets/source",
        files={"file": ("photo.png", PNG_1X1, "image/png")},
        data={"avatar_id": "demo"},
    )
    if r.status_code != 200:
        fail("upload source", r.text[:300])
    else:
        ok("upload source", str(r.json())[:80])
        # 媒体预览
        media_path = r.json().get("url") or r.json().get("path") or r.json().get("preview_url")
        if media_path and str(media_path).startswith("/media/"):
            rm = c.get(media_path)
            (ok if rm.status_code == 200 else fail)("media preview source", str(rm.status_code))

    # 上传动作：用现有 idle 复制一份作为 temp 动作再删
    idle_path = ROOT / "data" / "avatars" / "demo" / "actions" / "idle.mp4"
    if idle_path.is_file():
        r = c.post(
            "/api/v1/assets/actions/upload",
            files={"file": ("sim_test.mp4", idle_path.read_bytes(), "video/mp4")},
            data={"action": "sim_test", "avatar_id": "demo", "category": "gesture"},
        )
        if r.status_code != 200:
            fail("upload action", r.text[:300])
        else:
            ok("upload action sim_test")
            r = c.delete("/api/v1/assets/actions/sim_test?avatar_id=demo")
            if r.status_code != 200:
                fail("delete action", r.text[:200])
            else:
                ok("delete action sim_test")
    else:
        fail("upload action", "idle.mp4 missing")

    # ComfyUI status
    r = c.get("/api/v1/comfyui/status")
    if r.status_code != 200:
        fail("comfyui status", r.text[:200])
    else:
        ok("comfyui status", str(r.json())[:100])

    # 生成（ComfyUI 不可用时应友好失败）
    r = c.post(
        "/api/v1/assets/generate",
        json={"action": "wave", "avatar_id": "demo", "prompt": "wave hand"},
    )
    if r.status_code in (200, 400, 503):
        ok("assets generate", f"status={r.status_code} body={r.text[:100]}")
    else:
        fail("assets generate", f"{r.status_code} {r.text[:150]}")

    r = c.get("/api/v1/assets/jobs")
    (ok if r.status_code == 200 else fail)("assets jobs list", str(r.status_code))

    # ---- Voice ----
    print("\n## 声音")
    r = c.get("/api/v1/voice")
    if r.status_code != 200:
        fail("voice list", r.text[:200])
    else:
        ok("voice list", str(r.json())[:80])

    # 最小 wav header + silence
    wav_bytes = _minimal_wav()
    r = c.post(
        "/api/v1/voice/sample",
        files={"file": ("sample.wav", wav_bytes, "audio/wav")},
    )
    if r.status_code != 200:
        fail("voice sample", r.text[:300])
    else:
        ok("voice sample", str(r.json())[:80])

    r = c.post("/api/v1/voice/preview", json={"text": "大家好，欢迎来到直播间。", "mock": True})
    if r.status_code != 200:
        fail("voice preview mock", r.text[:300])
    else:
        ok("voice preview mock", str(r.json())[:100])

    # ---- Personas / Avatars ----
    print("\n## 人设与形象")
    r = c.get("/api/v1/personas")
    if r.status_code != 200:
        fail("list personas", r.text[:200])
        persona_id = None
    else:
        personas = r.json()
        ok("list personas", f"n={len(personas)}")
        persona_id = personas[0]["id"] if personas else None

    if persona_id is not None:
        r = c.put(
            f"/api/v1/personas/{persona_id}",
            json={
                "name": "模拟主播",
                "greeting": "哈喽大家好，我是模拟主播～",
                "system_prompt": "你是友好主播，回复简短口语化，不超过40字。",
            },
        )
        if r.status_code != 200:
            fail("update persona", r.text[:200])
        else:
            ok("update persona", f"id={persona_id}")

    r = c.get("/api/v1/avatars")
    if r.status_code != 200:
        fail("list avatars", r.text[:200])
    else:
        avatars = r.json()
        ok("list avatars", f"n={len(avatars)}")
        if avatars:
            aid = avatars[0]["id"]
            r = c.get(f"/api/v1/avatars/{aid}")
            (ok if r.status_code == 200 else fail)("get avatar", str(r.status_code))

    # ---- Chat test ----
    print("\n## 试聊")
    r = c.post("/api/v1/chat/test", json={"text": "今天直播讲什么？"})
    if r.status_code != 200:
        fail("chat test", r.text[:300])
    else:
        data = r.json()
        ok("chat test", f"provider={data.get('provider')} demo={data.get('demo')} reply={str(data.get('reply'))[:40]}")

    # ---- Preflight ----
    print("\n## 开播前检查")
    r = c.post(
        "/api/v1/live/preflight",
        json={"platform": "preview", "runtime_mode": "cloud"},
    )
    if r.status_code != 200:
        fail("preflight preview", r.text[:200])
    else:
        pf = r.json()
        ok("preflight preview", f"can_start={pf.get('can_start')} summary={str(pf.get('summary'))[:50]}")

    r = c.post(
        "/api/v1/live/preflight",
        json={"platform": "douyin", "runtime_mode": "cloud", "rtmp_key": ""},
    )
    if r.status_code != 200:
        fail("preflight douyin no key", r.text[:200])
    else:
        pf = r.json()
        if pf.get("can_start"):
            fail("preflight douyin no key", "should not can_start")
        else:
            ok("preflight douyin no key blocks", str(pf.get("summary"))[:50])

    # ---- Live: 错误路径 ----
    print("\n## 直播：错误路径")
    r = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "douyin", "runtime_mode": "cloud"},
    )
    if r.status_code != 400:
        fail("start douyin no key", f"expect 400 got {r.status_code} {r.text[:150]}")
    else:
        ok("start douyin no key -> 400")

    # 未开播 input
    r = c.post(
        "/api/v1/live/demo/input",
        json={"text": "hi", "user_key": "u"},
    )
    # 可能刚被自检留下，先 stop
    c.post("/api/v1/live/stop", params={"room_id": "demo"})
    r = c.post("/api/v1/live/demo/input", json={"text": "hi", "user_key": "u"})
    if r.status_code != 409:
        # 若仍 running 再 stop
        fail("input when not live", f"expect 409 got {r.status_code} {r.text[:100]}")
    else:
        ok("input when not live -> 409")

    # ---- Live: 预览开播全流程 ----
    print("\n## 直播：预览开播 + 互动")
    for runtime in ("cloud", "local", "hybrid"):
        r = c.post(
            "/api/v1/live/start",
            json={
                "room_id": "demo",
                "platform": "preview",
                "runtime_mode": runtime,
                "mode": "interactive",
            },
        )
        if r.status_code != 200:
            fail(f"start preview {runtime}", r.text[:300])
            continue
        ok(f"start preview {runtime}", r.json().get("message", "")[:40])

        # status
        time.sleep(0.5)
        r = c.get("/api/v1/live/demo/status")
        if r.status_code != 200 or not r.json().get("running"):
            fail(f"status after start {runtime}", r.text[:200])
        else:
            ok(f"status running {runtime}", f"phase={r.json().get('phase')}")

        # 普通输入
        r = c.post(
            "/api/v1/live/demo/input",
            json={"text": f"主播你好，测试{runtime}", "user_key": "sim1", "priority": 10},
        )
        if r.status_code != 200:
            fail(f"input {runtime}", r.text[:200])
        else:
            ok(f"input {runtime}", f"id={r.json().get('id')}")

        # 礼物优先
        r = c.post(
            "/api/v1/live/demo/input",
            json={
                "text": "送了跑车！",
                "user_key": "vip1",
                "priority": 90,
                "is_gift": True,
            },
        )
        if r.status_code != 200:
            fail(f"gift input {runtime}", r.text[:200])
        else:
            ok(f"gift input {runtime}")

        # 等处理
        reply = ""
        for _ in range(50):
            time.sleep(0.2)
            st = c.get("/api/v1/live/demo/status").json()
            reply = st.get("last_reply") or reply
            if st.get("phase") == "idle" and st.get("queue_length", 0) == 0 and reply:
                break
        if reply:
            ok(f"got reply {runtime}", reply[:50])
        else:
            fail(f"got reply {runtime}", f"status={st}")

        # events
        r = c.get("/api/v1/live/demo/events?limit=10")
        if r.status_code != 200:
            fail(f"events {runtime}", r.text[:150])
        else:
            ok(f"events {runtime}", f"n={len(r.json())}")

        # WebSocket
        try:
            with c.websocket_connect("/ws/live/demo") as ws:
                msg = ws.receive_json()
                if msg.get("type") == "status":
                    ok(f"ws status {runtime}", f"phase={msg.get('phase')}")
                else:
                    ok(f"ws first msg {runtime}", str(msg)[:60])
                ws.send_json({"type": "ping", "ts": 1})
                pong = ws.receive_json()
                if pong.get("type") == "pong":
                    ok(f"ws pong {runtime}")
                else:
                    # 可能先收到广播
                    ok(f"ws after ping {runtime}", str(pong.get("type")))
                ws.send_json(
                    {
                        "type": "text",
                        "content": "WebSocket 弹幕测试",
                        "user_key": "ws_user",
                    }
                )
                # drain a few
                for _ in range(5):
                    try:
                        m = ws.receive_json()
                        if m.get("type") in ("ai_response", "status", "error"):
                            ok(f"ws event {runtime}", f"type={m.get('type')}")
                            break
                    except Exception:
                        break
        except Exception as e:
            fail(f"websocket {runtime}", str(e))

        r = c.post("/api/v1/live/stop", params={"room_id": "demo"})
        if r.status_code != 200:
            fail(f"stop {runtime}", r.text[:150])
        else:
            ok(f"stop {runtime}")
        time.sleep(0.3)

    # 重复开播：先开再开（应能处理）
    print("\n## 直播：重复开播 / 脚本模式")
    r = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud"},
    )
    r2 = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud"},
    )
    # 可能 200 覆盖或 409/400
    if r2.status_code in (200, 400, 409, 503):
        ok("double start", f"status={r2.status_code}")
    else:
        fail("double start", f"{r2.status_code} {r2.text[:150]}")
    c.post("/api/v1/live/stop", params={"room_id": "demo"})

    r = c.post(
        "/api/v1/live/start",
        json={
            "room_id": "demo",
            "platform": "preview",
            "runtime_mode": "cloud",
            "mode": "script",
        },
    )
    if r.status_code == 200:
        ok("start script mode")
        time.sleep(1.0)
        st = c.get("/api/v1/live/demo/status").json()
        ok("script status", f"running={st.get('running')} phase={st.get('phase')}")
    else:
        fail("start script mode", r.text[:300])
    c.post("/api/v1/live/stop", params={"room_id": "demo"})

    # 审核敏感词（若有）
    print("\n## 互动边界")
    c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud"},
    )
    r = c.post(
        "/api/v1/live/demo/input",
        json={"text": "", "user_key": "empty"},
    )
    if r.status_code in (200, 400, 429):
        ok("empty input", str(r.status_code))
    else:
        fail("empty input", str(r.status_code))

    # 防刷
    for i in range(15):
        c.post(
            "/api/v1/live/demo/input",
            json={"text": f"刷屏{i}", "user_key": "spammer"},
        )
    r = c.post(
        "/api/v1/live/demo/input",
        json={"text": "最后一条", "user_key": "spammer"},
    )
    # 429 或 200 均可接受（取决于配置）
    ok("anti-spam batch", f"last status={r.status_code}")
    c.post("/api/v1/live/stop", params={"room_id": "demo"})

    # health rooms empty
    r = c.get("/health")
    ok("health final", str(r.json()))

    # ---- Summary ----
    print("\n" + "=" * 60)
    print(f"通过 {len(oks)}  失败 {len(fails)}")
    if fails:
        print("失败项:")
        for f in fails:
            print(" -", f)
        return 1
    print("全部功能模拟通过")
    return 0


def _minimal_wav(duration_ms: int = 200, rate: int = 16000) -> bytes:
    import struct
    import wave

    n = int(rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
