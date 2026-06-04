"""
smart_group_assistant - 智能群助手插件

自动识别群聊中的活动/会议通知，执行智能报名和每日群聊整理。
课程冲突检测基于内置课程表，日程查询和提醒由 astrbot_plugin_reminder 负责。
适配平台：aiocqhttp (OneBot V11 / Napcat)
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .core.activity import process_activity
from .core.classifier import classify_message
from .core.daily_summary import run_daily_summary
from .core.meeting import cancel_all_reminders, process_meeting
from .core.message_store import MessageStore
from .core.schedule import ConflictChecker


class SmartGroupAssistant(Star):
    """智能群助手插件主类

    功能：
    1. 自动监听群消息，分类为活动/会议/其他
    2. 活动通知：LLM兴趣匹配 → 时间冲突检测 → 报名分析 → 执行报名 → 通知主人
    3. 会议通知：提取信息 → 通知主人 → 会前提醒
    4. 每日群聊整理：定时收集消息 → LLM 生成摘要 → 发送给主人

    日程查询/提醒由 astrbot_plugin_reminder 提供。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 消息存储器
        keep_hours = int(config.get("message_keep_hours", 24))
        self.message_store = MessageStore(keep_hours=keep_hours)

        # 课程冲突检测器
        self.conflict_checker = ConflictChecker(dict(self.config))

        # 定时任务调度器
        self.scheduler: AsyncIOScheduler | None = None

        logger.info("[智能群助手] 插件实例已创建")

    async def initialize(self) -> None:
        """插件初始化：加载课程表、启动定时任务。"""
        logger.info("[智能群助手] 正在初始化...")

        # 加载课程表用于冲突检测
        self.conflict_checker.load()

        # 初始化定时任务调度器
        self.scheduler = AsyncIOScheduler()
        self._setup_daily_summary_job()
        self.scheduler.start()

        logger.info("[智能群助手] 初始化完成")

    async def terminate(self) -> None:
        """插件卸载时清理资源。"""
        logger.info("[智能群助手] 正在清理资源...")

        # 取消所有会前提醒
        cancel_all_reminders()

        # 停止定时任务
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("[智能群助手] 调度器已关闭")

        logger.info("[智能群助手] 插件已终止")

    # ══════════════════════════════════════════════════════════
    # 核心消息处理
    # ══════════════════════════════════════════════════════════

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def on_group_message(self, event: AstrMessageEvent):
        """监听所有QQ群消息，进行消息分类和处理。"""
        message_text = event.message_str.strip()
        if not message_text:
            return

        # 白名单检查
        group_id = event.get_group_id()
        whitelist = self.config.get("group_whitelist", [])
        if whitelist and group_id not in [str(w) for w in whitelist]:
            return

        # 忽略机器人自己的消息
        sender_id = event.get_sender_id()
        self_id = event.get_self_id()
        if str(sender_id) == str(self_id):
            return

        # 存储消息（用于每日整理）
        self.message_store.add_message(
            group_id=str(group_id),
            sender_name=event.get_sender_name(),
            sender_id=str(sender_id),
            content=message_text,
        )

        # 获取 LLM Provider
        provider = await self._get_provider(event)
        if not provider:
            return

        # 检查配置是否完整
        owner_qq = self.config.get("owner_qq", "")
        if not owner_qq:
            logger.debug("[智能群助手] 未配置主人QQ，跳过消息处理")
            return

        # ── 消息分类 ──
        category = await classify_message(message_text, provider)
        logger.info(f"[智能群助手] 消息分类结果: {category} | {message_text[:50]}")

        if category == "activity":
            await process_activity(
                event,
                dict(self.config),
                self.conflict_checker,
                provider,
                self.context,
            )

        elif category == "meeting":
            await process_meeting(
                event,
                dict(self.config),
                self.conflict_checker,
                provider,
                self.context,
            )

    # ══════════════════════════════════════════════════════════
    # 定时任务
    # ══════════════════════════════════════════════════════════

    def _setup_daily_summary_job(self) -> None:
        """配置每日群聊整理定时任务。"""
        if not self.scheduler:
            return

        summary_time = self.config.get("summary_time", "23:00")
        try:
            hour, minute = map(int, summary_time.split(":"))
        except (ValueError, AttributeError):
            hour, minute = 23, 0

        self.scheduler.add_job(
            self._daily_summary_task,
            CronTrigger(hour=hour, minute=minute),
            id="daily_group_summary",
            name="每日群聊整理",
            misfire_grace_time=300,
        )
        logger.info(f"[智能群助手] 每日群聊整理已设置为每天 {hour:02d}:{minute:02d}")

    async def _daily_summary_task(self) -> None:
        """每日群聊整理定时任务回调。"""
        logger.info("[智能群助手] 开始执行每日群聊整理...")

        provider = await self._get_provider_direct()
        if not provider:
            logger.warning("[智能群助手] 无法获取 LLM Provider，跳过每日整理")
            return

        await run_daily_summary(
            config=dict(self.config),
            message_store=self.message_store,
            provider=provider,
            context=self.context,
        )

    # ══════════════════════════════════════════════════════════
    # 辅助方法
    # ══════════════════════════════════════════════════════════

    async def _get_provider(self, event: AstrMessageEvent):
        """获取配置的 LLM Provider。"""
        provider_id = self.config.get("llm_provider", "")
        if provider_id:
            return self.context.get_provider_by_id(provider_id)
        return self.context.get_using_provider(umo=event.unified_msg_origin)

    async def _get_provider_direct(self):
        """直接获取 LLM Provider（无 event 上下文时使用）。"""
        provider_id = self.config.get("llm_provider", "")
        if provider_id:
            return self.context.get_provider_by_id(provider_id)
        return self.context.get_using_provider()
