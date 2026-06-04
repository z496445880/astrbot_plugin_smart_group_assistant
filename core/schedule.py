"""冲突检测模块：加载课程表、检查活动/会议时间是否与课程冲突。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger

from .utils import load_schedule as load_courses_from_config


class ConflictChecker:
    """加载课程表，提供时间冲突检测。

    仅用于冲突检测，不存储会议/活动。日程管理和提醒由 astrbot_plugin_reminder 负责。
    """

    def __init__(self, config: dict):
        self.courses: list[dict] = []

    def load(self) -> None:
        """加载课程表。"""
        self.courses = load_courses_from_config(self.config)
        logger.info(f"[智能群助手] 已加载 {len(self.courses)} 门课程（用于冲突检测）")

    def check(self, dt: datetime, duration_minutes: int = 60) -> tuple[bool, Optional[dict]]:
        """检查时间段是否与任何课程冲突。

        Args:
            dt: 开始时间
            duration_minutes: 时长（分钟）

        Returns:
            (是否冲突, 冲突的课程信息)
        """
        end_dt = dt + timedelta(minutes=duration_minutes)
        weekday = dt.weekday() + 1
        start_time = dt.strftime("%H:%M")
        end_time = end_dt.strftime("%H:%M")

        for course in self.courses:
            if course.get("day") == weekday:
                c_start = course.get("start_time", "")
                c_end = course.get("end_time", "")
                if start_time < c_end and c_start < end_time:
                    return True, course

        return False, None
