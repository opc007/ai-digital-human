"""
系统音色目录：按男女声分组，供控制台选择。
音色 ID 对齐 MiniMax 系统音色（speech 系列）；本地 edge-tts 作备用。
"""

from __future__ import annotations

from typing import Any

# MiniMax 常用中文系统音色（id 为接口 voice_id）
MINIMAX_VOICES: list[dict[str, Any]] = [
    # —— 男声 ——
    {
        "id": "male-qn-qingse",
        "name": "青涩青年",
        "gender": "male",
        "provider": "minimax",
        "tags": ["青年", "清澈"],
        "desc": "年轻男生，适合带货/聊天",
    },
    {
        "id": "male-qn-jingying",
        "name": "精英青年",
        "gender": "male",
        "provider": "minimax",
        "tags": ["青年", "稳重"],
        "desc": "成熟男声，适合讲解",
    },
    {
        "id": "male-qn-badao",
        "name": "霸道青年",
        "gender": "male",
        "provider": "minimax",
        "tags": ["青年", "有力"],
        "desc": "气场偏强",
    },
    {
        "id": "male-qn-daxuesheng",
        "name": "大学生",
        "gender": "male",
        "provider": "minimax",
        "tags": ["青年", "阳光"],
        "desc": "校园感男声",
    },
    {
        "id": "presenter_male",
        "name": "男性主持人",
        "gender": "male",
        "provider": "minimax",
        "tags": ["主持", "播报"],
        "desc": "直播间主持风格",
    },
    {
        "id": "audiobook_male_1",
        "name": "有声书男声1",
        "gender": "male",
        "provider": "minimax",
        "tags": ["有声书", "沉稳"],
        "desc": "叙事感强",
    },
    {
        "id": "audiobook_male_2",
        "name": "有声书男声2",
        "gender": "male",
        "provider": "minimax",
        "tags": ["有声书"],
        "desc": "偏沉稳男声",
    },
    {
        "id": "Chinese (Mandarin)_Gentleman",
        "name": "温润男声",
        "gender": "male",
        "provider": "minimax",
        "tags": ["普通话", "温柔"],
        "desc": "温和男声",
    },
    {
        "id": "Chinese (Mandarin)_Reliable_Executive",
        "name": "可靠男声",
        "gender": "male",
        "provider": "minimax",
        "tags": ["普通话", "商务"],
        "desc": "商务可靠感",
    },
    {
        "id": "Chinese (Mandarin)_News_Anchor",
        "name": "男主播",
        "gender": "male",
        "provider": "minimax",
        "tags": ["新闻", "播报"],
        "desc": "新闻播报风",
    },
    # —— 女声 ——
    {
        "id": "female-shaonv",
        "name": "少女音",
        "gender": "female",
        "provider": "minimax",
        "tags": ["少女", "甜"],
        "desc": "年轻女声，适合活泼直播",
    },
    {
        "id": "female-yujie",
        "name": "御姐音",
        "gender": "female",
        "provider": "minimax",
        "tags": ["御姐", "成熟"],
        "desc": "成熟女声",
    },
    {
        "id": "female-chengshu",
        "name": "成熟女声",
        "gender": "female",
        "provider": "minimax",
        "tags": ["成熟", "稳"],
        "desc": "稳重女声",
    },
    {
        "id": "female-tianmei",
        "name": "甜美女声",
        "gender": "female",
        "provider": "minimax",
        "tags": ["甜", "亲和"],
        "desc": "甜美亲和",
    },
    {
        "id": "presenter_female",
        "name": "女性主持人",
        "gender": "female",
        "provider": "minimax",
        "tags": ["主持", "播报"],
        "desc": "直播主持风格",
    },
    {
        "id": "audiobook_female_1",
        "name": "有声书女声1",
        "gender": "female",
        "provider": "minimax",
        "tags": ["有声书"],
        "desc": "叙事女声",
    },
    {
        "id": "audiobook_female_2",
        "name": "有声书女声2",
        "gender": "female",
        "provider": "minimax",
        "tags": ["有声书"],
        "desc": "柔和叙事",
    },
    {
        "id": "Chinese (Mandarin)_Gentle_Senior",
        "name": "温柔女声",
        "gender": "female",
        "provider": "minimax",
        "tags": ["普通话", "温柔"],
        "desc": "温柔亲切",
    },
    {
        "id": "Chinese (Mandarin)_Warm_Bestie",
        "name": "闺蜜音",
        "gender": "female",
        "provider": "minimax",
        "tags": ["普通话", "轻松"],
        "desc": "像朋友聊天",
    },
    {
        "id": "Chinese (Mandarin)_Radiant_Girl",
        "name": "元气少女",
        "gender": "female",
        "provider": "minimax",
        "tags": ["元气", "活泼"],
        "desc": "活力女声",
    },
    {
        "id": "Chinese (Mandarin)_Sweet_Lady",
        "name": "甜美女声",
        "gender": "female",
        "provider": "minimax",
        "tags": ["甜"],
        "desc": "甜美女声",
    },
    {
        "id": "Chinese (Mandarin)_HK_Flight_Attendant",
        "name": "空姐音",
        "gender": "female",
        "provider": "minimax",
        "tags": ["空乘", "礼貌"],
        "desc": "礼貌清晰女声",
    },
]

