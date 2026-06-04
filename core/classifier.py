"""消息分类模块：使用 LLM 将群消息分类为活动通知/会议通知/其他。"""

from __future__ import annotations

import json
import re
from typing import Optional

from astrbot.api import logger


CLASSIFY_PROMPT = """你是一个消息分类助手。请判断以下QQ群消息属于哪种类型。

类型定义：
- "activity": 活动通知。如：音乐节、演唱会、志愿活动、比赛、讲座、聚会等需要报名或参加的活动。
- "meeting": 会议通知。如：班会、部门会议、项目讨论、例会等正式或非正式会议。
- "other": 其他消息。如：闲聊、问问题、表情包、图片、无实质内容的通知等。

请只回复一个词：activity、meeting 或 other。不要包含任何其他内容。"""


async def classify_message(message_text: str, provider) -> str:
    """调用 LLM 将消息分类。

    Returns:
        "activity" / "meeting" / "other"
    """
    if not message_text or len(message_text.strip()) < 10:
        return "other"

    try:
        prompt = f"{CLASSIFY_PROMPT}\n\n消息内容：\n{message_text}"
        response = await provider.text_chat(prompt=prompt)
        result = response.completion_text.strip().lower()

        if "activity" in result:
            return "activity"
        elif "meeting" in result:
            return "meeting"
        else:
            return "other"

    except Exception as e:
        logger.error(f"[智能群助手] 消息分类失败: {e}")
        return "other"


EXTRACT_ACTIVITY_PROMPT = """你是一个活动信息提取助手。请从以下活动通知文本中提取关键信息，以JSON格式返回。

需要提取的字段：
1. activity_name: 活动名称（简洁描述）
2. activity_time: 活动时间（原文中的时间描述，如"12月25日14:00"，若无则填"未知"）
3. activity_location: 活动地点（若无则填"未知"）
4. organizer_qq: 发布者/组织者的QQ号（纯数字字符串，若无则填""）
5. registration_method: 报名方式描述（如"私聊发布者"、"加群123456"、"扫描二维码"等，原文原样保留）
6. group_id: 如果需要加群报名，提取群号（纯数字字符串，若无则填""）

请严格按以下JSON格式返回，不要包含其他内容：
{
    "activity_name": "",
    "activity_time": "",
    "activity_location": "",
    "organizer_qq": "",
    "registration_method": "",
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


EXTRACT_MEETING_PROMPT = """你是一个会议信息提取助手。请从以下会议通知文本中提取关键信息，以JSON格式返回。

需要提取的字段：
1. meeting_name: 会议名称（简洁描述）
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
