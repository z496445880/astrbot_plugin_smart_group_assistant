"""消息分类模块：使用 LLM 将群消息分类为活动通知/会议通知/其他。"""

from __future__ import annotations

import json
import re
from typing import Optional

from astrbot.api import logger


CLASSIFY_PROMPT = """你是一个消息分类助手。请判断以下QQ群消息属于哪种类型。

类型定义：
- "meeting": 会议通知。只要消息涉及"开会"、"会议"、或者跟"班"有关的通知（班会、班级活动通知等），都属于会议。
- "activity": 活动通知。非班级性质的公开活动，如：音乐节、演唱会、志愿活动、比赛、讲座、社团招新、聚会等需要报名或参加的活动。
- "other": 其他消息。如：闲聊、问问题、表情包、图片、无实质内容的通知等。

请只回复一个词：meeting、activity 或 other。不要包含任何其他内容。"""


async def classify_message(message_text: str, provider) -> str:
    """调用 LLM 将消息分类。

    Returns:
        "activity" / "meeting" / "other"
    """
    if not message_text or len(message_text.strip()) < 10:
        return "other"

    # 快速预判：含"班"的消息很可能是班级会议/通知
    if "班" in message_text:
        logger.info("[智能群助手] 消息含'班'，预判为会议/班级通知")

    try:
        prompt = f"{CLASSIFY_PROMPT}\n\n消息内容：\n{message_text}"
        response = await provider.text_chat(prompt=prompt)
        result = response.completion_text.strip().lower()

        if "meeting" in result:
            return "meeting"
        elif "activity" in result:
            return "activity"
        else:
            return "other"

    except Exception as e:
        logger.error(f"[智能群助手] 消息分类失败: {e}")
        # 含"班"时即使LLM出错也按会议处理
        return "meeting" if "班" in message_text else "other"


# ── 活动信息提取 ──────────────────────────────────────────

EXTRACT_ACTIVITY_PROMPT = """你是一个活动信息提取助手。请从以下活动通知文本中提取关键信息，以JSON格式返回。

需要提取的字段：
1. activity_name: 活动名称（简洁描述）
2. activity_time: 活动时间（原文中的时间描述，如"12月25日14:00"，若无则填"未知"）
3. activity_location: 活动地点（若无则填"未知"）
4. organizer_qq: 发布者/组织者的QQ号（纯数字字符串，若无则填""）
5. group_id: 如果需要加群报名，提取群号（纯数字字符串，若无则填""）

请严格按以下JSON格式返回，不要包含其他内容：
{
    "activity_name": "",
    "activity_time": "",
    "activity_location": "",
    "organizer_qq": "",
    "group_id": ""
}"""


async def extract_activity_info(message_text: str, provider) -> Optional[dict]:
    """从活动通知文本中提取结构化的活动信息。"""
    try:
        prompt = f"{EXTRACT_ACTIVITY_PROMPT}\n\n活动通知文本：\n{message_text}"
        response = await provider.text_chat(prompt=prompt)
        result_text = response.completion_text.strip()

        json_match = re.search(r"\{[^{}]*\}", result_text, re.DOTALL)
        if json_match:
            result_text = json_match.group()

        info = json.loads(result_text)
        logger.info(f"[智能群助手] 提取活动信息: {info.get('activity_name')}")
        return info

    except Exception as e:
        logger.error(f"[智能群助手] 提取活动信息失败: {e}")
        return None


# ── 报名方式分析 ──────────────────────────────────────────

ANALYZE_REGISTRATION_PROMPT = """你是一个报名方式识别助手。请仔细阅读以下活动通知的完整文本，分析其中包含的报名方式。

你需要识别并提取以下信息（以JSON格式返回）：

1. has_registration: 是否包含报名方式 (true/false)
2. method_type: 报名方式类型，可选值：
   - "private_message": 私聊发布者报名
   - "join_group": 加群报名
   - "send_info": 发送个人信息（姓名+学号等）给某人
   - "scan_qr": 扫描二维码
   - "fill_form": 填写在线表单
   - "other": 其他方式
   - "none": 未找到报名方式
3. method_detail: 报名方式的具体描述（原文中的原话，保留关键信息）
4. target_qq: 接收报名信息的QQ号（如果有，提取纯数字，否则填""）
5. target_group_id: 需要加入的群号（如果有，提取纯数字，否则填""）
6. required_info: 报名需要提供的信息（如"姓名+学号"、"姓名+学号+活动名称"等，原文保留）
7. action_suggestion: 建议机器人执行的操作描述（如"向发布者发送包含姓名学号的私聊"、"申请加群123456"等）

请严格按以下JSON格式返回：
{
    "has_registration": false,
    "method_type": "none",
    "method_detail": "",
    "target_qq": "",
    "target_group_id": "",
    "required_info": "",
    "action_suggestion": ""
}"""


