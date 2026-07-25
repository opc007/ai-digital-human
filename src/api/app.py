"""FastAPI 应用入口。"""

from __future__ import annotations

import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

from broadcast.avatar_meta import load_avatar_meta
from broadcast.config import load_app_config, load_room_config, project_root
from broadcast.logging_utils import setup_logging
from broadcast.presets import get_platform, get_runtime_mode, list_platforms, list_runtime_modes
from db.models import Avatar, LiveEvent, LiveRoom, Persona
from db.session import get_session, init_db
from orchestrator.live import InputItem, LiveOrchestrator

from .runtime import hub

logger = logging.getLogger("api")
ROOT = project_root()
WEB_DIR = ROOT / "web"


def _api_token() -> str:
    return os.getenv("API_TOKEN") or "dev-token"


def require_token(authorization: str | None = Header(default=None)) -> None:
    # dev 环境可跳过：APP_ENV=dev 且未强制
    if os.getenv("APP_ENV", "dev") == "dev" and os.getenv("REQUIRE_AUTH", "0") != "1":
        return
    token = _api_token()
    if not authorization:
        raise HTTPException(401, "未登录")
    raw = authorization.replace("Bearer ", "").strip()
    if not secrets.compare_digest(raw, token):
        raise HTTPException(401, "Token 无效")


class LoginBody(BaseModel):
    username: str = "admin"
    password: str = "admin"


class StartBody(BaseModel):
    room_id: str = "demo"
    mode: str = "interactive"  # interactive | script
    # 用户向字段
    platform: str = "preview"  # preview | douyin | kuaishou | wechat | xiaohongshu | tiktok
    runtime_mode: str = "cloud"  # cloud | local | hybrid
    rtmp_url: str | None = None
    rtmp_key: str | None = None
    # 角色 / 造型（Vidu 式）
    avatar_id: str | None = None  # 角色 slug，如 demo / c12ab34
    look_id: str | None = None  # 造型 id，默认 default
    # 画面：portrait 竖屏 | landscape 横屏 | square；fit=contain 完整人物
    orientation: str | None = None
    fit: str | None = None  # contain | cover
    # 兼容旧参数
    mock: bool | None = None
    dry_run: bool | None = None


class CharacterCreateBody(BaseModel):
    name: str = "新角色"


class LookCreateBody(BaseModel):
    name: str = "新造型"


class InputBody(BaseModel):
    text: str
    user_key: str = "op1"
    priority: int = 10
    is_gift: bool = False
    action_hint: str | None = None


