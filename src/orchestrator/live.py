"""直播编排：脚本播报 + 半自动互动。"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from broadcast.avatar_meta import load_avatar_meta
from broadcast.config import AppConfig, RoomConfig, resolve_voice_id
from broadcast.lipsync import create_lipsync_engine
from broadcast.pipeline import build_room_playlist, run_lipsync_batch, run_tts_batch
from broadcast.stream import push_rtmp
from broadcast.stream_manager import StreamManager
from broadcast.tts import create_tts_engine
from engines.actions import MatchContext, match_action
from engines.llm import create_llm_engine
from engines.moderation import create_moderator

logger = logging.getLogger("orchestrator.live")


class LiveState(str, Enum):
    IDLE = "idle"
    READING = "reading"
    THINKING = "thinking"
    SPEAKING = "speaking"
    STOPPED = "stopped"
    SCRIPT = "script"


@dataclass(order=True)
class PrioritizedItem:
    sort_key: tuple
    item: Any = field(compare=False)


@dataclass
class InputItem:
    text: str
    user_key: str = "op"
    priority: int = 10
    is_gift: bool = False
    action_hint: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class LiveStatus:
    room_id: str
    state: LiveState = LiveState.STOPPED
    phase: str = "stopped"
    queue_length: int = 0
    last_reply: str = ""
    last_error: str = ""
    mode: str = "interactive"
    running: bool = False
    platform: str = "preview"
    runtime_mode: str = "cloud"
    phase_label: str = "未开播"
    # 预览：待机静止图 + 说话口型成片（浏览器播放；待机不循环视频）
    idle_video_url: str = ""
    portrait_url: str = ""
    last_video_url: str = ""
    preview_video_url: str = ""


PHASE_LABELS = {
    "idle": "等待互动",
    "reading": "收到消息",
    "thinking": "思考中…",
    "speaking": "正在说话",
    "script": "脚本播报中",
    "stopped": "未开播",
}


EventCallback = Callable[[dict], None]


class LiveOrchestrator:
    def __init__(
        self,
        app: AppConfig,
        room: RoomConfig,
        *,
        mock: bool = False,
        dry_run_stream: bool = False,
        on_event: EventCallback | None = None,
        runtime_mode: str = "cloud",
        platform: str = "preview",
        engine_overrides: dict | None = None,
    ):
        self.app = app
        self.room = room
        self.mock = mock
        self.dry_run_stream = dry_run_stream
        self.on_event = on_event
        self.runtime_mode = runtime_mode
        self.platform = platform

        self.state = LiveState.STOPPED
        self.mode = "interactive"
        self._q: queue.PriorityQueue[PrioritizedItem] = queue.PriorityQueue()
        self._seq = 0
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        max_turns = int(app.section("llm").get("max_history_turns") or 6)
        self._history: deque[dict[str, str]] = deque(maxlen=max(2, 2 * max_turns))
        self.last_reply = ""
        self.last_error = ""
        self.idle_video_url = ""
        self.portrait_url = ""
        self.last_video_url = ""
        self._user_hits: dict[str, list[float]] = {}
        self._interrupt = threading.Event()

        llm_cfg = {**app.section("llm"), **((engine_overrides or {}).get("llm") or {})}
        tts_cfg = {**app.section("tts"), **((engine_overrides or {}).get("tts") or {})}
        avatar_cfg = {**app.section("avatar"), **((engine_overrides or {}).get("avatar") or {})}

        mock_llm = mock or bool((engine_overrides or {}).get("mock_llm"))
        mock_tts = mock or bool((engine_overrides or {}).get("mock_tts"))
        mock_avatar = mock or bool((engine_overrides or {}).get("mock_avatar"))

        self.llm = create_llm_engine(llm_cfg, mock=mock_llm)
        self.tts = create_tts_engine(tts_cfg, mock=mock_tts)
        self.lipsync = create_lipsync_engine(avatar_cfg, mock=mock_avatar)
        self.moderator = create_moderator(app.section("moderation"))
        self.stream_mgr: StreamManager | None = None
        self._limits = app.section("limits")
        self.engine_info = {
            "llm": llm_cfg.get("provider"),
            "tts": tts_cfg.get("provider"),
            "avatar": avatar_cfg.get("provider"),
            "runtime_mode": runtime_mode,
            "platform": platform,
            "dry_run": dry_run_stream,
        }

    def _media_url(self, path: Path | None) -> str:
        """data 下文件 → /media/... 供控制台预览播放。"""
        if path is None:
            return ""
        try:
            data_root = (self.app.root / "data").resolve()
            rel = path.resolve().relative_to(data_root)
            return "/media/" + rel.as_posix()
        except Exception:
            return ""

    # ---------- public ----------
    def status(self) -> LiveStatus:
        phase = self.state.value
        # 说话中：口型成片；待机：静止正脸图（不循环 idle 视频）
        if phase == "speaking" and self.last_video_url:
            preview = self.last_video_url
        else:
            preview = self.portrait_url or self.idle_video_url or self.last_video_url
        return LiveStatus(
            room_id=self.room.room_id,
            state=self.state,
            phase=phase,
            queue_length=self._q.qsize(),
            last_reply=self.last_reply,
            last_error=self.last_error,
            mode=self.mode,
            running=self._worker is not None and self._worker.is_alive(),
            platform=self.platform,
            runtime_mode=self.runtime_mode,
            phase_label=PHASE_LABELS.get(phase, phase),
            idle_video_url=self.idle_video_url,
            portrait_url=self.portrait_url,
            last_video_url=self.last_video_url,
            preview_video_url=preview,
        )

    def start(self, mode: str = "interactive", rtmp_url: str | None = None) -> None:
        if self._worker and self._worker.is_alive():
            if self._stop.is_set():
                # 上一次 stop() 已发信号但工作线程还没退出（可能卡在 TTS/口型）：等它收尾
                self._worker.join(timeout=10.0)
            if self._worker.is_alive():
                raise RuntimeError("房间已在直播中")
        self.mode = mode
        self._stop.clear()
        self.last_error = ""

        rtmp = rtmp_url or self.room.full_rtmp_url()
        if self.dry_run_stream:
            rtmp = ""  # StreamManager 空 url 不拉起 ffmpeg

        avatar_dir = self.room.avatar_path(self.app.root)
        meta = load_avatar_meta(avatar_dir)
        idle = meta.default_action_path(avatar_dir, self.room.avatar.default_action)
        if idle is None:
            raise FileNotFoundError("缺少 idle/动作视频，请先准备 data/avatars/demo/actions")

        self.stream_mgr = StreamManager(rtmp, self.app.section("stream"))

        self.idle_video_url = self._media_url(idle)
        # 正脸图作浏览器「静止待机」；无图时前端用 idle 视频首帧定格
        try:
            src = getattr(meta, "source_image", None) or "source/photo.jpg"
            src_path = avatar_dir / src
            if not src_path.is_file():
                for cand in (
                    avatar_dir / "source" / "photo.jpg",
                    avatar_dir / "source" / "photo.png",
                ):
                    if cand.is_file():
                        src_path = cand
                        break
            self.portrait_url = self._media_url(src_path) if src_path.is_file() else ""
        except Exception:
            self.portrait_url = ""

        if mode == "script":
            self._worker = threading.Thread(target=self._run_script_mode, daemon=True)
        else:
            # 真 RTMP 仍需 idle 循环垫片；浏览器预览由前端「静止→说话→静止」
            self.stream_mgr.start_idle_loop(idle)
            self.state = LiveState.IDLE
            self._emit(
                {
                    "type": "status",
                    "phase": "idle",
                    "queue_length": 0,
                    "idle_video_url": self.idle_video_url,
                    "portrait_url": self.portrait_url,
                    "video_url": self.portrait_url or self.idle_video_url,
                    "loop": False,
                    "stage": "still",
                }
            )
            # 开场白：走完整 TTS+口型，前端收到 ai_response 再播说话视频
            if self.room.persona.greeting:
                self.enqueue(
                    InputItem(
                        text=self.room.persona.greeting,
                        user_key="system",
                        priority=80,
                        action_hint="wave",
                    )
                )
            self._worker = threading.Thread(target=self._run_interactive_loop, daemon=True)
        self._worker.start()
        self._emit(
            {
                "type": "status",
                "phase": self.state.value,
                "queue_length": self._q.qsize(),
                "idle_video_url": self.idle_video_url,
                "portrait_url": self.portrait_url,
                "video_url": (
                    self.last_video_url
                    if self.state == LiveState.SPEAKING
                    else (self.portrait_url or self.idle_video_url)
                ),
                "loop": False,
                "stage": "still" if self.state == LiveState.IDLE else "speaking",
            }
        )

    def stop(self) -> None:
        self._stop.set()
        self._interrupt.set()
        # 清空队列
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        if self.stream_mgr:
            self.stream_mgr.stop()
        if self._worker and self._worker.is_alive() and threading.current_thread() is not self._worker:
            self._worker.join(timeout=3.0)
        self.state = LiveState.STOPPED
        self._emit({"type": "status", "phase": "stopped", "queue_length": 0})

    def interrupt(self) -> None:
        """打断当前说话并清空普通队列（保留后续新消息需重新发送）。"""
        self._interrupt.set()
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        # 正在播放的片段也立即切回 idle，而不是等它播完
        if self.stream_mgr:
            try:
                self.stream_mgr.abort_to_idle()
            except Exception:
                logger.exception("abort_to_idle failed")
        self._emit({"type": "status", "phase": "idle", "queue_length": 0, "interrupted": True})

    def enqueue(self, item: InputItem) -> tuple[bool, str]:
        if self._stop.is_set() or (
            self.state == LiveState.STOPPED and not (self._worker and self._worker.is_alive())
        ):
            return False, "未开播"
        if not self._allow_user(item.user_key):
            return False, "发送太频繁，请稍后再试"
        max_q = int(self._limits.get("max_queue") or 50)
        if self._q.qsize() >= max_q:
            return False, "队列已满"
        text = (item.text or "").strip()
        if not text:
            return False, "空内容"
        if not self.moderator.check(text) and item.user_key != "system":
            return False, "内容未通过审核"

        self._seq += 1
        # 优先级高的先处理：priority 大 → sort 小
        pri = PrioritizedItem(sort_key=(-item.priority, self._seq), item=item)
        self._q.put(pri)
        self._emit(
            {
                "type": "status",
                "phase": self.state.value,
                "queue_length": self._q.qsize(),
            }
        )
        return True, item.id

    # ---------- internal ----------
    def _emit(self, event: dict) -> None:
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                logger.exception("on_event error")

    def _allow_user(self, user_key: str) -> bool:
        if user_key in ("system", "op_urgent"):
            return True
        limit = int(self._limits.get("user_msg_per_30s") or 3)
        now = time.time()
        hits = self._user_hits.setdefault(user_key, [])
        hits[:] = [t for t in hits if now - t < 30]
        # 清掉长时间不活跃用户的空记录，避免字典无限增长
        stale = [k for k, v in self._user_hits.items() if not v and k != user_key]
        for k in stale:
            del self._user_hits[k]
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def _run_script_mode(self) -> None:
        try:
            self.state = LiveState.SCRIPT
            self._emit({"type": "status", "phase": "script", "queue_length": 0})
            run_tts_batch(self.app, self.room, mock=self.mock, engine=self.tts)
            run_lipsync_batch(self.app, self.room, mock=self.mock, engine=self.lipsync)
            _, single = build_room_playlist(self.app, self.room, make_single_file=True)
            if not single or not single.is_file():
                raise RuntimeError("脚本成片失败")
            rtmp = self.room.full_rtmp_url()
            if self.dry_run_stream or not rtmp:
                logger.info("script dry-run 成片: %s", single)
                self.last_reply = f"script ready: {single}"
                self._emit({"type": "ai_response", "text": self.last_reply, "latency_ms": 0})
            else:
                push_rtmp(
                    single,
                    rtmp,
                    self.app.section("stream"),
                    dry_run=False,
                    loop=False,
                    stop_event=self._stop,
                )
        except Exception as e:
            self.last_error = str(e)
            logger.exception("script mode failed")
            self._emit({"type": "error", "code": "script_failed", "message": str(e)})
        finally:
            self.state = LiveState.STOPPED
            self._emit({"type": "status", "phase": "stopped", "queue_length": 0})

    def _run_interactive_loop(self) -> None:
        while not self._stop.is_set():
            try:
                try:
                    pri = self._q.get(timeout=0.3)
                except queue.Empty:
                    if self.state not in (LiveState.SPEAKING, LiveState.THINKING, LiveState.READING):
                        self.state = LiveState.IDLE
                    continue
                item: InputItem = pri.item
                self._handle_one(item)
            except Exception as e:
                self.last_error = str(e)
                logger.exception("handle failed")
                self._emit({"type": "error", "code": "handle_failed", "message": str(e)})
                self.state = LiveState.IDLE

        if self.stream_mgr:
            self.stream_mgr.stop()
        self.state = LiveState.STOPPED

    def _handle_one(self, item: InputItem) -> None:
        if self._stop.is_set():
            return
        self._interrupt.clear()
        t0 = time.time()
        self.state = LiveState.READING
        self._emit({"type": "status", "phase": "reading", "queue_length": self._q.qsize()})

        user_text = item.text
        # 开场白特殊：直接用人设 greeting
        if item.user_key == "system" and self.room.persona.greeting:
            reply = self.room.persona.greeting
        else:
            self.state = LiveState.THINKING
            self._emit({"type": "status", "phase": "thinking", "queue_length": self._q.qsize()})
            reply = self._llm_reply(user_text)

        if self._stop.is_set() or self._interrupt.is_set():
            self.state = LiveState.IDLE
            return

        from engines.llm import clean_live_reply

        max_chars = int(self.app.section("llm").get("max_reply_chars") or 80)
        reply = clean_live_reply(reply, max_chars=max_chars)
        if not reply:
            # thinking 模型吐草稿时，用演示短句兜底，避免念英文规划
            from engines.llm import MockLLMEngine

            reply = clean_live_reply(
                MockLLMEngine().chat([{"role": "user", "content": user_text}]),
                max_chars=max_chars,
            ) or "谢谢支持呀～"
        reply = self.moderator.sanitize(reply)
        reply = clean_live_reply(reply, max_chars=max_chars) or reply[:max_chars]

        action = item.action_hint or match_action(
            MatchContext(
                text=user_text + reply,
                priority=item.priority,
                is_gift=item.is_gift,
            )
        )

        self.state = LiveState.SPEAKING
        self._emit(
            {
                "type": "status",
                "phase": "speaking",
                "queue_length": self._q.qsize(),
                "idle_video_url": self.idle_video_url,
            }
        )

        clip = self._synth_and_lipsync(reply, action)
        if self._stop.is_set() or self._interrupt.is_set():
            self.state = LiveState.IDLE
            return

        video_url = self._media_url(clip) if clip else ""
        if video_url:
            self.last_video_url = video_url

        if self.stream_mgr and clip:
            if self.dry_run_stream or not self.stream_mgr.rtmp_url:
                logger.info("dry-run speak clip=%s url=%s text=%s", clip, video_url, reply)
            else:
                self.stream_mgr.play_once(clip, resume_idle=True)

        latency = int((time.time() - t0) * 1000)
        self.last_reply = reply
        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": reply})
        self._emit(
            {
                "type": "ai_response",
                "text": reply,
                "action": action,
                "latency_ms": latency,
                "input_id": item.id,
                "video_url": video_url,
                "loop": False,
                "stage": "speaking",
                "has_audio": True,
            }
        )
        self.state = LiveState.IDLE
        # 说完：通知前端回静止（不要 loop idle 视频）
        self._emit(
            {
                "type": "status",
                "phase": "idle",
                "queue_length": self._q.qsize(),
                "idle_video_url": self.idle_video_url,
                "portrait_url": self.portrait_url,
                "video_url": self.portrait_url or self.idle_video_url,
                "loop": False,
                "stage": "still",
                "last_video_url": self.last_video_url,
            }
        )

    def _llm_reply(self, user_text: str) -> str:
        base = self.room.persona.system_prompt or "你是直播间助手，回复简短口语化。"
        # 强制直播口播约束，抑制 thinking 模型输出英文草稿
        sys_prompt = (
            f"{base}\n\n"
            "【输出规则】只输出一句可直接口播的中文，不超过40字；"
            "不要思考过程、不要英文、不要 markdown、不要列表编号。"
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": sys_prompt}]
        messages.extend(list(self._history))
        messages.append({"role": "user", "content": user_text})
        try:
            reply = self.llm.chat(
                messages,
                temperature=self.room.persona.temperature,
            )
            if not (reply or "").strip():
                raise RuntimeError("LLM 返回空内容")
            return reply.strip()
        except Exception as e:
            # 模型未 pull / 服务瞬时失败 / 空回复时不中断直播，回落演示回复
            logger.warning("LLM 调用失败，回落 Mock：%s", e)
            from engines.llm import MockLLMEngine

            fallback = MockLLMEngine().chat(messages)
            self.last_error = f"LLM 回落演示: {e}"
            return fallback

    def _synth_and_lipsync(self, text: str, action: str) -> Path | None:
        voice = resolve_voice_id(self.app, self.room)
        ts = int(time.time() * 1000)
        audio_dir = self.app.audio_dir / self.room.room_id / "live"
        clips_dir = self.app.clips_dir / self.room.room_id / "live"
        audio_dir.mkdir(parents=True, exist_ok=True)
        clips_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{ts}.wav"
        out_path = clips_dir / f"{ts}.mp4"

        self.tts.synth(text, voice, audio_path)

        avatar_dir = self.room.avatar_path(self.app.root)
        meta = load_avatar_meta(avatar_dir)
        ref = meta.action_path(avatar_dir, action)
        if ref is None or not ref.is_file():
            ref = meta.default_action_path(avatar_dir, self.room.avatar.default_action)
        if ref is None:
            raise FileNotFoundError("无参考视频")
        self.lipsync.run(audio_path, ref, out_path)
        return out_path
