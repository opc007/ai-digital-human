"""TTS 引擎：MiniMax HTTP + Mock。"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import uuid
import wave
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

logger = logging.getLogger("broadcast.tts")


def _tts_cache_enabled() -> bool:
    """TTS 磁盘缓存开关：默认开启，TTS_CACHE_ENABLED=0/false/off/no 关闭。"""
    v = (os.getenv("TTS_CACHE_ENABLED") or "1").strip().lower()
    return v not in ("0", "false", "off", "no")


def _tts_cache_dir() -> Path:
    from .config import project_root

    return project_root() / "data" / "audio" / "cache"


def _tts_cache_key(text: str, voice_id: str, params: dict) -> str:
    """以 voice_id + text + 关键合成参数计算缓存键。"""
    raw = json.dumps(
        {"voice_id": voice_id, "text": text, **params},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _tts_cache_lookup(key: str, out_path: Path) -> Path | None:
    """命中缓存则复制到 out_path 并返回；任何异常都返回 None（降级走 API）。"""
    try:
        cached = _tts_cache_dir() / f"{key}.wav"
        if not cached.is_file() or cached.stat().st_size <= 0:
            return None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, out_path)
        return out_path
    except Exception as e:
        logger.warning("TTS 缓存读取失败，改走 API: %s", e)
        return None


def _tts_cache_store(key: str, src: Path) -> None:
    """写入缓存：先写临时文件再原子 rename，避免并发写坏；失败不影响合成结果。"""
    try:
        cache_dir = _tts_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{key}.wav"
        tmp = cache_dir / f".{key}.{uuid.uuid4().hex}.tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)  # 同目录原子替换；并发写同一键最后者覆盖，内容一致
    except Exception as e:
        logger.warning("TTS 缓存写入失败（不影响本次合成）: %s", e)


class TTSEngine(ABC):
    @abstractmethod
    def synth(self, text: str, voice_id: str, out_path: Path) -> Path:
        """合成音频到 out_path，返回路径。"""


class MockTTSEngine(TTSEngine):
    """生成静音 wav，用于无 API Key 时打通流水线。"""

    def __init__(self, sample_rate: int = 32000, duration_sec: float = 1.5):
        self.sample_rate = sample_rate
        self.duration_sec = duration_sec

    def synth(self, text: str, voice_id: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        n_frames = int(self.sample_rate * self.duration_sec)
        with wave.open(str(out_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"\x00\x00" * n_frames)
        logger.info("MockTTS -> %s (%s chars)", out_path, len(text))
        return out_path


# 官方 language_boost 枚举（T2A V2）；未知语言用 auto
MINIMAX_LANGUAGE_BOOSTS = frozenset(
    {
        "Chinese",
        "Chinese,Yue",
        "English",
        "Arabic",
        "Russian",
        "Spanish",
        "French",
        "Portuguese",
        "German",
        "Turkish",
        "Dutch",
        "Ukrainian",
        "Vietnamese",
        "Indonesian",
        "Japanese",
        "Italian",
        "Korean",
        "Thai",
        "Polish",
        "Romanian",
        "Greek",
        "Czech",
        "Finnish",
        "Hindi",
        "Bulgarian",
        "Danish",
        "Hebrew",
        "Malay",
        "Persian",
        "Slovak",
        "Swedish",
        "Croatian",
        "Filipino",
        "Hungarian",
        "Norwegian",
        "Slovenian",
        "Catalan",
        "Nynorsk",
        "Tamil",
        "Afrikaans",
        "auto",
    }
)


def normalize_minimax_language_boost(value: str | None, default: str = "Chinese") -> str:
    """规范化 language_boost；空值回落 default。"""
    v = (value or "").strip()
    if not v:
        return default
    # 常见别名
    aliases = {
        "zh": "Chinese",
        "zh-cn": "Chinese",
        "cn": "Chinese",
        "中文": "Chinese",
        "普通话": "Chinese",
        "yue": "Chinese,Yue",
        "cantonese": "Chinese,Yue",
        "粤语": "Chinese,Yue",
        "en": "English",
        "english": "English",
        "ja": "Japanese",
        "jp": "Japanese",
        "ko": "Korean",
        "kr": "Korean",
    }
    key = v if v in MINIMAX_LANGUAGE_BOOSTS else aliases.get(v.lower(), v)
    if key not in MINIMAX_LANGUAGE_BOOSTS:
        logger.warning("未知 MINIMAX_LANGUAGE_BOOST=%s，改用 %s", v, default)
        return default
    return key


class MiniMaxTTSEngine(TTSEngine):
    """
    MiniMax 文本转语音（HTTP T2A V2）。
    官方文档：请求体含 language_boost（语种增强），默认 Chinese 适配中文直播。
    """

    def __init__(
        self,
        api_key: str | None = None,
        group_id: str | None = None,
        model: str = "speech-02-turbo",
        base_url: str = "https://api.minimax.chat/v1/t2a_v2",
        sample_rate: int = 32000,
        language_boost: str | None = None,
        emotion: str | None = None,
    ):
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY") or ""
        self.group_id = group_id or os.getenv("MINIMAX_GROUP_ID") or ""
        self.model = model
        self.base_url = base_url
        self.sample_rate = sample_rate
        self.language_boost = normalize_minimax_language_boost(
            language_boost if language_boost is not None else os.getenv("MINIMAX_LANGUAGE_BOOST"),
            default="Chinese",
        )
        self.emotion = (emotion if emotion is not None else os.getenv("MINIMAX_EMOTION") or "").strip() or None
        if not self.api_key:
            raise ValueError("缺少 MINIMAX_API_KEY")

    def _cache_key_for(self, text: str, voice_id: str) -> str:
        return _tts_cache_key(
            text,
            voice_id,
            {
                "model": self.model,
                "sample_rate": self.sample_rate,
                "language_boost": self.language_boost,
                "emotion": self.emotion or "",
            },
        )

    def synth(self, text: str, voice_id: str, out_path: Path, retries: int = 2) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # 磁盘缓存：同音色+同文案+同合成参数直接复用，跳过 MiniMax 请求
        cache_key = self._cache_key_for(text, voice_id) if _tts_cache_enabled() else None
        if cache_key:
            hit = _tts_cache_lookup(cache_key, out_path)
            if hit is not None:
                logger.info(
                    "MiniMaxTTS 缓存命中 -> %s (%s chars) voice=%s",
                    out_path,
                    len(text),
                    voice_id,
                )
                return hit

        url = self.base_url
        if self.group_id and "GroupId" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}GroupId={self.group_id}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        voice_setting: dict = {
            "voice_id": voice_id,
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
            # 中英数字混读更稳
            "text_normalization": True,
        }
        if self.emotion:
            voice_setting["emotion"] = self.emotion

        payload: dict = {
            "model": self.model,
            "text": text,
            "stream": False,
            # 官方语种增强：直播默认 Chinese；多语可设 auto
            "language_boost": self.language_boost,
            "voice_setting": voice_setting,
            "audio_setting": {
                "sample_rate": self.sample_rate,
                "bitrate": 128000,
                "format": "wav",
                "channel": 1,
            },
        }
        # 失败重试：网络抖动 / 限流常见，最多额外重试 retries 次
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with httpx.Client(timeout=120.0) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                break
            except Exception as e:
                last_err = e
                if attempt < retries:
                    import time

                    wait = 2.0 * (attempt + 1)
                    logger.warning(
                        "MiniMax 请求失败（%s），%.1fs 后重试 (%s/%s)",
                        e,
                        wait,
                        attempt + 1,
                        retries,
                    )
                    time.sleep(wait)
        else:
            raise RuntimeError(f"MiniMax 请求失败，已重试 {retries} 次: {last_err}")

        # 业务错误码（HTTP 200 但 base_resp 失败）
        if isinstance(data, dict):
            br = data.get("base_resp") if isinstance(data.get("base_resp"), dict) else {}
            code = br.get("status_code")
            if code not in (None, 0):
                raise RuntimeError(
                    f"MiniMax 业务错误 {code}: {br.get('status_msg') or data}"
                )

        # 兼容：data.audio / audio / data.audio_file（官方默认 hex）
        audio_payload = None
        if isinstance(data, dict):
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            audio_payload = (
                (inner or {}).get("audio")
                or data.get("audio")
                or (inner or {}).get("audio_file")
                or (inner or {}).get("audio_hex")
            )

        if not audio_payload:
            raise RuntimeError(f"MiniMax 响应中无音频字段: {str(data)[:500]}")

        if isinstance(audio_payload, str) and audio_payload.startswith("http"):
            with httpx.Client(timeout=120.0) as client:
                r = client.get(audio_payload)
                r.raise_for_status()
                out_path.write_bytes(r.content)
        else:
            out_path.write_bytes(_decode_minimax_audio(str(audio_payload)))

        if cache_key:
            _tts_cache_store(cache_key, out_path)

        logger.info(
            "MiniMaxTTS -> %s (%s chars) lang=%s voice=%s",
            out_path,
            len(text),
            self.language_boost,
            voice_id,
        )
        return out_path


def _decode_minimax_audio(payload: str) -> bytes:
    """
    官方非流式默认 output_format=hex；也兼容 base64。
    优先识别纯 hex，避免 hex 被 base64 误解码成坏音频。
    """
    s = (payload or "").strip()
    if not s:
        raise RuntimeError("空音频数据")
    # 纯十六进制（官方默认）
    if len(s) >= 8 and len(s) % 2 == 0:
        try:
            # 快速判断：前 32 字符是否全是 hex
            head = s[:64]
            if all(c in "0123456789abcdefABCDEF" for c in head) and all(
                c in "0123456789abcdefABCDEF" for c in s[:: max(1, len(s) // 200)]
            ):
                # 全串校验过慢时抽样 + 尾部；失败再走 base64
                if all(c in "0123456789abcdefABCDEF" for c in s):
                    return bytes.fromhex(s)
        except Exception:
            pass
    try:
        raw = base64.b64decode(s, validate=False)
        if len(raw) > 64:
            return raw
    except Exception:
        pass
    try:
        return bytes.fromhex(s)
    except Exception as e:
        raise RuntimeError(f"无法解码 MiniMax 音频: {e}") from e


def _is_edge_voice(voice: str) -> bool:
    """edge-tts 音色形如 zh-CN-XiaoxiaoNeural；MiniMax 为 male-qn-qingse 等。"""
    v = (voice or "").strip()
    if not v:
        return False
    # 常见 edge 命名：区域-语言-名字Neural
    if "Neural" in v or v.count("-") >= 2 and any(
        v.startswith(p) for p in ("zh-", "en-", "ja-", "ko-", "yue-")
    ):
        return True
    return False


class LocalTTSEngine(TTSEngine):
    """
    本机 TTS 占位：优先调用 edge-tts（若已安装），否则静音 Mock。
    后续可换成 GPT-SoVITS / Fish-Speech。
    """

    def __init__(self, sample_rate: int = 24000, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.sample_rate = sample_rate
        self.voice = voice or "zh-CN-XiaoxiaoNeural"

    def synth(self, text: str, voice_id: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # 房间默认常是 MiniMax 音色 ID，本地模式必须忽略，改用 edge 默认音色
        raw = (voice_id or "").strip()
        voice = raw if _is_edge_voice(raw) else self.voice
        # 尝试 edge-tts
        try:
            import asyncio

            import edge_tts  # type: ignore

            async def _run() -> None:
                communicate = edge_tts.Communicate(text, voice)
                tmp = out_path.with_suffix(".mp3")
                # 绝对路径，避免工作目录变化 + 中文路径相对解析问题
                tmp_abs = tmp.resolve()
                out_abs = out_path.resolve()
                await communicate.save(str(tmp_abs))
                from broadcast.ffmpeg_util import run_ffmpeg

                proc = run_ffmpeg(
                    [
                        "-y",
                        "-i",
                        str(tmp_abs),
                        "-ar",
                        str(self.sample_rate),
                        "-ac",
                        "1",
                        str(out_abs),
                    ],
                    capture_output=True,
                )
                if proc.returncode != 0:
                    err = (proc.stderr or b"")[-400:].decode("utf-8", errors="ignore")
                    raise RuntimeError(f"ffmpeg convert failed: {err}")
                try:
                    tmp_abs.unlink(missing_ok=True)
                except Exception:
                    pass

            asyncio.run(_run())
            logger.info("LocalTTS(edge) voice=%s -> %s", voice, out_path)
            return out_path
        except Exception as e:
            logger.warning("LocalTTS 回落静音: %s", e)
            return MockTTSEngine(sample_rate=self.sample_rate).synth(text, voice_id, out_path)


def _want_free_tts(app_tts: dict | None = None) -> bool:
    """会员过期/未配 Key 时：USE_FREE_TTS=1（默认开）或 TTS_PROVIDER=edge|local 强制走免费 edge-tts。"""
    flag = (os.getenv("USE_FREE_TTS") if os.getenv("USE_FREE_TTS") is not None else "1")
    flag = str(flag).strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    env_p = (os.getenv("TTS_PROVIDER") or "").strip().lower()
    if env_p in ("local", "edge", "edge-tts", "free"):
        return True
    if app_tts:
        p = (app_tts.get("provider") or "").strip().lower()
        if p in ("local", "edge", "edge-tts", "free"):
            return True
    return False


class FallbackTTSEngine(TTSEngine):
    """主引擎失败时依次尝试备用（免费 edge → 静音），避免会员过期后整轮卡死。"""

    def __init__(self, primary: TTSEngine, *fallbacks: TTSEngine):
        self.primary = primary
        self.fallbacks = list(fallbacks)

    def synth(self, text: str, voice_id: str, out_path: Path) -> Path:
        try:
            return self.primary.synth(text, voice_id, out_path)
        except Exception as e:
            logger.warning("主 TTS 失败，尝试免费备用: %s", e)
            last: Exception | None = e
            for fb in self.fallbacks:
                try:
                    return fb.synth(text, voice_id, out_path)
                except Exception as e2:
                    last = e2
                    logger.warning("备用 TTS 仍失败 (%s): %s", type(fb).__name__, e2)
            raise RuntimeError(f"全部 TTS 失败: {last}") from last


def create_tts_engine(app_tts: dict, mock: bool = False) -> TTSEngine:
    sample = int(app_tts.get("sample_rate") or 32000)
    if mock or (app_tts.get("provider") or "").lower() == "mock":
        return MockTTSEngine(sample_rate=sample)
    # 免费优先：会员过期时直接用 edge-tts，不走 MiniMax
    if _want_free_tts(app_tts):
        logger.info("TTS 使用免费 edge-tts（USE_FREE_TTS / TTS_PROVIDER）")
        return LocalTTSEngine(sample_rate=int(app_tts.get("sample_rate") or 24000))
    provider = (app_tts.get("provider") or "minimax").lower()
    if provider in ("local", "edge", "edge-tts", "free"):
        return LocalTTSEngine(sample_rate=int(app_tts.get("sample_rate") or 24000))
    if provider == "minimax":
        free = LocalTTSEngine(sample_rate=int(app_tts.get("sample_rate") or 24000))
        silent = MockTTSEngine(sample_rate=sample)
        try:
            primary = MiniMaxTTSEngine(
                model=str(app_tts.get("model") or os.getenv("MINIMAX_MODEL") or "speech-02-turbo"),
                base_url=str(app_tts.get("base_url") or "https://api.minimax.chat/v1/t2a_v2"),
                sample_rate=sample,
                language_boost=str(
                    app_tts.get("language_boost")
                    or os.getenv("MINIMAX_LANGUAGE_BOOST")
                    or "Chinese"
                ),
                emotion=(app_tts.get("emotion") or os.getenv("MINIMAX_EMOTION") or None),
            )
            # 有 Key 但会员过期/403 时，合成阶段自动切免费语音
            return FallbackTTSEngine(primary, free, silent)
        except ValueError as e:
            logger.warning("MiniMax 不可用 (%s)，改用免费 edge-tts", e)
            return FallbackTTSEngine(free, silent)
    if provider == "mock":
        return MockTTSEngine()
    raise ValueError(f"未知 TTS provider: {provider}")