class PersonaUpdate(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    greeting: str | None = None
    temperature: float | None = None


class SettingsSaveBody(BaseModel):
    """键值对，对应 .env 字段。"""
    values: dict[str, str] = Field(default_factory=dict)


class SettingsTestBody(BaseModel):
    target: str  # deepseek | minimax | ollama


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    setup_logging()
    init_db()
    import asyncio

    hub.set_loop(asyncio.get_running_loop())
    logger.info("API started root=%s", ROOT)
    yield
    for rid in list(hub.orchestrators.keys()):
        hub.unregister(rid)


app = FastAPI(title="AI Digital Human MVP", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # "*" 与 credentials=True 是矛盾组合，浏览器会拒绝
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def index():
    index_path = WEB_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(
            index_path,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    return {"message": "web/index.html missing", "docs": "/docs"}


@app.get("/materials")
def materials_page():
    path = WEB_DIR / "materials.html"
    if path.is_file():
        return FileResponse(path, headers={"Cache-Control": "no-store, max-age=0"})
    raise HTTPException(404, "materials.html missing")


def _media_file_response(file_path: str):
    """安全提供 data 下的素材预览。"""
    base = (ROOT / "data").resolve()
    target = (base / file_path).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404)
    # 预览视频需正确 MIME，否则部分浏览器不播
    media_map = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    return FileResponse(
        target,
        media_type=media_map.get(target.suffix.lower()),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.api_route("/media/{file_path:path}", methods=["GET", "HEAD"])
def media_files(file_path: str):
    # 部分浏览器对 <video> 会先发 HEAD，需与 GET 一样可用
    return _media_file_response(file_path)


@app.get("/static/{file_path:path}")
def static_no_cache(file_path: str):
    """静态资源禁用缓存，保证控制台更新即时生效。"""
    target = (WEB_DIR / file_path).resolve()
    if not target.is_relative_to(WEB_DIR.resolve()) or not target.is_file():
        raise HTTPException(404)
    media = "text/css" if target.suffix == ".css" else (
        "application/javascript" if target.suffix == ".js" else None
    )
    return FileResponse(
        target,
        media_type=media,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/health")
def health():
    return {"ok": True, "rooms": list(hub.orchestrators.keys())}


def _probe_ollama(base_url: str) -> bool:
    try:
        import httpx

        # .../v1 -> 根 /api/tags
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        r = httpx.get(f"{root}/api/tags", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


@app.get("/api/v1/bootstrap")
def bootstrap():
    """控制台首屏：平台、算力模式、密钥是否已配置（不返回密钥本身）。"""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from broadcast.ffmpeg_util import find_ffmpeg
    from broadcast.avatar_meta import load_avatar_meta
    from broadcast.i2v_geeknow import i2v_configured

    deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))
    minimax = bool(os.getenv("MINIMAX_API_KEY"))
    free_raw = os.getenv("USE_FREE_TTS")
    free_tts = (free_raw if free_raw is not None else "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    ollama_url = os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
    ollama_ok = _probe_ollama(ollama_url)
    ff = find_ffmpeg()
    video_i2v = i2v_configured()

    avatar_ok = False
    avatar_actions = 0
    try:
        meta = load_avatar_meta(ROOT / "data" / "avatars" / "demo")
        avatar_actions = len(meta.actions)
        avatar_ok = all((ROOT / "data" / "avatars" / "demo" / a.file).is_file() for a in meta.actions)
    except Exception:
        pass

    return {
        "platforms": list_platforms(),
        "runtime_modes": list_runtime_modes(),
        "keys": {
            "deepseek": deepseek,
            "minimax": minimax,
            "free_tts": free_tts,
            "video_i2v": video_i2v,
            "ollama_base_url": ollama_url,
            "ollama_online": ollama_ok,
            "has_any_cloud_key": deepseek or minimax,
            "ffmpeg": bool(ff),
            "ffmpeg_path": ff or "",
            "musetalk_root": bool(os.getenv("MUSETALK_ROOT")),
            "avatar_ready": avatar_ok,
            "avatar_actions": avatar_actions,
        },
        "defaults": {
            "platform": "preview",
            "runtime_mode": "cloud",
            "room_id": "demo",
        },
        "tips": [
            "进来先点「配置」填图生视频接口 / Key / 模型，再去素材中心建角色",
            "声音默认「免费测试」（微软语音），先跑通流程；以后在配置关掉免费开关并填 MiniMax 即可",
            "第一次用：选「仅预览」，点开始直播即可试玩",
        ],
    }


@app.get("/api/v1/platforms")
def api_platforms():
    return list_platforms()


@app.get("/api/v1/runtime-modes")
def api_runtime_modes():
    return list_runtime_modes()


@app.get("/api/v1/settings")
def get_settings(_: None = Depends(require_token)):
    """读取云端/本地配置（供控制台表单填写）。"""
    from broadcast.settings_store import get_settings_for_ui

    return get_settings_for_ui()


@app.put("/api/v1/settings")
def put_settings(body: SettingsSaveBody, _: None = Depends(require_token)):
    """保存配置到 .env，并立即对当前进程生效（下一场开播使用）。"""
    from broadcast.settings_store import save_settings

    try:
        data = save_settings(body.values or {})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "message": "已保存，下一场开播立即生效", **data}


@app.post("/api/v1/settings/test")
def test_settings(body: SettingsTestBody, _: None = Depends(require_token)):
    """连通性测试：deepseek / minimax / ollama。"""
    from broadcast.settings_store import apply_settings_to_engines
    import httpx

    apply_settings_to_engines()
    target = (body.target or "").lower()

    if target == "deepseek":
        key = os.getenv("DEEPSEEK_API_KEY") or ""
        base = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
        model = os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"
        if not key:
            raise HTTPException(400, "请先填写 DeepSeek API Key 并保存")
        try:
            r = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "回复：ok"}],
                    "max_tokens": 8,
                },
                timeout=20.0,
            )
            if r.status_code >= 400:
                raise HTTPException(400, f"DeepSeek 返回 {r.status_code}: {r.text[:200]}")
            return {"ok": True, "message": "DeepSeek 连通正常", "model": model}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"DeepSeek 连接失败: {e}") from e

    if target == "minimax":
        key = os.getenv("MINIMAX_API_KEY") or ""
        gid = os.getenv("MINIMAX_GROUP_ID") or ""
        if not key:
            raise HTTPException(400, "请先填写 MiniMax API Key 并保存")
        from broadcast.tts import normalize_minimax_language_boost

        lang = normalize_minimax_language_boost(os.getenv("MINIMAX_LANGUAGE_BOOST"), "Chinese")
        model = os.getenv("MINIMAX_MODEL") or "speech-02-turbo"
        # 仅校验 key 非空 + 可选请求；不同账号接口差异大，做轻量检查
        url = "https://api.minimax.chat/v1/t2a_v2"
        if gid:
            url = f"{url}?GroupId={gid}"
        try:
            r = httpx.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "text": "测试",
                    "stream": False,
                    "language_boost": lang,
                    "voice_setting": {
                        "voice_id": os.getenv("MINIMAX_VOICE_ID") or "male-qn-qingse",
                        "speed": 1.0,
                        "vol": 1.0,
                        "pitch": 0,
                        "text_normalization": True,
                    },
                    "audio_setting": {
                        "sample_rate": 16000,
                        "bitrate": 128000,
                        "format": "mp3",
                        "channel": 1,
                    },
                },
                timeout=30.0,
            )
            # 200 或业务 JSON 均可能；401/403 明确失败
            if r.status_code in (401, 403):
                raise HTTPException(400, f"MiniMax 鉴权失败: {r.text[:200]}")
            if r.status_code >= 500:
                raise HTTPException(400, f"MiniMax 服务异常: {r.status_code}")
            # 4xx 其它也可能是参数问题但 key 有效
            return {
                "ok": True,
                "message": f"MiniMax 已响应（HTTP {r.status_code}），密钥可用或请核对 GroupId/音色",
                "status_code": r.status_code,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"MiniMax 连接失败: {e}") from e

    if target == "ollama":
        base = os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
        if _probe_ollama(base):
            return {"ok": True, "message": f"Ollama 在线：{base}"}
        raise HTTPException(400, f"未检测到 Ollama，请先启动服务：{base}")

    raise HTTPException(400, "target 应为 deepseek / minimax / ollama")


