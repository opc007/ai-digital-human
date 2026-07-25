"""用户云端/本地配置：读写 .env，并同步到进程环境变量。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .config import project_root

# 可在控制台编辑的字段定义
SETTING_FIELDS: list[dict[str, Any]] = [
    {
        "key": "VIDEO_I2V_BASE_URL",
        "label": "接口地址",
        "group": "video_i2v",
        "group_label": "① 必填 · 图生视频（做角色待机）",
        "secret": False,
        "placeholder": "https://your-i2v-gateway.example/v1",
        "default": "",
        "help": "任意兼容 OpenAI 格式的视频网关地址（如 NewAPI / 自建中转）。留空则跳过 I2V 待机，使用动作视频兜底。进来先填好这一组，再去建角色、上传造型、生成待机。",
    },
    {
        "key": "VIDEO_I2V_API_KEY",
        "label": "API Key",
        "group": "video_i2v",
        "group_label": "① 必填 · 图生视频（做角色待机）",
        "secret": True,
        "placeholder": "sk-...",
        "help": "必填。没有 Key 无法生成呼吸待机。仅保存在本机 .env。",
    },
    {
        "key": "VIDEO_I2V_MODEL",
        "label": "模型名",
        "group": "video_i2v",
        "group_label": "① 必填 · 图生视频（做角色待机）",
        "secret": False,
        "placeholder": "doubao-seedance-1-5-pro_720p",
        "default": "doubao-seedance-1-5-pro_720p",
        "help": "例如 doubao-seedance-1-5-pro_720p / _480p / _1080p。待机提示词由产品内置，无需用户填写。",
    },
    {
        "key": "DEEPSEEK_API_KEY",
        "label": "DeepSeek API Key",
        "group": "cloud_llm",
        "group_label": "② 云端对话（DeepSeek）",
        "secret": True,
        "placeholder": "sk-...",
        "help": "用于云端模式/混合模式的对话。在 platform.deepseek.com 申请。",
    },
    {
        "key": "DEEPSEEK_BASE_URL",
        "label": "DeepSeek 接口地址",
        "group": "cloud_llm",
        "group_label": "② 云端对话（DeepSeek）",
        "secret": False,
        "placeholder": "https://api.deepseek.com/v1",
        "default": "https://api.deepseek.com/v1",
        "help": "一般不用改。兼容其它 OpenAI 格式接口时可改这里。",
    },
    {
        "key": "DEEPSEEK_MODEL",
        "label": "对话模型名",
        "group": "cloud_llm",
        "group_label": "② 云端对话（DeepSeek）",
        "secret": False,
        "placeholder": "deepseek-chat",
        "default": "deepseek-chat",
        "help": "例如 deepseek-chat、deepseek-reasoner。",
    },
    {
        "key": "USE_FREE_TTS",
        "label": "免费测试声音（edge-tts）",
        "group": "cloud_tts",
        "group_label": "③ 云端声音（MiniMax）",
        "secret": False,
        "placeholder": "1",
        "default": "1",
        "help": "填 1=开启免费测试人声（无需 MiniMax 会员，适合先跑通流程）；填 0=改用下方 MiniMax（需有效 Key）。改完保存，下一场开播生效。",
    },
    {
        "key": "EDGE_TTS_VOICE_ID",
        "label": "免费测试音色 ID",
        "group": "cloud_tts",
        "group_label": "③ 云端声音（MiniMax）",
        "secret": False,
        "placeholder": "zh-CN-XiaoxiaoNeural",
        "default": "zh-CN-XiaoxiaoNeural",
        "help": "免费模式下的默认音色，也可在「声音」页点选用。常见：女声 zh-CN-XiaoxiaoNeural，男声 zh-CN-YunxiNeural。",
    },
    {
        "key": "MINIMAX_API_KEY",
        "label": "MiniMax API Key",
        "group": "cloud_tts",
        "group_label": "③ 云端声音（MiniMax）",
        "secret": True,
        "placeholder": "填写 MiniMax 密钥",
        "help": "会员有效时填写。关闭「免费测试声音」后才会使用。在 minimaxi.com 申请。",
    },
    {
        "key": "MINIMAX_GROUP_ID",
        "label": "MiniMax Group ID",
        "group": "cloud_tts",
        "group_label": "③ 云端声音（MiniMax）",
        "secret": False,
        "placeholder": "数字 GroupId",
        "help": "部分 MiniMax 接口需要 GroupId，控制台账号信息里可查。",
    },
    {
        "key": "MINIMAX_VOICE_ID",
        "label": "默认音色 ID",
        "group": "cloud_tts",
        "group_label": "③ 云端声音（MiniMax）",
        "secret": False,
        "placeholder": "male-qn-qingse",
        "default": "male-qn-qingse",
        "help": "MiniMax 音色 ID，可在平台音色列表复制。",
    },
    {
        "key": "MINIMAX_LANGUAGE_BOOST",
        "label": "语种增强 language_boost",
        "group": "cloud_tts",
        "group_label": "③ 云端声音（MiniMax）",
        "secret": False,
        "placeholder": "Chinese",
        "default": "Chinese",
        "help": "官方 T2A 字段：增强指定语种/方言。中文直播用 Chinese；粤语用 Chinese,Yue；多语混杂用 auto。",
    },
    {
        "key": "MINIMAX_MODEL",
        "label": "TTS 模型",
        "group": "cloud_tts",
        "group_label": "③ 云端声音（MiniMax）",
        "secret": False,
        "placeholder": "speech-02-turbo",
        "default": "speech-02-turbo",
        "help": "如 speech-02-turbo / speech-2.6-turbo / speech-2.8-hd 等，以官方文档为准。",
    },
    {
        "key": "OLLAMA_BASE_URL",
        "label": "Ollama 地址",
        "group": "local",
        "group_label": "④ 本地模式（Ollama）",
        "secret": False,
        "placeholder": "http://127.0.0.1:11434/v1",
        "default": "http://127.0.0.1:11434/v1",
        "help": "本机 Ollama OpenAI 兼容地址。",
    },
    {
        "key": "OLLAMA_MODEL",
        "label": "本地模型名",
        "group": "local",
        "group_label": "④ 本地模式（Ollama）",
        "secret": False,
        "placeholder": "qwen2.5:7b",
        "default": "qwen2.5:7b",
        "help": "需先 ollama pull 对应模型。",
    },
    {
        "key": "ROOM_DEMO_RTMP_KEY",
        "label": "默认推流码（可选）",
        "group": "stream",
        "group_label": "⑤ 推流（可选）",
        "secret": True,
        "placeholder": "可空，开播时再填也行",
        "help": "保存后，开播页可自动带出，仍可在页面临时修改。",
    },
    {
        "key": "OUTPUT_ORIENTATION",
        "label": "画面方向",
        "group": "stream",
        "group_label": "⑤ 推流（可选）",
        "secret": False,
        "placeholder": "portrait",
        "default": "portrait",
        "help": "portrait=竖屏 1080×1920（抖音等）；landscape=横屏 1920×1080；square=1:1。",
    },
    {
        "key": "OUTPUT_FIT",
        "label": "画面适配",
        "group": "stream",
        "group_label": "⑤ 推流（可选）",
        "secret": False,
        "placeholder": "contain",
        "default": "contain",
        "help": "contain=完整显示人物（可有黑边）；cover=铺满画面（可能裁切）。",
    },
    {
        "key": "COMFYUI_BASE_URL",
        "label": "ComfyUI 地址",
        "group": "comfyui",
        "group_label": "⑥ 本地生视频（ComfyUI·可选）",
        "secret": False,
        "placeholder": "http://127.0.0.1:8000",
        "default": "http://127.0.0.1:8000",
        "help": "本机 ComfyUI 地址。Comfy Desktop 常见为 http://127.0.0.1:8000（不是 8188）。工作流：configs/comfyui/action_workflow.json",
    },
    {
        "key": "COMFYUI_WORKFLOW_PATH",
        "label": "工作流 JSON 路径（可选）",
        "group": "comfyui",
        "group_label": "⑥ 本地生视频（ComfyUI·可选）",
        "secret": False,
        "placeholder": "configs/comfyui/action_workflow.json",
        "help": "留空则用默认路径。需为 ComfyUI「另存为 API 格式」导出的 JSON。",
    },
]


def env_path() -> Path:
    return project_root() / ".env"


def ensure_env_file() -> Path:
    path = env_path()
    if not path.is_file():
        example = project_root() / ".env.example"
        if example.is_file():
            path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            path.write_text("# AI 数字人配置\n", encoding="utf-8")
    return path


def _parse_env_file(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        result[k] = v
    return result


def read_env_map() -> dict[str, str]:
    path = ensure_env_file()
    return _parse_env_file(path.read_text(encoding="utf-8"))


def write_env_map(updates: dict[str, str]) -> None:
    """合并写入 .env：更新已有键，没有则追加；不删其它键。"""
    path = ensure_env_file()
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    keys_done: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line.strip()) if line.strip() and not line.strip().startswith("#") else None
        # keep comments and blanks as-is; only replace KEY= lines
        raw = line
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                keys_done.add(k)
                continue
        new_lines.append(raw)

    for k, v in updates.items():
        if k not in keys_done:
            new_lines.append(f"{k}={v}")

    content = "\n".join(new_lines)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")

    # 立即生效
    for k, v in updates.items():
        os.environ[k] = v
    load_dotenv(path, override=True)


def get_settings_for_ui() -> dict[str, Any]:
    load_dotenv(env_path(), override=True)
    file_map = read_env_map()
    groups: dict[str, dict[str, Any]] = {}
    fields_out: list[dict[str, Any]] = []

    for meta in SETTING_FIELDS:
        key = meta["key"]
        raw = file_map.get(key)
        if raw is None or raw == "":
            raw = os.getenv(key) or meta.get("default") or ""
        item = {
            **meta,
            "value": raw,
            "configured": bool(str(raw).strip()),
        }
        fields_out.append(item)
        g = meta["group"]
        if g not in groups:
            groups[g] = {
                "id": g,
                "label": meta["group_label"],
                "fields": [],
            }
        groups[g]["fields"].append(item)

    return {
        "env_path": str(env_path()),
        "groups": list(groups.values()),
        "fields": fields_out,
    }


def save_settings(payload: dict[str, str]) -> dict[str, Any]:
    """payload: { KEY: value }。空字符串表示清空。未知键忽略。"""
    allowed = {m["key"] for m in SETTING_FIELDS}
    updates: dict[str, str] = {}
    for k, v in payload.items():
        if k not in allowed:
            continue
        if v is None:
            continue
        v = str(v).strip()
        # 换行会注入新的 KEY=VALUE 行，破坏 .env 结构
        if "\n" in v or "\r" in v:
            continue
        updates[k] = v

    if not updates:
        known = ", ".join(sorted(allowed))
        raise ValueError(f"没有可保存的字段（仅支持: {known}）")

    write_env_map(updates)
    return get_settings_for_ui()


def apply_settings_to_engines() -> None:
    """把 .env 同步到当前进程（开播前再调一次更稳）。"""
    load_dotenv(env_path(), override=True)