async def analyze_registration(message_text: str, provider) -> Optional[dict]:
    """让 LLM 分析活动通知中的报名方式。

    Returns:
        报名方式分析结果字典，失败返回 None。
    """
    try:
        prompt = f"{ANALYZE_REGISTRATION_PROMPT}\n\n活动通知原文：\n{message_text}"
        response = await provider.text_chat(prompt=prompt)
        result_text = response.completion_text.strip()

        json_match = re.search(r"\{[^{}]*\}", result_text, re.DOTALL)
        if json_match:
            result_text = json_match.group()

        info = json.loads(result_text)
        logger.info(f"[智能群助手] 报名方式分析: type={info.get('method_type')}, target_qq={info.get('target_qq')}")
        return info

    except Exception as e:
        logger.error(f"[智能群助手] 报名方式分析失败: {e}")
        return None


# ── 兴趣匹配 ──────────────────────────────────────────────

INTEREST_MATCH_PROMPT = """你是一个活动兴趣匹配助手。请判断以下活动是否匹配用户的兴趣。

用户的兴趣关键词：
{interests}

用户精确匹配短语：
{exact_interests}

活动通知内容：
{message}

请判断这个活动是否匹配用户的兴趣。如果活动内容与任一兴趣关键词相关，或包含任一精确匹配短语，则判定为匹配。
请只回复 "yes" 或 "no"。不要包含其他内容。"""


async def match_interests_by_llm(
    message_text: str,
    interest_keywords: list,
    exact_keywords: list,
    provider,
) -> bool:
    """使用 LLM 判断活动是否匹配用户兴趣。

    Args:
        message_text: 活动通知文本
        interest_keywords: 模糊匹配关键词列表
        exact_keywords: 精确匹配关键词列表
        provider: LLM Provider

    Returns:
        是否匹配。
    """
    # 如果两个列表都为空，默认匹配所有
    if not interest_keywords and not exact_keywords:
        return True

    # 快速预检：如果关键词已在文本中直接出现，立即匹配
    for kw in interest_keywords:
        if isinstance(kw, str) and kw.strip() and kw.strip() in message_text:
            logger.info(f"[智能群助手] 关键词快速匹配: {kw.strip()}")
            return True
    for kw in exact_keywords:
        if isinstance(kw, str) and kw.strip() and kw.strip() in message_text:
            logger.info(f"[智能群助手] 精确短语快速匹配: {kw.strip()}")
            return True

    # 快速预检未命中时，交给 LLM 做语义匹配
    try:
        interests_str = "、".join(k.strip() for k in interest_keywords if isinstance(k, str) and k.strip())
        exact_str = "、".join(k.strip() for k in exact_keywords if isinstance(k, str) and k.strip())

        if not interests_str and not exact_str:
            return True

        prompt = INTEREST_MATCH_PROMPT.format(
            interests=interests_str or "无",
            exact_interests=exact_str or "无",
            message=message_text,
        )
        response = await provider.text_chat(prompt=prompt)
        result = response.completion_text.strip().lower()
        matched = "yes" in result
        logger.info(f"[智能群助手] LLM兴趣匹配结果: {matched}")
        return matched

    except Exception as e:
        logger.error(f"[智能群助手] LLM兴趣匹配失败: {e}")
        # LLM 失败时保守处理：如果没有任何关键词配置则匹配，否则不匹配
        return not interest_keywords and not exact_keywords


# ── 会议信息提取 ──────────────────────────────────────────

EXTRACT_MEETING_PROMPT = """你是一个会议信息提取助手。请从以下会议通知文本中提取关键信息，以JSON格式返回。

需要提取的字段：
1. meeting_name: 会议名称（简洁描述，如果涉及班级则注明"XX班XX会议"）
2. meeting_time: 会议时间（原文中的时间描述，如"12月25日14:00"，若无则填"未知"）
3. meeting_location: 会议地点/方式（如"腾讯会议 123-456-789"、"教学楼A101"，若无则填"未知"）
4. meeting_notes: 注意事项/议程/需要准备的内容（若无则填""）

请严格按以下JSON格式返回，不要包含其他内容：
{
    "meeting_name": "",
    "meeting_time": "",
    "meeting_location": "",
    "meeting_notes": ""
}"""


async def extract_meeting_info(message_text: str, provider) -> Optional[dict]:
    """从会议通知文本中提取结构化的会议信息。"""
    try:
        prompt = f"{EXTRACT_MEETING_PROMPT}\n\n会议通知文本：\n{message_text}"
        response = await provider.text_chat(prompt=prompt)
        result_text = response.completion_text.strip()

        json_match = re.search(r"\{[^{}]*\}", result_text, re.DOTALL)
        if json_match:
            result_text = json_match.group()

        info = json.loads(result_text)
        logger.info(f"[智能群助手] 提取会议信息: {info.get('meeting_name')}")
        return info

    except Exception as e:
        logger.error(f"[智能群助手] 提取会议信息失败: {e}")
        return None
