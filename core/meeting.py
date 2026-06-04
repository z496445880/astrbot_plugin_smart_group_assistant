"""会议通知处理模块：提取信息 → 加入日程 → 通知主人 → 会前提醒。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger

from .classifier import extract_meeting_info
from .schedule import ScheduleManager
from .utils import extract_time_from_text, notify_owner, poke_user


# 存储已调度的提醒任务，用于清理
_reminder_tasks: dict[str, asyncio.Task] = {}


async def process_meeting(
    event,
    config: dict,
    schedule: ScheduleManager,
    provider,
    context,
) -> None:
    """处理一条会议通知消息的完整流程。

    流程：
    1. 提取会议信息
    2. 加入日程表
    3. 通知主人
    4. 设置会前提醒
    """
    message_text = event.message_str.strip()

    # ── 步骤1: 提取会议信息 ──
    meeting_info = await extract_meeting_info(message_text, provider)
    if not meeting_info:
        logger.warning("[智能群助手] 无法提取会议信息，跳过")
        return

    meeting_name = meeting_info.get("meeting_name", "未知会议")
    logger.info(f"[智能群助手] 开始处理会议: {meeting_name}")

    # 解析会议时间
    time_str = meeting_info.get("meeting_time", "")
    meeting_dt: Optional[datetime] = None

    if time_str and time_str != "未知":
        meeting_dt = extract_time_from_text(time_str)
        if not meeting_dt:
            meeting_dt = extract_time_from_text(message_text)

    if not meeting_dt:
        logger.warning(f"[智能群助手] 会议 {meeting_name} 无法解析时间: {time_str}")
        return

    location = meeting_info.get("meeting_location", "未知地点")
    notes = meeting_info.get("meeting_notes", "")

    # ── 步骤2: 加入日程表 ──
    schedule_entry = {
        "name": meeting_name,
        "datetime": meeting_dt.isoformat(),
        "location": location,
        "notes": notes,
    }
    added = schedule.add_meeting(schedule_entry)
    if not added:
        logger.info(f"[智能群助手] 会议 {meeting_name} 已在日程中，跳过添加")
        return

    # ── 步骤3: 通知主人 ──
    owner_qq = config.get("owner_qq", "")
    if owner_qq:
        await poke_user(context, owner_qq)

        formatted_time = meeting_dt.strftime("%m月%d日 %H:%M")
        summary = (
            f"📋 【会议已加入日程】\n"
            f"━━━━━━━━━━━━━━\n"
            f"📌 会议：{meeting_name}\n"
            f"🕐 时间：{formatted_time}\n"
            f"📍 地点：{location}\n"
            f"📝 备注：{notes if notes else '无'}\n"
            f"━━━━━━━━━━━━━━\n"
            f"⏰ 将在会议开始前 {config.get('reminder_minutes', 15)} 分钟提醒"
        )
        await notify_owner(context, config, summary)

    # ── 步骤4: 设置会前提醒 ──
    reminder_minutes = config.get("reminder_minutes", 15)
    reminder_dt = meeting_dt - timedelta(minutes=reminder_minutes)
    now = datetime.now()

    if reminder_dt > now:
        delay = (reminder_dt - now).total_seconds()
        task_id = f"meeting_reminder_{meeting_dt.timestamp()}"

        task = asyncio.create_task(
            _meeting_reminder(
                task_id, delay, meeting_name, meeting_dt, location, config, context
            )
        )
        _reminder_tasks[task_id] = task
        task.add_done_callback(lambda t: _reminder_tasks.pop(task_id, None))
        logger.info(
            f"[智能群助手] 已设置会议 {meeting_name} 的会前提醒，"
            f"将于 {reminder_dt.strftime('%m/%d %H:%M')} 触发"
        )
    else:
        logger.warning(
            f"[智能群助手] 提醒时间 {reminder_dt} 已过，"
            f"会议 {meeting_name} 的提醒将立即发送"
        )
        await _send_meeting_reminder(
            meeting_name, meeting_dt, location, config, context
        )


async def _meeting_reminder(
    task_id: str,
    delay: float,
    meeting_name: str,
    meeting_dt: datetime,
    location: str,
    config: dict,
    context,
) -> None:
    """会前提醒延迟任务。"""
    try:
        await asyncio.sleep(delay)
        await _send_meeting_reminder(
            meeting_name, meeting_dt, location, config, context
        )
    except asyncio.CancelledError:
        logger.info(f"[智能群助手] 会议提醒已取消: {meeting_name}")
    except Exception as e:
        logger.error(f"[智能群助手] 会议提醒任务异常: {e}")


async def _send_meeting_reminder(
    meeting_name: str,
    meeting_dt: datetime,
    location: str,
    config: dict,
    context,
) -> None:
    """发送会前提醒（戳一戳 + 消息）。"""
    owner_qq = config.get("owner_qq", "")
    if not owner_qq:
        return

    await poke_user(context, owner_qq)

    formatted_time = meeting_dt.strftime("%H:%M")
    message = (
        f"⏰ 【会前提醒】\n"
        f"会议「{meeting_name}」将在 {formatted_time} 于 {location} 开始，请注意参加。"
    )
    await notify_owner(context, config, message)
    logger.info(f"[智能群助手] 已发送会议 {meeting_name} 的会前提醒")


def cancel_all_reminders() -> None:
    """取消所有待执行的会前提醒任务。"""
    for task_id, task in list(_reminder_tasks.items()):
        if not task.done():
            task.cancel()
    _reminder_tasks.clear()
    logger.info("[智能群助手] 已取消所有会前提醒")