@app.post("/api/v1/auth/login")
def login(body: LoginBody):
    # MVP：固定账号
    if body.username == "admin" and body.password in ("admin", "admin123"):
        return {"token": _api_token(), "username": "admin"}
    raise HTTPException(401, "用户名或密码错误")


# ---------- 素材 / 生视频 / 声音 ----------


class GenerateBody(BaseModel):
    action: str
    avatar_id: str = "demo"
    prompt: str | None = None


class VoicePreviewBody(BaseModel):
    text: str = "大家好，欢迎来到直播间。"
    mock: bool = False
    voice_id: str | None = None  # 试听指定音色，不传则用当前默认


class VoiceSelectBody(BaseModel):
    voice_id: str


class PreflightBody(BaseModel):
    platform: str = "preview"
    runtime_mode: str = "cloud"
    rtmp_key: str | None = None
    avatar_id: str | None = None
    look_id: str | None = None


class ChatTestBody(BaseModel):
    text: str = "你好"
    system_prompt: str | None = None


@app.get("/api/v1/assets")
def api_list_assets(
    avatar_id: str = "demo",
    look_id: str = "default",
    _: None = Depends(require_token),
):
    from broadcast.characters import list_look_assets

    return list_look_assets(avatar_id, look_id)


@app.post("/api/v1/assets/source")
async def api_upload_source(
    file: UploadFile = File(...),
    avatar_id: str = Form("demo"),
    look_id: str = Form("default"),
    _: None = Depends(require_token),
):
    from broadcast.characters import save_look_image

    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "图片不要超过 20MB")
    return save_look_image(avatar_id, look_id, data, file.filename or "photo.jpg")


@app.post("/api/v1/characters")
def api_create_character(body: CharacterCreateBody, _: None = Depends(require_token)):
    from broadcast.characters import create_character

    try:
        return create_character(body.name)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/v1/characters")
def api_list_characters(_: None = Depends(require_token)):
    from broadcast.characters import list_characters

    return {"items": list_characters()}


@app.get("/api/v1/characters/{character_id}")
def api_get_character(character_id: str, _: None = Depends(require_token)):
    from broadcast.characters import summarize_character, avatar_root
    from broadcast.assets import safe_avatar_id

    cid = safe_avatar_id(character_id)
    if not avatar_root(cid).exists():
        raise HTTPException(404, "角色不存在")
    return summarize_character(cid)


@app.post("/api/v1/characters/{character_id}/looks")
def api_add_look(character_id: str, body: LookCreateBody, _: None = Depends(require_token)):
    from broadcast.characters import add_look

    try:
        return add_look(character_id, body.name)
    except Exception as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/v1/characters/{character_id}/looks/{look_id}/generate")
def api_generate_look(
    character_id: str,
    look_id: str,
    force: bool = True,
    _: None = Depends(require_token),
):
    from broadcast.characters import generate_look_videos

    try:
        return generate_look_videos(character_id, look_id, force=force)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, f"生成失败: {e}") from e


