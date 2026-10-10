"""产品知识库：目录里的 .md/.txt 即问答依据，无需向量数据库。

用法：
    kb = KnowledgeBase(Path("knowledge"))
    chunks = kb.search("你们平台怎么收费")
    prompt_ctx = kb.format_context(chunks)

检索是纯本地关键词（中文 bigram）打分，零依赖、通用可替换。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("engines.knowledge")

CHUNK_MAX_CHARS = 500

# 别名文件：用户可选维护，不存在也不影响任何行为
ALIASES_FILENAME = "_aliases.txt"

# 内置常见问法组：组内词互为别名。
# 解决纯字面 bigram 匹配的根本短板——观众问「多少钱」，知识库写「售价…元」，
# 字面零重叠导致零命中。零新依赖；用户可在 _aliases.txt 里追加自己的组。
DEFAULT_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("价格", "多少钱", "多钱", "贵不贵", "贵吗", "费用", "收费", "定价", "售价", "价位", "报价", "折扣", "优惠", "套餐", "客单价"),
    ("多久", "多长时间", "耗时", "速度", "多快", "出片", "生成时间"),
    ("怎么用", "使用方法", "教程", "上手", "操作", "步骤", "新手"),
    ("支持", "兼容", "适配", "能不能", "可以吗", "行不行"),
    ("区别", "对比", "相比", "差异", "哪个好", "和别的"),
    ("售后", "退款", "退货", "保修", "质保", "服务"),
    ("功能", "能做什么", "特性", "玩法", "亮点", "能力"),
    ("账号", "注册", "登录", "开通", "入驻"),
)

# 别名命中的权重：低于字面命中，避免别名把无关片段顶上来
ALIAS_WEIGHT = 0.7

# 标题命中的加分（按 IDF 加权后取该比例，避免只靠一个常见词拿满分）
HEADING_BONUS = 0.25


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
    def __init__(self, root: Path | str, *, use_aliases: bool = True):
        self.root = Path(root)
        self.chunks: list[KBChunk] = []
        self.files: list[str] = []
        self.use_aliases = use_aliases
        self.synonym_groups: list[tuple[str, ...]] = list(DEFAULT_SYNONYM_GROUPS)
        self._alias_source = "内置"
        self.load()

    # ---------- 别名 ----------
    def _load_alias_file(self, fp: Path) -> int:
        """从 _aliases.txt 追加同义组；返回追加的组数。"""
        added = 0
        try:
            raw = fp.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("别名文件读取失败 %s: %s", fp, e)
            return 0
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            words = [w for w in re.split(r"[\s|,，、]+", s) if w]
            if len(words) < 2:
                continue
            self.synonym_groups.append(tuple(words))
            added += 1
        return added

    def _alias_bigrams(self, query: str) -> set[str]:
        """返回查询经同义组扩展出的额外 bigram（不含查询自身的）。"""
        if not self.use_aliases:
            return set()
        own = _bigrams(query)
        extra: set[str] = set()
        for group in self.synonym_groups:
            if any(w in query for w in group):
                for w in group:
                    extra |= _bigrams(w)
        return extra - own

    # ---------- 加载 ----------
    def load(self) -> None:
        self.chunks = []
        self.files = []
        self._df: dict[str, int] = {}
        self._idf_cache: dict[str, float] = {}
        self.synonym_groups = list(DEFAULT_SYNONYM_GROUPS)
        self._alias_source = "内置"
        if not self.root.is_dir():
            logger.warning("知识库目录不存在: %s", self.root)
            return
        alias_fp = self.root / ALIASES_FILENAME
        if alias_fp.is_file():
            n = self._load_alias_file(alias_fp)
            self._alias_source = f"内置+{alias_fp.name}({n}组)"
        for fp in sorted(self.root.rglob("*")):
            if not fp.is_file() or fp.suffix.lower() not in (".md", ".txt"):
                continue
            # promo_script.md 是宣讲稿，_aliases.txt 是配置，都不进问答检索
            if fp.name in ("promo_script.md", ALIASES_FILENAME):
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("知识库文件读取失败 %s: %s", fp, e)
                continue
            rel = fp.relative_to(self.root).as_posix()
            self.files.append(rel)
            self.chunks.extend(_split_chunks(text, rel))
        self._build_idf()
        logger.info(
            "知识库加载: %d 文件, %d 片段, 同义组 %d (%s), 词表 %d",
            len(self.files), len(self.chunks), len(self.synonym_groups),
            self._alias_source, len(self._df),
        )

    def _build_idf(self) -> None:
        """统计 bigram 文档频率。

        不做 IDF 的话，「怎么」「什么」这类到处都有的词和「售价」「算力」一样重，
        于是「今天天气怎么样」会因为命中一个「怎么」就被判为相关——错误知识库内容
        喂给模型比没有知识库更糟（会答错而不是不答）。
        """
        df: dict[str, int] = {}
        for c in self.chunks:
            for b in c._bigrams:
                df[b] = df.get(b, 0) + 1
        self._df = df
        self._idf_cache = {}

    def _idf(self, bigram: str) -> float:
        v = self._idf_cache.get(bigram)
        if v is None:
            n = max(1, len(self.chunks))
            v = math.log(1.0 + n / (1.0 + self._df.get(bigram, 0)))
            self._idf_cache[bigram] = v
        return v

    def _weighted_overlap(self, qset: set[str], c: KBChunk, denom: float | None = None) -> float:
        """命中 bigram 的 IDF 加权占比：命中「罕见词」远比命中「常见词」值钱。

        denom 为 None 时用 qset 自身的 IDF 和做分母；调用方可传入**查询词**的
        IDF 和，让字面与别名两部分共用同一量纲（否则别名组一大就把分数稀释没了）。
        """
        hits = qset & c._bigrams
        if not hits:
            return 0.0
        got = sum(self._idf(b) for b in hits)
        want = denom if denom is not None else sum(self._idf(b) for b in qset)
        return got / want if want and want > 0 else 0.0

    def search(self, query: str, top_k: int = 3, min_score: float = 0.12) -> list[KBChunk]:
        q = query.strip()
        if not q or not self.chunks:
            return []
        qb = _bigrams(q)
        if not qb:
            return []
        ab = self._alias_bigrams(q)
        # 两部分统一以「查询本身」的 IDF 和为分母，避免别名集合大小稀释分数
        q_sum = sum(self._idf(b) for b in qb)
        scored: list[tuple[float, KBChunk]] = []
        for c in self.chunks:
            score = self._weighted_overlap(qb, c, q_sum)
            if ab:
                score += ALIAS_WEIGHT * self._weighted_overlap(ab, c, q_sum)
            if c.heading and (_bigrams(c.heading) & (qb | ab)):
                score += HEADING_BONUS * self._weighted_overlap(qb | ab, c, q_sum)
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
