#!/usr/bin/env python3
"""项目自检：模块导入 + API 预览开播 + 互动回复。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    print("== 模块导入 ==")
    for m in [
        "broadcast.config",
        "broadcast.ffmpeg_util",
        "broadcast.lipsync",
        "broadcast.stream",
        "orchestrator.live",
        "api.app",
    ]:
        __import__(m)
        print(" OK", m)

    from broadcast.ffmpeg_util import find_ffmpeg

    ff = find_ffmpeg()
    print(" ffmpeg:", ff or "NOT FOUND")

    print("== API TestClient ==")
    from fastapi.testclient import TestClient
    from api.app import app

    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200, r.text
    print(" health OK")

    r = c.get("/api/v1/bootstrap")
    assert r.status_code == 200
    boot = r.json()
    assert len(boot["platforms"]) >= 5
    assert len(boot["runtime_modes"]) >= 3
    print(" bootstrap OK platforms=", len(boot["platforms"]))

    r = c.get("/")
    assert r.status_code == 200
    assert "选平台" in r.text or "数字人" in r.text
    print(" index OK")

    r = c.get("/static/app.js")
    assert r.status_code == 200
    print(" static OK")

    # 无推流码应 400
    r = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "douyin", "runtime_mode": "cloud"},
    )
    assert r.status_code == 400, r.text
    print(" douyin without key -> 400 OK")

    r = c.post(
        "/api/v1/live/start",
        json={"room_id": "demo", "platform": "preview", "runtime_mode": "cloud"},
    )
    assert r.status_code == 200, r.text
    print(" preview start OK")

    r = c.post(
        "/api/v1/live/demo/input",
        json={"text": "自检你好", "user_key": "selfcheck"},
    )
    assert r.status_code == 200, r.text

    reply = ""
    for _ in range(40):
        time.sleep(0.25)
        st = c.get("/api/v1/live/demo/status").json()
        if st.get("last_reply") and "欢迎" not in (st.get("last_reply") or ""):
            # 可能仍是开场白，再等等
            pass
        if st.get("last_reply"):
            reply = st["last_reply"]
        if st.get("phase") == "idle" and reply and st.get("queue_length", 0) == 0:
            # 再确认有用户向回复
            break

    # 等开场白 + 用户消息处理完
    time.sleep(1.5)
    st = c.get("/api/v1/live/demo/status").json()
    reply = st.get("last_reply") or ""
    print(" status phase=", st.get("phase"), "reply=", reply[:40])
    assert st.get("running") is True
    assert reply, "应有回复"

    r = c.post("/api/v1/live/stop?room_id=demo")
    assert r.status_code == 200
    print(" stop OK")

    print("\n全部自检通过")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("FAIL:", e)
        raise