@app.delete("/api/v1/characters/{character_id}/looks/{look_id}")
def api_delete_look(character_id: str, look_id: str, _: None = Depends(require_token)):
    from broadcast.characters import delete_look

    try:
        return delete_look(character_id, look_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.delete("/api/v1/characters/{character_id}")
def api_delete_character(character_id: str, _: None = Depends(require_token)):
    from broadcast.characters import delete_character

    try:
        return delete_character(character_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/v1/assets/actions/upload")
async def api_upload_action(
    file: UploadFile = File(...),
    action: str = Form(...),
    avatar_id: str = Form("demo"),
    look_id: str = Form("default"),
    category: str = Form(""),
    _: None = Depends(require_token),
):
    from broadcast.characters import save_look_action

    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(400, "视频不要超过 200MB")
    return save_look_action(
        avatar_id,
        look_id,
        data,
        action,
        category=category or None,
    )


@app.delete("/api/v1/assets/actions/{action}")
def api_delete_action(
    action: str,
    avatar_id: str = "demo",
    look_id: str = "default",
    _: None = Depends(require_token),
):
    from broadcast.characters import delete_look_action

    return delete_look_action(avatar_id, look_id, action)


@app.get("/api/v1/comfyui/status")
def api_comfyui_status(_: None = Depends(require_token)):
    from broadcast.comfyui_client import ComfyUIClient, load_workflow_template, workflow_path
    from broadcast.settings_store import apply_settings_to_engines

    apply_settings_to_engines()
    client = ComfyUIClient()
    h = client.health()
    wf = load_workflow_template()
    return {
        **h,
        "workflow_ready": wf is not None,
        "workflow_path": str(workflow_path()),
    }


@app.post("/api/v1/assets/generate")
def api_generate_action(body: GenerateBody, _: None = Depends(require_token)):
    from broadcast.gen_service import start_generate_action
    from broadcast.settings_store import apply_settings_to_engines

    apply_settings_to_engines()
    try:
        job = start_generate_action(
            body.action,
            avatar_id=body.avatar_id,
            prompt_override=body.prompt,
        )
        return {"ok": True, "job": job}
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except ConnectionError as e:
        raise HTTPException(503, str(e)) from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e


class PresetGenerateBody(BaseModel):
    avatar_id: str = "demo"
    look_id: str = "default"
    force: bool = True  # 覆盖已有动作
    orientation: str = "portrait"  # portrait | landscape


@app.post("/api/v1/assets/generate-preset")
def api_generate_preset(body: PresetGenerateBody, _: None = Depends(require_token)):
    """
    造型图 → 图生视频模型 → idle 待机片（异步）。
    提示词由产品内置；需先在配置填写 VIDEO_I2V_*。
    """
    from broadcast.i2v_service import start_idle_i2v_job
    from broadcast.settings_store import apply_settings_to_engines

    apply_settings_to_engines()
    try:
        return start_idle_i2v_job(
            body.avatar_id or "demo",
            body.look_id or "default",
            force=body.force,
        )
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("generate-preset failed")
        raise HTTPException(500, f"生成待机视频失败: {e}") from e


@app.get("/api/v1/assets/jobs")
def api_list_jobs(_: None = Depends(require_token)):
    from broadcast.comfyui_client import list_jobs

    return {"jobs": list_jobs(30)}


@app.get("/api/v1/assets/jobs/{job_id}")
def api_get_job(job_id: str, _: None = Depends(require_token)):
    from broadcast.comfyui_client import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@app.post("/api/v1/live/preflight")
def api_preflight(body: PreflightBody, _: None = Depends(require_token)):
    """开播前检查清单。"""
    from broadcast.preflight import run_preflight

    return run_preflight(
        platform=body.platform,
        runtime_mode=body.runtime_mode,
        rtmp_key=body.rtmp_key,
        avatar_id=body.avatar_id or "demo",
        look_id=body.look_id or "default",
    )


@app.post("/api/v1/demo/ensure")
def api_demo_ensure(_: None = Depends(require_token)):
    """新手一键：补齐可播演示素材（占位动作）。"""
    from broadcast.demo_bootstrap import ensure_demo_ready

    return ensure_demo_ready("demo")


@app.get("/api/v1/home")
def api_home(_: None = Depends(require_token)):
    """首页总览：进度、检查、下一步建议（产品自己判断该引导去哪）。"""
    from broadcast.assets import list_assets
    from broadcast.demo_bootstrap import ensure_demo_ready
    from broadcast.ffmpeg_util import find_ffmpeg
    from broadcast.preflight import run_preflight
    from broadcast.settings_store import apply_settings_to_engines

    apply_settings_to_engines()
    assets = list_assets("demo")
    pf = run_preflight(platform="preview", runtime_mode="cloud", rtmp_key=None)
    has_llm = bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))
    has_tts = bool(os.getenv("MINIMAX_API_KEY"))
    ff = bool(find_ffmpeg())

    steps = [
        {
            "id": "materials",
            "title": "准备形象素材",
            "done": bool(assets.get("ready")),
            "href": "/materials",
            "desc": f"动作 {assets.get('ready_count', 0)}/{assets.get('total_count', 0)}，idle "
            + ("已有" if any(a["name"] == "idle" and a["exists"] for a in assets.get("actions", [])) else "缺少"),
        },
        {
            "id": "config",
            "title": "声音与对话（可选）",
            "done": has_llm or has_tts,
            "href": "/#settings",
            "desc": (
                ("对话✓ " if has_llm else "对话用演示 ")
                + ("声音✓" if has_tts else "声音用演示")
            ),
        },
        {
            "id": "platform",
            "title": "选平台 / 推流码",
            "done": True,  # 预览随时可做
            "href": "/#live-setup",
            "desc": "新手请选「仅预览」，真播再填推流码",
        },
        {
            "id": "go",
            "title": "检查并开播",
            "done": bool(pf.get("can_start")),
            "href": "/#go-live",
            "desc": pf.get("summary") or "",
        },
    ]
    done_n = sum(1 for s in steps if s["done"])
    # 智能下一步
    next_step = next((s for s in steps if not s["done"]), steps[-1])
    if not assets.get("ready"):
        next_action = {
            "type": "ensure_demo",
            "label": "一键准备演示素材并预览",
            "primary": True,
        }
    elif pf.get("can_start"):
        next_action = {
            "type": "quick_preview",
            "label": "立即预览开播（3 秒上手）",
            "primary": True,
        }
    else:
        next_action = {
            "type": "fix",
            "label": f"去处理：{next_step['title']}",
            "href": next_step["href"],
            "primary": True,
        }

    return {
        "progress": {"done": done_n, "total": len(steps), "percent": int(100 * done_n / len(steps))},
        "steps": steps,
        "preflight": pf,
        "ffmpeg": ff,
        "keys": {"llm": has_llm, "tts": has_tts},
        "assets_ready": bool(assets.get("ready")),
        "next_action": next_action,
        "tips": [
            "第一次用：点绿色大按钮，系统自动准备演示素材并预览。",
            "正式直播：素材中心换成真人动作 → 云端配置填 Key → 选平台贴推流码。",
            "不会技术也没关系：先预览跑通，再慢慢替换素材和真声音。",
        ],
    }


