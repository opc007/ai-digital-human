"""声音素材：试听 TTS、上传参考音频、音色目录。"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

from .config import load_app_config, project_root, resolve_voice_id, load_room_config
from .settings_store import apply_settings_to_engines, save_settings
from .tts import create_tts_engine
from .voice_catalog import find_voice, get_voice_catalog


def voice_dir() -> Path:
    p = project_root() / "data" / "voices" / "demo"
    p.mkdir(parents=True, exist_ok=True)
    (p / "sample").mkdir(exist_ok=True)
    (p / "preview").mkdir(exist_ok=True)
    return p


def _free_tts_on() -> bool:
    v = (os.getenv("USE_FREE_TTS") or "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def list_voices(runtime_mode: str = "cloud") -> dict[str, Any]:
    root = voice_dir()
    samples = []
    for f in sorted((root / "sample").glob("*")):
        if f.is_file() and f.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg"):
            samples.append(
                {
                    "name": f.name,
                    "url": f"/media/voices/demo/sample/{f.name}",
                    "size": f.stat().st_size,
                }
            )
    previews = []
    for f in sorted((root / "preview").glob("*.wav"), reverse=True)[:10]:
        previews.append(
            {
                "name": f.name,
                "url": f"/media/voices/demo/preview/{f.name}",
                "size": f.stat().st_size,
            }
        )
    apply_settings_to_engines()
    free = _free_tts_on()
    provider = "minimax"
    if free or (runtime_mode or "").lower() == "local":
        provider = "edge"
    elif not os.getenv("MINIMAX_API_KEY"):
        provider = "edge"  # 无 Key 时直接展示免费音色，避免假静音

    catalog = get_voice_catalog(provider)
    if provider == "edge":
        current = os.getenv("EDGE_TTS_VOICE_ID") or catalog["default_id"]
    else:
        current = os.getenv("MINIMAX_VOICE_ID") or catalog["default_id"]
    meta = find_voice(current) or {}
    return {
        "provider": "edge-free" if free or provider == "edge" else "minimax",
        "free_tts": free or provider == "edge",
        "catalog_provider": catalog["provider"],
        "voice_id": current,
        "voice_name": meta.get("name") or current,
        "voice_gender": meta.get("gender") or "",
        "has_minimax_key": bool(os.getenv("MINIMAX_API_KEY")),
        "genders": catalog["genders"],
        "voices": catalog["voices"],
        "groups": catalog["groups"],
        "samples": samples,
        "previews": previews,
        "hint": (
            "当前为免费测试声音（微软 edge-tts），可直接试听开播；之后在配置里关掉免费开关并填 MiniMax Key 即可升级。"
            if (free or provider == "edge")
            else "当前使用 MiniMax 云端声音。"
        ),
    }


def select_voice(voice_id: str) -> dict[str, Any]:
    """保存当前音色到 .env，下一场开播生效。"""
    vid = (voice_id or "").strip()
    if not vid:
        raise ValueError("请选择音色")
    meta = find_voice(vid)
    # edge 音色写入 EDGE_TTS_VOICE_ID；MiniMax 写入 MINIMAX_VOICE_ID
    from .tts import _is_edge_voice

    if _is_edge_voice(vid) or _free_tts_on():
        save_settings({"EDGE_TTS_VOICE_ID": vid})
    else:
        save_settings({"MINIMAX_VOICE_ID": vid})
    apply_settings_to_engines()
    return {
        "ok": True,
        "voice_id": vid,
        "voice_name": (meta or {}).get("name") or vid,
        "voice_gender": (meta or {}).get("gender") or "",
        "message": f"已选择音色：{(meta or {}).get('name') or vid}",
    }


def save_sample(data: bytes, filename: str) -> dict[str, Any]:
    root = voice_dir()
    ext = Path(filename).suffix.lower() or ".wav"
    name = f"sample_{int(time.time())}{ext}"
    path = root / "sample" / name
    path.write_bytes(data)
    return {
        "ok": True,
        "name": name,
        "url": f"/media/voices/demo/sample/{name}",
    }


def preview_tts(
    text: str,
    mock: bool = False,
    voice_id: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    apply_settings_to_engines()
    app = load_app_config()
    room = load_room_config("demo", app)
    voice = (voice_id or "").strip() or resolve_voice_id(app, room)
    tts_cfg = {**app.section("tts")}
    free = _free_tts_on()
    if provider:
        tts_cfg["provider"] = provider
    elif free or not os.getenv("MINIMAX_API_KEY"):
        # 免费测试 / 无 Key：走 edge-tts 真人声，不再静音 mock
        tts_cfg["provider"] = "local"
    use_mock = bool(mock)
    engine = create_tts_engine(tts_cfg, mock=use_mock)
    out = voice_dir() / "preview" / f"tts_{uuid.uuid4().hex[:10]}.wav"
    engine.synth(text.strip() or "大家好，欢迎来到直播间。", voice, out)
    meta = find_voice(voice) or {}
    return {
        "ok": True,
        "text": text,
        "voice_id": voice,
        "voice_name": meta.get("name") or voice,
        "demo": use_mock,
        "free_tts": free or (tts_cfg.get("provider") or "").lower() in ("local", "edge", "edge-tts"),
        "url": f"/media/voices/demo/preview/{out.name}",
        "path": str(out),
    }
