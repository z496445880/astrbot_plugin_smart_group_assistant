"""活动通知处理模块：兴趣匹配 → 时间冲突检测 → 提取报名方式 → 执行报名 → 通知主人。"""

from __future__ import annotations

from astrbot.api import logger

from .classifier import extract_activity_info
from .registration import execute_registration
from .schedule import ScheduleManager
from .utils import extract_time_from_text, notify_owner, poke_user


async def process_activity(
    event,
    config: dict,
    schedule: ScheduleManager,
    provider,
    context,
) -> None:
    """处理一条活动通知消息的完整流程。

    流程：
    1. 兴趣匹配
    2. 提取活动信息
    3. 时间冲突检测
    4. 提取报名方式 & 执行报名操作
    5. 通知主人
    """
    message_text = event.message_str.strip()

    # ── 步骤1: 兴趣匹配 ──
    if not _match_interests(message_text, config):
        logger.info(f"[智能群助手] 活动不匹配兴趣，跳过: {message_text[:50]}")
        return

    # ── 步骤2: 提取活动信息 ──
    activity_info = await extract_activity_info(message_text, provider)
    if not activity_info:
        logger.warning("[智能群助手] 无法提取活动信息，跳过")
        return

    activity_name = activity_info.get("activity_name", "未知活动")
    logger.info(f"[智能群助手] 开始处理活动: {activity_name}")

    # ── 步骤3: 时间冲突检测 ──
    activity_time_str = activity_info.get("activity_time", "")
    if activity_time_str and activity_time_str != "未知":
        activity_dt = extract_time_from_text(activity_time_str)
        if not activity_dt:
            activity_dt = extract_time_from_text(message_text)

        if activity_dt:
            has_conflict, conflict_item = schedule.check_conflict_with_range(
                activity_dt, duration_minutes=60
            )
            if has_conflict:
                conflict_name = (
                    conflict_item.get("name", "未知")
                    if conflict_item
                    else "未知"
                )
                logger.info(
                    f"[智能群助手] 活动 {activity_name} 时间冲突({conflict_name})，跳过"
                )
                return
        else:
            logger.info(
                f"[智能群助手] 活动 {activity_name} 时间未知，跳过冲突检测"
            )
    else:
        logger.info(f"[智能群助手] 活动 {activity_name} 无明确时间，跳过冲突检测")

    # ── 步骤4: 执行报名 ──
    results = await execute_registration(event, activity_info, config)

    # ── 步骤5: 通知主人 ──
    owner_qq = config.get("owner_qq", "")
    if owner_qq:
        await poke_user(context, owner_qq)

        time_display = activity_time_str if activity_time_str else "未知时间"
        location = activity_info.get("activity_location", "未知地点")
        operations = "\n".join(f"  • {r}" for r in results)

        summary = (
            f"📢 【活动报名通知】\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎯 活动：{activity_name}\n"
            f"🕐 时间：{time_display}\n"
            f"📍 地点：{location}\n"
            f"🔧 机器人已执行：\n{operations}\n"
            f"━━━━━━━━━━━━━━"
        )
        await notify_owner(context, config, summary)

    logger.info(f"[智能群助手] 活动 {activity_name} 处理完成")


def _match_interests(message_text: str, config: dict) -> bool:
    """检查活动文本是否匹配用户兴趣。

    Args:
        message_text: 消息纯文本
        config: 插件配置

    Returns:
        是否匹配。
    """
    interest_keywords = config.get("interest_keywords", [])
    exact_keywords = config.get("exact_match_keywords", [])

    # 如果两个列表都为空，默认匹配所有
    if not interest_keywords and not exact_keywords:
        return True

    # 模糊匹配：任一关键词出现在文本中即匹配
    for keyword in interest_keywords:
        if isinstance(keyword, str) and keyword.strip():
            if keyword.strip() in message_text:
                logger.info(f"[智能群助手] 兴趣关键词匹配: {keyword.strip()}")
                return True

    # 精确匹配：完整短语匹配
    for keyword in exact_keywords:
        if isinstance(keyword, str) and keyword.strip():
            if keyword.strip() == message_text or keyword.strip() in message_text:
                logger.info(f"[智能群助手] 精确关键词匹配: {keyword.strip()}")
                return True

    return False