@app.post("/api/v1/chat/test")
def api_chat_test(body: ChatTestBody, _: None = Depends(require_token)):
    """试聊：只跑 LLM，不推流、不口型。"""
    from broadcast.settings_store import apply_settings_to_engines
    from engines.llm import create_llm_engine

    apply_settings_to_engines()
    # 根据是否有 key / ollama 自动选
    has_cloud = bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))
    llm_cfg: dict[str, Any] = {
        "provider": "deepseek" if has_cloud else "mock",
        "base_url": os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1",
        "model": os.getenv("DEEPSEEK_MODEL") or "deepseek-chat",
    }
    # 若用户更可能用本地：探测 ollama（模型名由 create_llm_engine 自动对齐本机列表）
    if not has_cloud:
        try:
            from engines.llm import list_ollama_models

            base = os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
            if list_ollama_models(base):
                llm_cfg = {
                    "provider": "ollama",
                    "base_url": base,
                    "model": os.getenv("OLLAMA_MODEL") or "qwen2.5:7b",
                }
        except Exception:
            pass

    sys_p = body.system_prompt or "你是直播间助手，回复不超过30字，口语化。"
    sys_p = (
        f"{sys_p}\n【输出规则】只输出一句可直接口播的中文；不要思考过程、不要英文草稿。"
    )
    messages = [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": body.text or "你好"},
    ]
    provider = llm_cfg.get("provider")
    demo = provider == "mock"
    model_used = llm_cfg.get("model")
    try:
        from engines.llm import MockLLMEngine, clean_live_reply

        engine = create_llm_engine(llm_cfg, mock=demo)
        model_used = getattr(engine, "model", model_used)
        reply = clean_live_reply(engine.chat(messages), max_chars=80)
        if isinstance(engine, MockLLMEngine):
            provider = "mock"
            demo = True
        if not (reply or "").strip():
            raise RuntimeError("模型返回空内容或不可口播")
    except Exception as e:
        logger.warning("chat test primary failed (%s), fallback mock: %s", provider, e)
        from engines.llm import MockLLMEngine, clean_live_reply

        engine = create_llm_engine({"provider": "mock"}, mock=True)
        reply = clean_live_reply(engine.chat(messages), max_chars=80)
        provider = "mock"
        demo = True
    return {
        "ok": True,
        "reply": reply,
        "provider": provider,
        "demo": demo,
        "model": model_used,
    }


@app.get("/api/v1/voice")
def api_voice_list(runtime_mode: str = "cloud", _: None = Depends(require_token)):
    """音色目录：男女声分组 + 当前选中。"""
    from broadcast.voice_assets import list_voices

    return list_voices(runtime_mode=runtime_mode)


@app.post("/api/v1/voice/select")
def api_voice_select(body: VoiceSelectBody, _: None = Depends(require_token)):
    """选择音色并写入 .env。"""
    from broadcast.voice_assets import select_voice

    try:
        return select_voice(body.voice_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/v1/voice/sample")
async def api_voice_sample(
    file: UploadFile = File(...),
    _: None = Depends(require_token),
):
    from broadcast.voice_assets import save_sample

    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    return save_sample(data, file.filename or "sample.wav")


@app.post("/api/v1/voice/preview")
def api_voice_preview(body: VoicePreviewBody, _: None = Depends(require_token)):
    from broadcast.voice_assets import preview_tts

    try:
        return preview_tts(body.text, mock=body.mock, voice_id=body.voice_id)
    except Exception as e:
        raise HTTPException(500, f"TTS 失败: {e}") from e


@app.get("/api/v1/avatars")
def list_avatars(_: None = Depends(require_token)):
    """兼容旧接口：返回角色列表（含造型摘要）。"""
    from broadcast.characters import list_characters

    items = list_characters()
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "root_path": f"data/avatars/{c['id']}",
            "status": 1 if c.get("ready") else 0,
            "ready": c.get("ready"),
            "source_url": c.get("source_url"),
            "idle_url": c.get("idle_url"),
            "looks": c.get("looks") or [],
            "actions": [],
        }
        for c in items
    ]


