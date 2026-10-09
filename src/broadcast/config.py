"""加载全局与房间配置，合并环境变量。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置根节点必须是 mapping: {path}")
    return data


class ScriptItem(BaseModel):
    id: str
    text: str
    action: str = "nod"


class RoomStream(BaseModel):
    platform: str = "douyin"
    rtmp_url: str = ""
    rtmp_key: str = ""


class RoomAvatar(BaseModel):
    dir: str
    default_action: str = "idle"


class RoomPersona(BaseModel):
    name: str = "助手"
    system_prompt: str = ""
    greeting: str = ""
    temperature: float = 0.7


class RoomPromo(BaseModel):
    """宣讲带货模式（房间级覆盖，全局默认见 configs/default.yaml 的 promo 节）。"""

    enabled: bool | None = None
    layout: str | None = None  # avatar_only | split | website_only
    knowledge_dir: str | None = None
    promo_script: str | None = None
    idle_seconds: int | None = None
    product_name: str | None = None
    website_url: str | None = None
    website_title: str | None = None
    website_refresh_sec: int | None = None
    kb_top_k: int | None = None


class RoomConfig(BaseModel):
    room_id: str
    title: str = ""
    avatar: RoomAvatar
    persona: RoomPersona = Field(default_factory=RoomPersona)
    tts_voice_id: str = ""
    stream: RoomStream = Field(default_factory=RoomStream)
    script: list[ScriptItem] = Field(default_factory=list)
    promo: RoomPromo = Field(default_factory=RoomPromo)

    def avatar_path(self, root: Path | None = None) -> Path:
        root = root or project_root()
        p = Path(self.avatar.dir)
        return p if p.is_absolute() else root / p

    def full_rtmp_url(self) -> str:
        url = (self.stream.rtmp_url or "").rstrip("/")
        key = (self.stream.rtmp_key or "").lstrip("/")
        if not url:
            return ""
        if not key:
            return url
        return f"{url}/{key}"


class AppConfig(BaseModel):
    raw: dict[str, Any] = Field(default_factory=dict)
    root: Path = Field(default_factory=project_root)

    @property
    def data_dir(self) -> Path:
        d = self.raw.get("app", {}).get("data_dir", "data")
        p = Path(d)
        return p if p.is_absolute() else self.root / p

    @property
    def audio_dir(self) -> Path:
        return self._path("paths", "audio_dir", "data/audio")

    @property
    def output_dir(self) -> Path:
        return self._path("paths", "output_dir", "data/output")

    @property
    def clips_dir(self) -> Path:
        return self._path("paths", "clips_dir", "data/output/clips")

    @property
    def logs_dir(self) -> Path:
        return self._path("paths", "logs_dir", "logs")

    def _path(self, section: str, key: str, default: str) -> Path:
        d = self.raw.get(section, {}).get(key, default)
        p = Path(d)
        return p if p.is_absolute() else self.root / p

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.raw.get(name, {}) or {})

    def ensure_dirs(self) -> None:
        for d in (self.audio_dir, self.output_dir, self.clips_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_app_config(config_path: str | Path | None = None) -> AppConfig:
    load_dotenv(project_root() / ".env")
    root = project_root()
    path = Path(config_path) if config_path else root / "configs" / "default.yaml"
    if not path.is_absolute():
        path = root / path
    raw = _load_yaml(path)
    # 环境覆盖
    env_name = os.getenv("APP_ENV")
    if env_name:
        raw.setdefault("app", {})["env"] = env_name
    cfg = AppConfig(raw=raw, root=root)
    cfg.ensure_dirs()
    return cfg


def load_room_config(room_id: str, app: AppConfig | None = None) -> RoomConfig:
    app = app or load_app_config()
    path = app.root / "configs" / "rooms" / f"{room_id}.yaml"
    data = _load_yaml(path)

    tts_block = data.get("tts") or {}
    voice_id = tts_block.get("voice_id") or ""
    stream_block = dict(data.get("stream") or {})

    # 环境变量：ROOM_{ID}_RTMP_KEY / ROOM_{ID}_RTMP_URL
    # 注意：不做跨房间 fallback，避免其它房间误用 demo 的推流码
    env_prefix = f"ROOM_{room_id.upper().replace('-', '_')}"
    key_env = os.getenv(f"{env_prefix}_RTMP_KEY")
    url_env = os.getenv(f"{env_prefix}_RTMP_URL")
    if key_env:
        stream_block["rtmp_key"] = key_env
    if url_env:
        stream_block["rtmp_url"] = url_env

    return RoomConfig(
        room_id=data.get("room_id", room_id),
        title=data.get("title", ""),
        avatar=RoomAvatar(**(data.get("avatar") or {})),
        persona=RoomPersona(**(data.get("persona") or {})),
        tts_voice_id=voice_id or "",
        stream=RoomStream(**stream_block),
        script=[ScriptItem(**x) for x in (data.get("script") or [])],
        promo=RoomPromo(**(data.get("promo") or {})),
    )


def _free_tts_enabled() -> bool:
    v = (os.getenv("USE_FREE_TTS") or "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def resolve_voice_id(app: AppConfig, room: RoomConfig) -> str:
    if room.tts_voice_id:
        return room.tts_voice_id
    # 免费测试模式：优先 edge 音色
    if _free_tts_enabled():
        edge = (os.getenv("EDGE_TTS_VOICE_ID") or "").strip()
        if edge:
            return edge
        return "zh-CN-XiaoxiaoNeural"
    # 优先用户在控制台配置的音色
    env_voice = os.getenv("MINIMAX_VOICE_ID")
    if env_voice:
        return env_voice
    return str(app.section("tts").get("default_voice_id") or "")


def mask_secret(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w\-]+", "", text, flags=re.UNICODE)
    return text[:64] or "item"
