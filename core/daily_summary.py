"""每日群聊整理模块：收集消息 → 调用LLM生成摘要 → 发送给主人。"""

from __future__ import annotations

from datetime import datetime

from astrbot.api import logger

from .message_store import MessageStore
from .utils import notify_owner, poke_user


SUMMARY_PROMPT = """你是一个群聊总结助手。请根据以下QQ群聊天记录，生成一份简洁的群聊整理报告。

请按以下格式输出：

📊 **今日热点话题**
- 列出当日群内讨论最多的1-3个话题，每个用一两句话概括

📢 **重要通知摘要**
- 提取群内发布的重要通知/公告，每个用一句话概括
- 如果没有重要通知，注明"今日无重要通知"

📋 **待办事项**
- 提取聊天中提到的待办事项/需要跟进的事项
- 如果没有，注明"今日无待办事项"

要求：简洁、客观，总字数不超过500字。"""


async def run_daily_summary(
    config: dict,
    message_store: MessageStore,
    provider,
    context,
) -> None:
    """执行每日群聊整理。

    对每个监听的群分别收集消息、调用LLM生成摘要，最后汇总发送给主人。
    """
    whitelist = config.get("group_whitelist", [])
    owner_qq = config.get("owner_qq", "")

    if not owner_qq:
        logger.warning("[智能群助手] 未配置主人QQ，跳过每日整理")
        return

    # 确定要整理的群列表
    monitored_groups = whitelist if whitelist else message_store.get_all_groups()

    if not monitored_groups:
        logger.info("[智能群助手] 没有需要整理的群消息")
        await notify_owner(context, config, "📊 今日无群聊消息可整理。")
        return

    logger.info(f"[智能群助手] 开始每日群聊整理，涉及 {len(monitored_groups)} 个群")

    all_summaries: list[str] = []

    for group_id in monitored_groups:
        try:
            messages_text = message_store.format_messages(group_id, hours=24)

            if not messages_text or len(messages_text) < 50:
                logger.info(f"[智能群助手] 群 {group_id} 消息太少，跳过整理")
                continue

            summary = await _summarize_messages(messages_text, provider, group_id)
            if summary:
                all_summaries.append(summary)

        except Exception as e:
            logger.error(f"[智能群助手] 整理群 {group_id} 消息失败: {e}")

    if not all_summaries:
        logger.info("[智能群助手] 所有群均无足够消息可整理")
        return

    # 构建最终报告
    today = datetime.now().strftime("%Y年%m月%d日")
    final_report = f"📊 【{today} 群聊整理报告】\n" + "\n\n".join(all_summaries)

    if owner_qq:
        await poke_user(context, owner_qq)
        await notify_owner(context, config, final_report)

    logger.info("[智能群助手] 每日群聊整理完成")


async def _summarize_messages(
    messages_text: str,
    provider,
    group_id: str,
) -> str:
    """对单个群的聊天记录调用LLM生成摘要。"""
    try:
        max_chars = 8000
        if len(messages_text) > max_chars:
            messages_text = (
                messages_text[:max_chars] + "\n\n...(消息过多，已截断)..."
            )

        prompt = (
            f"{SUMMARY_PROMPT}\n\n"
            f"群号: {group_id}\n"
            f"以下是该群最近24小时的聊天记录：\n\n"
            f"{messages_text}\n\n"
            f"请生成整理报告："
        )

        response = await provider.text_chat(prompt=prompt)
        result = response.completion_text.strip()

        return f"### 群 {group_id}\n{result}"

    except Exception as e:
        logger.error(f"[智能群助手] LLM摘要生成失败 (群{group_id}): {e}")
        return ""