@app.get("/api/v1/avatars/{avatar_id}")
def get_avatar(avatar_id: int, _: None = Depends(require_token)):
    with get_session() as db:
        a = db.get(Avatar, avatar_id)
        if not a:
            raise HTTPException(404, "avatar not found")
        meta = None
        try:
            meta = load_avatar_meta(ROOT / a.root_path).model_dump()
        except Exception as e:
            meta = {"error": str(e)}
        return {"id": a.id, "name": a.name, "root_path": a.root_path, "meta": meta}


@app.get("/api/v1/personas")
def list_personas(_: None = Depends(require_token)):
    with get_session() as db:
        rows = db.scalars(select(Persona)).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "system_prompt": p.system_prompt,
                "greeting": p.greeting,
                "temperature": p.temperature,
            }
            for p in rows
        ]


@app.put("/api/v1/personas/{persona_id}")
def update_persona(persona_id: int, body: PersonaUpdate, _: None = Depends(require_token)):
    with get_session() as db:
        p = db.get(Persona, persona_id)
        if not p:
            raise HTTPException(404)
        if body.name is not None:
            p.name = body.name
        if body.system_prompt is not None:
            p.system_prompt = body.system_prompt
        if body.greeting is not None:
            p.greeting = body.greeting
        if body.temperature is not None:
            p.temperature = body.temperature
        db.commit()
        # 同步到 yaml 房间人设（运行中下次开播生效；互动中热更新 orch 若存在）
        orch = hub.get("demo")
        if orch:
            if body.system_prompt is not None:
                orch.room.persona.system_prompt = body.system_prompt
            if body.greeting is not None:
                orch.room.persona.greeting = body.greeting
            if body.temperature is not None:
                orch.room.persona.temperature = body.temperature
        return {"ok": True}


