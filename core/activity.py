"""活动通知处理模块：兴趣匹配 → 时间冲突检测 → 报名分析 → 执行报名 → 加入日程 → 通知主人。"""

from __future__ import annotations

from datetime import datetime

from astrbot.api import logger

from .classifier import extract_activity_info, analyze_registration, match_interests_by_llm
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
    1. LLM 兴趣匹配（语义级别，不再只用关键词）
    2. 提取活动信息
    3. 时间冲突检测
    4. LLM 分析报名方式并执行
    5. 加入日程表
    6. 戳一戳 + 通知主人
    """
    message_text = event.message_str.strip()

    # ── 步骤1: LLM 兴趣匹配 ──
    interest_keywords = config.get("interest_keywords", [])
    exact_keywords = config.get("exact_match_keywords", [])
    if not await match_interests_by_llm(message_text, interest_keywords, exact_keywords, provider):
        logger.info(f"[智能群助手] 活动不匹配兴趣，跳过: {message_text[:50]}")
        return

    # ── 步骤2: 提取活动基本信息 ──
    activity_info = await extract_activity_info(message_text, provider)
    if not activity_info:
        logger.warning("[智能群助手] 无法提取活动信息，跳过")
        return

    activity_name = activity_info.get("activity_name", "未知活动")
    logger.info(f"[智能群助手] 开始处理活动: {activity_name}")

    # ── 步骤3: 时间冲突检测 ──
    activity_time_str = activity_info.get("activity_time", "")
    activity_dt: datetime | None = None

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
            logger.info(f"[智能群助手] 活动 {activity_name} 时间未知，跳过冲突检测")
    else:
        logger.info(f"[智能群助手] 活动 {activity_name} 无明确时间，跳过冲突检测")

    # ── 步骤4: LLM 分析报名方式并执行 ──
    reg_analysis = await analyze_registration(message_text, provider)
    results: list[str] = []
    if reg_analysis and reg_analysis.get("has_registration", False):
        results = await execute_registration(event, activity_info, reg_analysis, config)
    else:
        results.append("未检测到报名方式，如需报名请手动处理")
        logger.info(f"[智能群助手] 活动 {activity_name} 未检测到报名方式")

    # ── 步骤5: 加入日程表 ──
    schedule_note = ""
    if activity_dt:
        schedule_entry = {
            "name": f"【活动】{activity_name}",
            "datetime": activity_dt.isoformat(),
            "location": activity_info.get("activity_location", ""),
            "notes": f"来源: 群聊自动识别。报名方式: {reg_analysis.get('method_detail', '未知') if reg_analysis else '未知'}",
        }
        if schedule.add_meeting(schedule_entry):
            schedule_note = f"\n📅 已加入日程表"
            logger.info(f"[智能群助手] 活动 {activity_name} 已加入日程")

    # ── 步骤6: 戳一戳 + 通知主人 ──
    owner_qq = config.get("owner_qq", "")
    if owner_qq:
        await poke_user(context, owner_qq)

        time_display = activity_time_str if activity_time_str else "未知时间"
        location = activity_info.get("activity_location", "未知地点")
        operations = "\n".join(f"  • {r}" for r in results) if results else "  无"

        summary = (
            f"📢 【活动通知】\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎯 活动：{activity_name}\n"
            f"🕐 时间：{time_display}\n"
            f"📍 地点：{location}\n"
            f"🔧 机器人已执行：\n{operations}"
            f"{schedule_note}\n"
            f"━━━━━━━━━━━━━━"
        )
        await notify_owner(context, config, summary)

    logger.info(f"[智能群助手] 活动 {activity_name} 处理完成")
