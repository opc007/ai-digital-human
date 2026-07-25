"""阶段 0～1 播报管线：配置 / TTS / 口型 / 播放列表 / 推流。"""

from .config import AppConfig, RoomConfig, load_app_config, load_room_config

__all__ = [
    "AppConfig",
    "RoomConfig",
    "load_app_config",
    "load_room_config",
]

__version__ = "0.1.0"
