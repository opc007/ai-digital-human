"""产品知识库：目录里的 .md/.txt 即问答依据，无需向量数据库。

用法：
    kb = KnowledgeBase(Path("knowledge"))
    chunks = kb.search("你们平台怎么收费")
    prompt_ctx = kb.format_context(chunks)

检索是纯本地关键词（中文 bigram）打分，零依赖、通用可替换。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("engines.knowledge")

CHUNK_MAX_CHARS = 500


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text.lower())
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _split_chunks(text: str, source: str) -> list["KBChunk"]:
    """按空行/标题切段，超长段再硬切。"""
    parts = re.split(r"\n\s*\n", text.strip())
    chunks: list[KBChunk] = []
    heading = ""
    for p in parts:
        p = p.strip()
        if not p or p.startswith(("<!--", "---")):
            continue
        m = re.match(r"^#{1,6}\s*(.+)$", p)
        if m and len(p) < 80:
            heading = m.group(1).strip()
            continue
        if re.fullmatch(r"[\s|\-:]+", p):
            continue
        while len(p) > CHUNK_MAX_CHARS:
            cut = p.rfind("\u3002", 0, CHUNK_MAX_CHARS)
            cut = cut + 1 if cut > 100 else CHUNK_MAX_CHARS
            chunks.append(KBChunk(source=source, heading=heading, text=p[:cut].strip()))
            p = p[cut:].strip()
        if p:
            chunks.append(KBChunk(source=source, heading=heading, text=p))
    return chunks


@dataclass
class KBChunk:
    source: str
    heading: str
    text: str
    _bigrams: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        self._bigrams = _bigrams(self.text)


class KnowledgeBase:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.chunks: list[KBChunk] = []
        self.files: list[str] = []
        self.load()

    def load(self) -> None:
        self.chunks = []
        self.files = []
        if not self.root.is_dir():
            logger.warning("知识库目录不存在: %s", self.root)
            return
        for fp in sorted(self.root.rglob("*")):
            if not fp.is_file() or fp.suffix.lower() not in (".md", ".txt"):
                continue
            # promo_script.md 是宣讲稿，不进问答检索
            if fp.name == "promo_script.md":
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("知识库文件读取失败 %s: %s", fp, e)
                continue
            rel = fp.relative_to(self.root).as_posix()
            self.files.append(rel)
            self.chunks.extend(_split_chunks(text, rel))
        logger.info("知识库加载: %d 文件, %d 片段", len(self.files), len(self.chunks))

    def search(self, query: str, top_k: int = 3, min_score: float = 0.12) -> list[KBChunk]:
        q = query.strip()
        if not q or not self.chunks:
            return []
        qb = _bigrams(q)
        if not qb:
            return []
        scored: list[tuple[float, KBChunk]] = []
        for c in self.chunks:
            hit = len(qb & c._bigrams)
            score = hit / max(1, len(qb))
            if c.heading and _bigrams(c.heading) & qb:
                score += 0.15
            if score >= min_score:
                scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:max(1, top_k)]]

    def format_context(self, chunks: list[KBChunk]) -> str:
        if not chunks:
            return ""
        lines = ["\u3010\u4ea7\u54c1\u77e5\u8bc6\u5e93\uff08\u4ec5\u4f9d\u636e\u4ee5\u4e0b\u5185\u5bb9\u56de\u7b54\uff0c\u4e0d\u8981\u7f16\u9020\uff09\u3011"]
        for i, c in enumerate(chunks, 1):
            tag = f"\uff08{c.heading}\uff09" if c.heading else ""
            lines.append(f"{i}. {tag}{c.text}")
        return "\n".join(lines)

    def promo_lines(self, script_file: str = "promo_script.md") -> list[str]:
        """宣讲稿：每行一条，# 开头与空行跳过。支持绝对路径或相对知识库目录。"""
        fp = Path(script_file)
        if not fp.is_absolute():
            fp = self.root / fp
        if not fp.is_file():
            return []
        lines: list[str] = []
        for raw in fp.read_text(encoding="utf-8").splitlines():
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            s = re.sub(r"^[-*]\s+", "", s)
            if s:
                lines.append(s)
        return lines
