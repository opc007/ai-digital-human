"""开播前检查：按主路径逐步给出通过/警告/阻断。"""

from __future__ import annotations

import os
from typing import Any

from .ffmpeg_util import find_ffmpeg
from .settings_store import apply_settings_to_engines


def run_preflight(
    *,
    platform: str = "preview",
    runtime_mode: str = "cloud",
    rtmp_key: str | None = None,
    avatar_id: str = "demo",
    look_id: str = "default",
) -> dict[str, Any]:
    apply_settings_to_engines()
    checks: list[dict[str, Any]] = []

    def add(id_: str, label: str, ok: bool, level: str, message: str, fix: str = "") -> None:
        checks.append(
            {
                "id": id_,
                "label": label,
                "ok": ok,
                "level": level,  # ok | warn | block
                "message": message,
                "fix": fix,
            }
        )

    # 1 素材（按当前选中的角色 / 造型检查，不再死盯 demo）
    from .assets import safe_avatar_id
    from .characters import list_look_assets, summarize_character

    cid = safe_avatar_id(avatar_id or "demo")
    lid = safe_avatar_id(look_id or "default") or "default"
    char: dict[str, Any] = {}
    try:
        char = summarize_character(cid)
        char_name = char.get("name") or cid
    except Exception:
        char_name = cid
    assets = list_look_assets(cid, lid)
    idle_ok = any(a["name"] == "idle" and a["exists"] for a in assets["actions"])
    ready_n = assets.get("ready_count") or 0
    look_label = lid
    for lk in char.get("looks") or []:
        if str(lk.get("id")) == lid:
            look_label = lk.get("name") or lid
            break

    if idle_ok and ready_n >= 1:
        add(
            "avatar",
            "形象与动作",
            True,
            "ok",
            f"角色「{char_name}」· 造型「{look_label}」已有 {ready_n} 个动作，含 idle",
            "",
        )
    elif idle_ok:
        add(
            "avatar",
            "形象与动作",
            True,
            "warn",
            f"角色「{char_name}」有 idle，建议再补 2～3 个动作",
            "/materials",
        )
    else:
        add(
            "avatar",
            "形象与动作",
            False,
            "block",
            f"角色「{char_name}」造型「{look_label}」缺少 idle 待机视频，请到素材中心生成微动",
            "/materials",
        )

    if not assets.get("source_exists"):
        add(
            "source",
            "正脸原图",
            True,
            "warn",
            "当前造型未上传原图（仅上传动作也可播；生成微动需要原图）",
            "/materials",
        )
    else:
        add("source", "正脸原图", True, "ok", "当前造型已有原图", "")

    # 2 FFmpeg
    ff = find_ffmpeg()
    if ff:
        add("ffmpeg", "FFmpeg", True, "ok", "已就绪（推流/混流需要）", "")
    else:
        add(
            "ffmpeg",
            "FFmpeg",
            False,
            "block",
            "未检测到 FFmpeg，无法推流与音画合成",
            "",
        )

    # 3 声音
    has_minimax = bool(os.getenv("MINIMAX_API_KEY"))
    use_free = (os.getenv("USE_FREE_TTS") or "1").strip().lower() in ("1", "true", "yes", "on")
    if use_free:
        add("tts", "声音 TTS", True, "ok", "免费测试声音已开（edge-tts）", "")
    elif runtime_mode == "local":
        add(
            "tts",
            "声音 TTS",
            True,
            "warn" if not has_minimax else "ok",
            "本地模式：将尝试本机 TTS（edge-tts），失败则演示静音",
            "",
        )
    elif has_minimax:
        add("tts", "声音 TTS", True, "ok", "已配置 MiniMax，可真出声", "")
    else:
        add(
            "tts",
            "声音 TTS",
            True,
            "warn",
            "未配置 MiniMax，将用演示音（可先开「免费测试声音」）",
            "settings",
        )

    # 4 对话
    has_llm = bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))
    if runtime_mode == "local":
        try:
            from engines.llm import list_ollama_models, resolve_ollama_model

            base = os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
            names = list_ollama_models(base)
            preferred = os.getenv("OLLAMA_MODEL") or "qwen2.5:7b"
            resolved = resolve_ollama_model(preferred, base) if names else None
            online = bool(names)
        except Exception:
            online = False
            preferred = os.getenv("OLLAMA_MODEL") or "qwen2.5:7b"
            resolved = None
        if online and resolved:
            note = resolved if resolved == preferred else f"{resolved}（配置 {preferred} 未安装，已自动改用）"
            add("llm", "对话模型", True, "ok", f"Ollama 在线，模型 {note}", "")
        elif online:
            add(
                "llm",
                "对话模型",
                True,
                "warn",
                "Ollama 在线但未发现模型，将用演示回复",
                "settings",
            )
        else:
            add(
                "llm",
                "对话模型",
                True,
                "warn",
                "Ollama 未检测到，将用演示回复",
                "settings",
            )
    elif has_llm:
        add("llm", "对话模型", True, "ok", "已配置 DeepSeek（或兼容 Key）", "")
    else:
        add(
            "llm",
            "对话模型",
            True,
            "warn",
            "未配置对话 Key，将用演示回复",
            "settings",
        )

    # 5 推流
    is_preview = platform in ("preview", "", None) or platform == "preview"
    key = (rtmp_key or os.getenv("ROOM_DEMO_RTMP_KEY") or "").strip()
    if is_preview:
        add("stream", "推流", True, "ok", "仅预览模式，不推到直播平台", "")
    elif key:
        add("stream", "推流", True, "ok", "已填写推流码", "")
    else:
        add(
            "stream",
            "推流",
            False,
            "block",
            "真平台开播必须填写推流码",
            "step2",
        )

    blocks = [c for c in checks if c["level"] == "block"]
    warns = [c for c in checks if c["level"] == "warn"]
    return {
        "ok": len(blocks) == 0,
        "can_start": len(blocks) == 0,
        "block_count": len(blocks),
        "warn_count": len(warns),
        "avatar_id": cid,
        "look_id": lid,
        "checks": checks,
        "summary": (
            "可以开播"
            if not blocks and not warns
            else ("可以开播（有提示）" if not blocks else "请先处理阻断项")
        ),
    }
