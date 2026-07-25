"""阶段 1 批处理流水线：脚本 → 音频 → 口型 clips → playlist。"""

from __future__ import annotations

import logging
from pathlib import Path

from .avatar_meta import load_avatar_meta
from .config import AppConfig, RoomConfig, resolve_voice_id
from .lipsync import LipSyncEngine, create_lipsync_engine
from .playlist import concat_to_file, write_concat_list
from .tts import TTSEngine, create_tts_engine

logger = logging.getLogger("broadcast.pipeline")


def run_tts_batch(
    app: AppConfig,
    room: RoomConfig,
    *,
    mock: bool = False,
    engine: TTSEngine | None = None,
) -> list[Path]:
    engine = engine or create_tts_engine(app.section("tts"), mock=mock)
    voice = resolve_voice_id(app, room)
    out_paths: list[Path] = []
    room_audio = app.audio_dir / room.room_id
    room_audio.mkdir(parents=True, exist_ok=True)

    for item in room.script:
        out = room_audio / f"{item.id}.wav"
        try:
            engine.synth(item.text, voice, out)
            out_paths.append(out)
            logger.info("TTS ok %s", item.id)
        except Exception:
            logger.exception("TTS 失败 %s，跳过", item.id)
    return out_paths


def run_lipsync_batch(
    app: AppConfig,
    room: RoomConfig,
    *,
    mock: bool = False,
    engine: LipSyncEngine | None = None,
) -> list[Path]:
    engine = engine or create_lipsync_engine(app.section("avatar"), mock=mock)
    avatar_dir = room.avatar_path(app.root)
    meta = load_avatar_meta(avatar_dir)
    clips_dir = app.clips_dir / room.room_id
    clips_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = app.audio_dir / room.room_id

    out_paths: list[Path] = []
    for item in room.script:
        audio = audio_dir / f"{item.id}.wav"
        if not audio.is_file():
            logger.warning("缺少音频，跳过 lipsync: %s", audio)
            continue
        ref = meta.action_path(avatar_dir, item.action)
        if ref is None or not ref.is_file():
            ref = meta.default_action_path(avatar_dir, room.avatar.default_action)
        if ref is None or not ref.is_file():
            logger.error("无可用参考视频，跳过 %s", item.id)
            continue
        out = clips_dir / f"{item.id}.mp4"
        try:
            engine.run(audio, ref, out)
            out_paths.append(out)
            logger.info("lipsync ok %s", item.id)
        except NotImplementedError:
            logger.error("真实口型未接入，请加 --mock")
            raise
        except Exception:
            logger.exception("lipsync 失败 %s，跳过", item.id)
    return out_paths


def build_room_playlist(
    app: AppConfig,
    room: RoomConfig,
    *,
    make_single_file: bool = True,
) -> tuple[Path, Path | None]:
    clips_dir = app.clips_dir / room.room_id
    paths: list[Path] = []
    for item in room.script:
        p = clips_dir / f"{item.id}.mp4"
        if p.is_file():
            paths.append(p)
        else:
            logger.warning("缺少 clip: %s", p)

    if not paths:
        raise FileNotFoundError(f"房间 {room.room_id} 无任何 clip，请先跑 TTS+lipsync")

    list_path = app.output_dir / room.room_id / "playlist.txt"
    write_concat_list(paths, list_path)

    single: Path | None = None
    if make_single_file:
        single = app.output_dir / room.room_id / "broadcast.mp4"
        concat_to_file(list_path, single)
    return list_path, single