def _build_engine_overrides(runtime_mode: str) -> dict:
    """根据用户选择的算力模式组装引擎配置。"""
    from broadcast.settings_store import apply_settings_to_engines

    apply_settings_to_engines()

    preset = get_runtime_mode(runtime_mode) or get_runtime_mode("cloud") or {}
    engines = preset.get("engines") or {}
    llm_p = engines.get("llm") or "deepseek"
    tts_p = engines.get("tts") or "minimax"
    avatar_p = engines.get("avatar") or "musetalk"

    llm_cfg: dict[str, Any] = {"provider": llm_p}
    tts_cfg: dict[str, Any] = {"provider": tts_p}
    avatar_cfg: dict[str, Any] = {"provider": avatar_p, "fallback_mock": True}

    if llm_p == "ollama":
        llm_cfg["base_url"] = os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
        preferred = os.getenv("OLLAMA_MODEL") or "qwen2.5:7b"
        try:
            from engines.llm import resolve_ollama_model

            llm_cfg["model"] = resolve_ollama_model(preferred, llm_cfg["base_url"]) or preferred
        except Exception:
            llm_cfg["model"] = preferred
    elif llm_p == "deepseek":
        llm_cfg["base_url"] = os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"
        llm_cfg["model"] = os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"

    # 会员过期时可设 USE_FREE_TTS=1（默认开），任意算力模式都走免费 edge-tts
    free_raw = os.getenv("USE_FREE_TTS")
    use_free = (free_raw if free_raw is not None else "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    env_tts = (os.getenv("TTS_PROVIDER") or "").strip().lower()
    if use_free or env_tts in ("local", "edge", "edge-tts", "free"):
        tts_cfg["provider"] = "local"
        tts_p = "local"
    elif tts_p == "local":
        tts_cfg["provider"] = "local"
    elif tts_p == "minimax":
        tts_cfg["default_voice_id"] = os.getenv("MINIMAX_VOICE_ID") or tts_cfg.get(
            "default_voice_id"
        )
        tts_cfg["provider"] = "minimax"

    # 无密钥时是否演示（免费 TTS 不算 mock：仍有真实人声）
    mock_llm = False
    mock_tts = False
    if preset.get("mock_llm_if_no_key") and llm_p != "ollama":
        if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")):
            mock_llm = True
    if preset.get("mock_tts_if_no_key") and tts_p == "minimax":
        if not os.getenv("MINIMAX_API_KEY"):
            # 无 MiniMax 时改用免费 edge，而不是静音演示
            tts_cfg["provider"] = "local"
            tts_p = "local"

    return {
        "llm": llm_cfg,
        "tts": tts_cfg,
        "avatar": avatar_cfg,
        "mock_llm": mock_llm,
        "mock_tts": mock_tts,
        "mock_avatar": False,
    }


@app.post("/api/v1/live/start")
def live_start(body: StartBody, _: None = Depends(require_token)):
    app_cfg = load_app_config()
    room = load_room_config(body.room_id, app_cfg)

    platform = get_platform(body.platform) or get_platform("preview") or {}
    runtime = get_runtime_mode(body.runtime_mode) or get_runtime_mode("cloud") or {}

    # 平台决定推流地址；预览强制 dry_run
    dry_run = body.dry_run if body.dry_run is not None else bool(platform.get("dry_run"))
    if body.platform == "preview":
        dry_run = True

    rtmp_url = body.rtmp_url or platform.get("rtmp_url") or room.stream.rtmp_url
    rtmp_key = body.rtmp_key if body.rtmp_key is not None else room.stream.rtmp_key

    if not dry_run and not (rtmp_key or "").strip():
        raise HTTPException(
            400,
            f"请填写{platform.get('name') or '平台'}的推流码。可先选「仅预览」试玩。",
        )

    # 开播前硬门槛（按选中角色/造型）
    from broadcast.preflight import run_preflight
    from broadcast.assets import safe_avatar_id
    from broadcast.characters import resolve_live_avatar_dir, summarize_character, look_has_idle

    char_id = safe_avatar_id(body.avatar_id or "demo")
    look_id = safe_avatar_id(body.look_id or "default") or "default"

    pf = run_preflight(
        platform=body.platform,
        runtime_mode=body.runtime_mode,
        rtmp_key=rtmp_key,
        avatar_id=char_id,
        look_id=look_id,
    )
    if not pf.get("can_start"):
        blocks = [c["message"] for c in pf.get("checks", []) if c.get("level") == "block"]
        raise HTTPException(400, "；".join(blocks) or "开播前检查未通过，请先处理阻断项")
    if not look_has_idle(char_id, look_id):
        raise HTTPException(400, "当前造型缺少 idle 待机视频，请到素材中心生成微动后再开播")

    room.stream.rtmp_url = rtmp_url or ""
    room.stream.rtmp_key = (rtmp_key or "").strip()
    room.stream.platform = body.platform

    # 绑定角色 / 造型（Vidu 式：选人再开播）
    try:
        room.avatar.dir = resolve_live_avatar_dir(char_id, look_id)
        info = summarize_character(char_id)
        if info.get("name"):
            room.title = room.title or info["name"]
    except Exception as e:
        logger.warning("bind character failed: %s", e)

    # 全局 mock 仅当用户显式传入
    force_mock = bool(body.mock) if body.mock is not None else False
    overrides = _build_engine_overrides(body.runtime_mode)
    if force_mock:
        overrides["mock_llm"] = True
        overrides["mock_tts"] = True

    # 画面方向：请求体 > 环境变量 > 默认竖屏（抖音）
    orient = (body.orientation or os.getenv("OUTPUT_ORIENTATION") or "portrait").strip().lower()
    fit = (body.fit or os.getenv("OUTPUT_FIT") or "contain").strip().lower()
    from broadcast.lipsync import resolve_output_size

    w, h, fit_n = resolve_output_size({"orientation": orient, "fit": fit})
    av = overrides.setdefault("avatar", {})
    av["orientation"] = orient
    av["fit"] = fit_n
    av["width"] = w
    av["height"] = h

    # DB 人设覆盖
    with get_session() as db:
        persona = db.scalar(select(Persona).limit(1))
        if persona:
            room.persona.system_prompt = persona.system_prompt or room.persona.system_prompt
            room.persona.greeting = persona.greeting or room.persona.greeting
            room.persona.temperature = persona.temperature
            room.persona.name = persona.name or room.persona.name

    def on_event(ev: dict) -> None:
        hub.broadcast(body.room_id, ev)
        try:
            with get_session() as db:
                db.add(
                    LiveEvent(
                        room_key=body.room_id,
                        type=str(ev.get("type") or "event"),
                        payload=json.dumps(ev, ensure_ascii=False),
                        latency_ms=int(ev.get("latency_ms") or 0),
                    )
                )
                db.commit()
        except Exception:
            logger.exception("persist event failed")

    orch = LiveOrchestrator(
        app_cfg,
        room,
        mock=False,
        dry_run_stream=dry_run,
        on_event=on_event,
        runtime_mode=body.runtime_mode,
        platform=body.platform,
        engine_overrides=overrides,
    )
    try:
        orch.start(mode=body.mode)
    except Exception as e:
        logger.exception("start failed")
        raise HTTPException(503, str(e)) from e

    # 开播成功后才落库"直播中"，避免失败启动留下脏状态
    with get_session() as db:
        lr = db.scalar(select(LiveRoom).where(LiveRoom.room_key == body.room_id))
        if lr:
            lr.status = 1
            lr.mode = body.mode
            lr.platform = body.platform
            lr.rtmp_url = room.stream.rtmp_url
            lr.started_at = _utcnow()
            lr.ended_at = None
            db.commit()

    hub.register(body.room_id, orch)
    return {
        "room_id": body.room_id,
        "status": "live",
        "mode": body.mode,
        "platform": body.platform,
        "platform_name": platform.get("name"),
        "runtime_mode": body.runtime_mode,
        "runtime_name": runtime.get("name"),
        "dry_run": dry_run,
        "engines": orch.engine_info,
        "message": (
            "预览已开始：待机静止，发文字后才会说话（语音+口型视频）"
            if dry_run
            else f"已开始向「{platform.get('name')}」推流，请到平台后台确认画面"
        ),
        "ws_url": f"/ws/live/{body.room_id}",
        # 浏览器：静止正脸图 + 说话成片；不要循环播 idle
        "idle_video_url": getattr(orch, "idle_video_url", "") or "",
        "portrait_url": getattr(orch, "portrait_url", "") or "",
        "preview_video_url": getattr(orch, "portrait_url", "")
        or getattr(orch, "idle_video_url", "")
        or "",
        "stage": "still",
        "orientation": orient,
        "fit": fit_n,
        "output_size": {"width": w, "height": h},
    }


@app.post("/api/v1/live/stop")
def live_stop(room_id: str = "demo", _: None = Depends(require_token)):
    hub.unregister(room_id)
    with get_session() as db:
        lr = db.scalar(select(LiveRoom).where(LiveRoom.room_key == room_id))
        if lr:
            lr.status = 0
            lr.ended_at = _utcnow()
            db.commit()
    return {"room_id": room_id, "status": "stopped"}


@app.get("/api/v1/live/{room_id}/status")
def live_status(room_id: str, _: None = Depends(require_token)):
    orch = hub.get(room_id)
    if not orch:
        return {
            "room_id": room_id,
            "running": False,
            "phase": "stopped",
            "phase_label": "未开播",
            "queue_length": 0,
            "last_reply": "",
            "last_error": "",
            "idle_video_url": "",
            "portrait_url": "",
            "last_video_url": "",
            "preview_video_url": "",
            "stage": "still",
        }
    s = orch.status()
    data = s.__dict__ | {"state": s.state.value}
    data["engines"] = getattr(orch, "engine_info", {})
    data["phase_label"] = s.phase_label
    data["idle_video_url"] = s.idle_video_url
    data["portrait_url"] = s.portrait_url
    data["last_video_url"] = s.last_video_url
    data["preview_video_url"] = s.preview_video_url
    data["stage"] = "speaking" if s.phase == "speaking" else "still"
    return data


@app.post("/api/v1/live/{room_id}/input")
def live_input(room_id: str, body: InputBody, _: None = Depends(require_token)):
    orch = hub.get(room_id)
    if not orch:
        raise HTTPException(409, "房间未开播")
    ok, msg = orch.enqueue(
        InputItem(
            text=body.text,
            user_key=body.user_key,
            priority=body.priority,
            is_gift=body.is_gift,
            action_hint=body.action_hint,
        )
    )
    if not ok:
        raise HTTPException(429 if "频繁" in msg or "满" in msg else 400, msg)
    return {"ok": True, "id": msg}


@app.get("/api/v1/live/{room_id}/events")
def live_events(room_id: str, limit: int = 50, _: None = Depends(require_token)):
    with get_session() as db:
        rows = db.scalars(
            select(LiveEvent)
            .where(LiveEvent.room_key == room_id)
            .order_by(desc(LiveEvent.id))
            .limit(min(limit, 200))
        ).all()
        return [
            {
                "id": r.id,
                "type": r.type,
                "payload": json.loads(r.payload or "{}"),
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


@app.websocket("/ws/live/{room_id}")
async def ws_live(websocket: WebSocket, room_id: str):
    await websocket.accept()
    q = hub.subscribe(room_id)
    try:
        # 初始状态
        orch = hub.get(room_id)
        if orch:
            s = orch.status()
            await websocket.send_json(
                {
                    "type": "status",
                    "phase": s.state.value,
                    "queue_length": s.queue_length,
                }
            )
        else:
            await websocket.send_json({"type": "status", "phase": "stopped", "queue_length": 0})

        import asyncio

        async def reader():
            while True:
                data = await websocket.receive_json()
                typ = data.get("type")
                if typ == "ping":
                    await websocket.send_json({"type": "pong", "ts": data.get("ts")})
                elif typ == "text":
                    orch = hub.get(room_id)
                    if not orch:
                        await websocket.send_json(
                            {"type": "error", "code": "not_live", "message": "未开播"}
                        )
                        continue
                    ok, msg = orch.enqueue(
                        InputItem(
                            text=str(data.get("content") or ""),
                            user_key=str(data.get("user_key") or "ws"),
                            priority=int(data.get("priority") or 10),
                            is_gift=bool(data.get("is_gift")),
                            action_hint=data.get("action_hint"),
                        )
                    )
                    if not ok:
                        await websocket.send_json(
                            {"type": "error", "code": "enqueue", "message": msg}
                        )
                elif typ == "action":
                    orch = hub.get(room_id)
                    if orch:
                        orch.enqueue(
                            InputItem(
                                text="（请配合做一个动作并向观众打个招呼）",
                                user_key="op",
                                priority=60,
                                action_hint=str(data.get("name") or "wave"),
                            )
                        )
                elif typ == "interrupt":
                    orch = hub.get(room_id)
                    if orch:
                        orch.interrupt()
                        await websocket.send_json({"type": "status", "phase": "idle", "interrupted": True})
                    else:
                        await websocket.send_json(
                            {"type": "error", "code": "not_live", "message": "未开播"}
                        )

        async def writer():
            while True:
                event = await q.get()
                await websocket.send_json(event)

        await asyncio.gather(reader(), writer())
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws error")
    finally:
        hub.unsubscribe(room_id, q)
