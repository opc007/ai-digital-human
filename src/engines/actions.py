"""动作匹配（极简规则）。"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class MatchContext:
    text: str = ""
    priority: int = 10
    is_gift: bool = False
    phase: str = ""


def match_action(ctx: MatchContext, default: str = "nod") -> str:
    if ctx.is_gift or ctx.priority >= 50:
        return "thanks_wave"
    t = ctx.text or ""
    if re.search(r"谢谢|感谢|多谢", t):
        return "thanks_wave"
    if re.search(r"你好|大家好|欢迎|嗨|hello", t, re.I):
        return "wave"
    if ctx.phase == "thinking":
        return "thinking"
    if re.search(r"吗\？|\?|怎么|为什么|如何", t):
        return "thinking"
    return default
