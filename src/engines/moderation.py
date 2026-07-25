"""内容审核：本地敏感词 + 可扩展云审核。"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

logger = logging.getLogger("engines.moderation")

SAFE_FALLBACK = "咱们换个话题聊吧～"


class Moderator(ABC):
    @abstractmethod
    def check(self, text: str) -> bool:
        """True = 通过。"""

    def sanitize(self, text: str) -> str:
        if self.check(text):
            return text
        return SAFE_FALLBACK


class KeywordModerator(Moderator):
    def __init__(self, words: list[str] | None = None, enabled: bool = True):
        self.enabled = enabled
        self.words = [w.strip() for w in (words or []) if w and w.strip()]
        parts = [re.escape(w) for w in self.words]
        self._pattern = re.compile("|".join(parts), re.I) if parts else None

    def check(self, text: str) -> bool:
        if not self.enabled or not self._pattern:
            return True
        if self._pattern.search(text or ""):
            logger.warning("moderation block: %s", (text or "")[:40])
            return False
        return True


class PassThroughModerator(Moderator):
    def check(self, text: str) -> bool:
        return True


def create_moderator(cfg: dict) -> Moderator:
    if not cfg.get("enabled", True):
        return PassThroughModerator()
    provider = (cfg.get("provider") or "keyword").lower()
    if provider == "keyword":
        return KeywordModerator(
            words=list(cfg.get("blocked_words") or []),
            enabled=True,
        )
    return KeywordModerator(words=list(cfg.get("blocked_words") or []))
