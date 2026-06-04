"""会议通知处理模块：提取信息 → 通知主人 → 通过 reminder 插件设置提醒。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from astrbot.api import logger

from .classifier import extract_meeting_info
from .utils import extract_time_from_text, notify_owner, poke_user


async def process_meeting(
    event,
    config: dict,
    checker,
    provider,
    context,
) -> None:
    """处理一条会议通知消息的完整流程。

    流程：
    1. 提取会议信息
    2. 通知主人（戳一戳 + 消息）
    3. 通过 LLM Agent 调用 astrbot_plugin_reminder 的 set_reminder_or_task 创建提醒
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
    reminder_minutes = config.get("reminder_minutes", 15)
    formatted_time = meeting_dt.strftime("%Y-%m-%d %H:%M")

    # ── 步骤2: 通知主人 ──
    owner_qq = config.get("owner_qq", "")
    if owner_qq:
        await poke_user(context, owner_qq)

        summary = (
            f"📋 【检测到会议通知】\n"
            f"━━━━━━━━━━━━━━\n"
            f"📌 会议：{meeting_name}\n"
            f"🕐 时间：{meeting_dt.strftime('%m月%d日 %H:%M')}\n"
            f"📍 地点：{location}\n"
            f"📝 备注：{notes if notes else '无'}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🤖 正在自动设置提醒..."
        )
        await notify_owner(context, config, summary)

    # ── 步骤3: 通过 Agent 调用 reminder 插件创建提醒 ──
    try:
        provider_id = await context.get_current_chat_provider_id(
            event.unified_msg_origin
        )
        prompt = (
            f"请使用 set_reminder_or_task 工具，创建一个会议提醒：\n"
            f"- 提醒内容：参加「{meeting_name}」会议，地点：{location}"
            f"{'，备注：' + notes if notes else ''}\n"
            f"- 提醒时间：{formatted_time}\n"
            f"- 不是任务(is_task=no)，就是普通提醒\n"
            f"- 提醒对象：用户\n"
        )
        await context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=prompt,
            max_steps=5,
            tool_call_timeout=60,
        )
        logger.info(f"[智能群助手] 已通过 reminder 插件创建会议提醒: {meeting_name}")
    except Exception as e:
        logger.error(f"[智能群助手] 调用 reminder 插件创建提醒失败: {e}")
        # 兜底：通知主人手动设置
        await notify_owner(
            context,
            config,
            f"⚠️ 自动设置提醒失败，请手动操作：/提醒我 {formatted_time} 参加{meeting_name}",
        )