# 本地 edge-tts 备用（runtime=local）
EDGE_VOICES: list[dict[str, Any]] = [
    {
        "id": "zh-CN-YunxiNeural",
        "name": "云希（男）",
        "gender": "male",
        "provider": "edge",
        "tags": ["本地", "男"],
        "desc": "edge-tts 男声",
    },
    {
        "id": "zh-CN-YunjianNeural",
        "name": "云健（男）",
        "gender": "male",
        "provider": "edge",
        "tags": ["本地", "男"],
        "desc": "edge-tts 男声",
    },
    {
        "id": "zh-CN-XiaoxiaoNeural",
        "name": "晓晓（女）",
        "gender": "female",
        "provider": "edge",
        "tags": ["本地", "女"],
        "desc": "edge-tts 女声（默认）",
    },
    {
        "id": "zh-CN-XiaoyiNeural",
        "name": "晓伊（女）",
        "gender": "female",
        "provider": "edge",
        "tags": ["本地", "女"],
        "desc": "edge-tts 女声",
    },
    {
        "id": "zh-CN-XiaochenNeural",
        "name": "晓辰（女）",
        "gender": "female",
        "provider": "edge",
        "tags": ["本地", "女"],
        "desc": "edge-tts 女声",
    },
]


def get_voice_catalog(provider: str = "minimax") -> dict[str, Any]:
    """返回分组后的音色目录。"""
    p = (provider or "minimax").lower()
    if p in ("local", "edge", "edge-tts"):
        voices = list(EDGE_VOICES)
        default_id = "zh-CN-XiaoxiaoNeural"
    else:
        voices = list(MINIMAX_VOICES)
        default_id = "male-qn-qingse"

    male = [v for v in voices if v.get("gender") == "male"]
    female = [v for v in voices if v.get("gender") == "female"]
    return {
        "provider": "edge" if p in ("local", "edge", "edge-tts") else "minimax",
        "default_id": default_id,
        "genders": [
            {"id": "all", "label": "全部", "count": len(voices)},
            {"id": "male", "label": "男声", "count": len(male)},
            {"id": "female", "label": "女声", "count": len(female)},
        ],
        "voices": voices,
        "groups": {
            "male": male,
            "female": female,
        },
    }


def find_voice(voice_id: str) -> dict[str, Any] | None:
    vid = (voice_id or "").strip()
    for v in MINIMAX_VOICES + EDGE_VOICES:
        if v["id"] == vid:
            return v
    return None
