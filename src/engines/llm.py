"""LLM：DeepSeek / OpenAI 兼容 + Mock。"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from typing import Any

from openai import AsyncOpenAI, OpenAI

logger = logging.getLogger("engines.llm")


class LLMEngine(ABC):
    @abstractmethod
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        ...

    async def achat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return self.chat(messages, **kwargs)

    def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> Iterator[str]:
        yield self.chat(messages, **kwargs)

    async def astream(self, messages: list[dict[str, str]], **kwargs: Any) -> AsyncIterator[str]:
        for chunk in self.stream(messages, **kwargs):
            yield chunk


class MockLLMEngine(LLMEngine):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user = m.get("content") or ""
                break
        text = user.strip() or "大家好"
        if len(text) > 20:
            text = text[:20]
        return f"收到啦，{text}。谢谢支持呀～"


def clean_live_reply(text: str, *, max_chars: int = 80) -> str:
    """
    清洗直播口播回复：去掉 thinking 模型草稿、英文规划、markdown 步骤，
    尽量留下可直接朗读的口语短句。
    """
    import re

    s = (text or "").strip()
    if not s:
        return ""

    # 去掉常见 thinking / 工具痕迹
    s = re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.I)
    s = re.sub(r"<thinking>[\s\S]*?</thinking>", "", s, flags=re.I)
    s = re.sub(r"```[\s\S]*?```", "", s)
    s = s.replace("**", "").replace("__", "")

    # 若含「最终回复/口播/对观众说」等标记，取其后内容
    for sep in (
        "最终回复：",
        "最终回复:",
        "口播：",
        "口播:",
        "回复：",
        "回复:",
        "对观众说：",
        "对观众说:",
        "Answer:",
        "Final:",
        "Output:",
    ):
        if sep in s:
            s = s.split(sep, 1)[-1].strip()

    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    # 丢掉明显是思考过程的行
    bad = re.compile(
        r"(?i)^(step\s*\d|#{1,3}\s|[-*]\s*\*\*|formulate|draft|reasoning|"
        r"system prompt|let me|i need|i'll|the user|分析|思考|规划|步骤\s*\d)"
    )
    kept = [ln for ln in lines if not bad.search(ln)]
    if kept:
        s = " ".join(kept)
    else:
        s = " ".join(lines)

    s = re.sub(r"\s+", " ", s).strip(" \t\r\n-•")
    # 仍像英文草稿 / 编号大纲则视为无效
    if re.search(r"(?i)formulate response|draft \d|^\d+\.\s+\*\*", s):
        return ""
    # 中文占比过低且偏长英文 → 无效
    zh = len(re.findall(r"[\u4e00-\u9fff]", s))
    if len(s) > 20 and zh < max(3, len(s) // 8):
        return ""

    if max_chars > 0 and len(s) > max_chars:
        # 尽量在句号处截断
        cut = s[:max_chars]
        for mark in ("。", "！", "？", "~", "～", "!", "?"):
            i = cut.rfind(mark)
            if i >= 12:
                cut = cut[: i + 1]
                break
        s = cut
    return s


def _ollama_root(base_url: str) -> str:
    root = (base_url or "").rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root or "http://127.0.0.1:11434"


def list_ollama_models(base_url: str | None = None) -> list[str]:
    """列出本机 Ollama 已安装模型名，失败返回空列表。"""
    try:
        import httpx

        base = base_url or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
        root = _ollama_root(base)
        r = httpx.get(f"{root}/api/tags", timeout=2.0)
        if r.status_code != 200:
            return []
        models = r.json().get("models") or []
        names: list[str] = []
        for m in models:
            name = (m or {}).get("name") or (m or {}).get("model")
            if name:
                names.append(str(name))
        return names
    except Exception as e:
        logger.debug("list_ollama_models failed: %s", e)
        return []


def resolve_ollama_model(preferred: str, base_url: str | None = None) -> str | None:
    """
    解析可用 Ollama 模型：优先 preferred，否则选本机已装中较轻量的一个。
    都没有则返回 None。
    """
    names = list_ollama_models(base_url)
    if not names:
        return preferred or None
    if preferred and preferred in names:
        return preferred
    # 允许短名匹配，如 qwen2.5:7b vs xxx/qwen2.5:7b
    if preferred:
        for n in names:
            if n == preferred or n.endswith("/" + preferred) or preferred in n:
                return n

    def _rank(name: str) -> tuple:
        # 优先小参数量，直播互动延迟更友好
        lower = name.lower()
        score = 100
        for tag, s in (
            (":1b", 1),
            (":1.5b", 2),
            (":2b", 3),
            (":3b", 4),
            (":4b", 5),
            (":e4b", 6),
            (":7b", 7),
            (":8b", 8),
            (":9b", 9),
            (":13b", 13),
            (":14b", 14),
            (":27b", 27),
            (":32b", 32),
            (":35b", 35),
            (":70b", 70),
        ):
            if tag in lower:
                score = s
                break
        return (score, len(name), name)

    pick = sorted(names, key=_rank)[0]
    logger.warning(
        "Ollama 未找到模型 %s，改用已安装: %s",
        preferred or "(空)",
        pick,
    )
    return pick


class OpenAICompatLLM(LLMEngine):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 120,
        *,
        allow_empty_key: bool = False,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        if not self.api_key and not allow_empty_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY / OPENAI_API_KEY")
        if not self.api_key:
            self.api_key = "ollama"
        # 超时保护：一次调用最坏情况不无限卡住直播工作线程
        timeout = float(os.getenv("LLM_TIMEOUT_SEC") or 60)
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=timeout)
        self._async = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=timeout)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        resp = self._client.chat.completions.create(
            model=kwargs.get("model") or self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        msg = resp.choices[0].message
        content = (msg.content or "").strip()
        # 部分 thinking 模型 content 为空，尝试其它字段
        if not content:
            raw = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
            if isinstance(raw, str) and raw.strip():
                # 取最后一两句当口头回复，避免整段思考刷屏
                lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
                content = (lines[-1] if lines else raw.strip())[:120]
        logger.info("LLM chat tokens~ reply_len=%s", len(content))
        return content

    def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=kwargs.get("model") or self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            stream=True,
        )
        for event in stream:
            delta = event.choices[0].delta.content if event.choices else None
            if delta:
                yield delta

    async def achat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        resp = await self._async.chat.completions.create(
            model=kwargs.get("model") or self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        return (resp.choices[0].message.content or "").strip()

    async def astream(self, messages: list[dict[str, str]], **kwargs: Any) -> AsyncIterator[str]:
        stream = await self._async.chat.completions.create(
            model=kwargs.get("model") or self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            stream=True,
        )
        async for event in stream:
            delta = event.choices[0].delta.content if event.choices else None
            if delta:
                yield delta


def create_llm_engine(cfg: dict, mock: bool = False) -> LLMEngine:
    if mock or (cfg.get("provider") or "").lower() == "mock":
        return MockLLMEngine()
    provider = (cfg.get("provider") or "deepseek").lower()

    if provider == "ollama":
        # 本机 Ollama OpenAI 兼容接口；模型名自动对齐本机已安装列表
        base = str(cfg.get("base_url") or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1")
        preferred = str(cfg.get("model") or os.getenv("OLLAMA_MODEL") or "qwen2.5:7b")
        model = resolve_ollama_model(preferred, base)
        if not model:
            logger.warning("Ollama 无可用模型（服务未启动或未 pull），回落 MockLLM")
            return MockLLMEngine()
        try:
            return OpenAICompatLLM(
                api_key=os.getenv("OLLAMA_API_KEY") or "ollama",
                base_url=base,
                model=model,
                temperature=float(cfg.get("temperature") or 0.7),
                max_tokens=int(cfg.get("max_tokens") or 120),
                allow_empty_key=True,
            )
        except Exception as e:
            logger.warning("Ollama 不可用 (%s)，回落 MockLLM", e)
            return MockLLMEngine()

    if provider in ("deepseek", "openai", "qwen", "openai_compat"):
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("无 LLM API Key，回落 MockLLM")
            return MockLLMEngine()
        return OpenAICompatLLM(
            api_key=api_key,
            base_url=str(cfg.get("base_url") or "https://api.deepseek.com/v1"),
            model=str(cfg.get("model") or "deepseek-chat"),
            temperature=float(cfg.get("temperature") or 0.7),
            max_tokens=int(cfg.get("max_tokens") or 120),
        )
    raise ValueError(f"未知 LLM provider: {provider}")
