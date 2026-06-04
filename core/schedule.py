"""日程管理模块：加载课程表、添加会议、时间冲突检测、日程查询。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from astrbot.api import logger
from astrbot.api.star import StarTools

from .utils import load_schedule as load_courses_from_config


class ScheduleManager:
    """管理课程 + 会议的完整日程。

    课程从配置文件/.ics加载；会议动态添加，持久化到本地JSON。
    """

    def __init__(self, config: dict, plugin_data_dir: Optional[Path] = None):
        self.config = config
        self.courses: list[dict] = []
        self.meetings: list[dict] = []
        self._data_dir = plugin_data_dir
        self._meetings_file: Optional[Path] = None

    async def initialize(self) -> None:
        """加载课程和已保存的会议。"""
        self.courses = load_courses_from_config(self.config)
        logger.info(f"[智能群助手] 已加载 {len(self.courses)} 门课程")

        if not self._data_dir:
            try:
                self._data_dir = StarTools.get_data_dir("smart_group_assistant")
            except Exception:
                self._data_dir = Path("data/plugin_data/smart_group_assistant")

        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._meetings_file = self._data_dir / "meetings.json"
        self._load_meetings()

    def _load_meetings(self) -> None:
        """从本地JSON加载会议列表，并清理已过期的会议。"""
        if not self._meetings_file or not self._meetings_file.exists():
            return
        try:
            with open(self._meetings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = datetime.now()
            valid = []
            for m in data:
                try:
                    dt = datetime.fromisoformat(m.get("datetime", ""))
                    if dt > now:
                        valid.append(m)
                except (ValueError, TypeError):
                    continue
            self.meetings = valid
            logger.info(f"[智能群助手] 已恢复 {len(self.meetings)} 个会议日程")
        except Exception as e:
            logger.error(f"[智能群助手] 加载会议数据失败: {e}")

    def _save_meetings(self) -> None:
        """保存会议列表到本地JSON。"""
        if not self._meetings_file:
            return
        try:
            with open(self._meetings_file, "w", encoding="utf-8") as f:
                json.dump(self.meetings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[智能群助手] 保存会议数据失败: {e}")

    def add_meeting(self, meeting_info: dict) -> bool:
        """添加一个会议到日程。

        Args:
            meeting_info: 包含 name/datetime/location/notes 的字典。
                          datetime 为 ISO格式字符串 "YYYY-MM-DDTHH:MM:SS"

        Returns:
            是否成功添加。
        """
        required = ["name", "datetime"]
        for key in required:
            if key not in meeting_info:
                logger.warning(f"[智能群助手] 会议信息缺少必要字段: {key}")
                return False

        meeting_info.setdefault("location", "")
        meeting_info.setdefault("notes", "")
        meeting_info.setdefault("added_at", datetime.now().isoformat())

        # 检查重复
        for m in self.meetings:
            if (
                m.get("name") == meeting_info["name"]
                and m.get("datetime") == meeting_info["datetime"]
            ):
                logger.info(f"[智能群助手] 会议已存在，跳过: {meeting_info['name']}")
                return False

        self.meetings.append(meeting_info)
        self._save_meetings()
        logger.info(f"[智能群助手] 已添加会议: {meeting_info['name']}")
        return True

    def check_conflict(self, dt: datetime) -> tuple[bool, Optional[dict]]:
        """检查指定时间是否与课程或会议冲突。

        Args:
            dt: 要检查的 datetime 对象

        Returns:
            (是否冲突, 冲突的课程或会议信息)
        """
        weekday = dt.weekday() + 1
        time_str = dt.strftime("%H:%M")

        for course in self.courses:
            if course.get("day") == weekday:
                if course.get("start_time", "") <= time_str < course.get("end_time", ""):
                    return True, course

        for meeting in self.meetings:
            try:
                m_dt = datetime.fromisoformat(meeting.get("datetime", ""))
                m_end = m_dt + timedelta(hours=1)
                if m_dt <= dt < m_end:
                    return True, meeting
            except (ValueError, TypeError):
                continue

        return False, None

    def check_conflict_with_range(
        self, dt: datetime, duration_minutes: int = 60
    ) -> tuple[bool, Optional[dict]]:
        """检查时间段是否与任何课程或会议冲突。

        Args:
            dt: 开始时间
            duration_minutes: 时长（分钟）

        Returns:
            (是否冲突, 冲突项)
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

        for meeting in self.meetings:
            try:
                m_start = datetime.fromisoformat(meeting.get("datetime", ""))
                m_end = m_start + timedelta(hours=1)
                if max(dt, m_start) < min(end_dt, m_end):
                    return True, meeting
            except (ValueError, TypeError):
                continue

        return False, None

    def get_day_schedule(self, date: Optional[datetime] = None) -> list[dict]:
        """获取某一天的完整日程（课程+会议）。"""
        if date is None:
            date = datetime.now()

        weekday = date.weekday() + 1
        items: list[dict] = []

        for course in self.courses:
            if course.get("day") == weekday:
                items.append({
                    "type": "course",
                    "name": course["name"],
                    "time": course.get("start_time", ""),
                    "end_time": course.get("end_time", ""),
                    "date": date.strftime("%Y-%m-%d"),
                })

        for meeting in self.meetings:
            try:
                m_dt = datetime.fromisoformat(meeting.get("datetime", ""))
                if m_dt.date() == date.date():
                    items.append({
                        "type": "meeting",
                        "name": meeting["name"],
                        "time": m_dt.strftime("%H:%M"),
                        "datetime": m_dt.isoformat(),
                        "location": meeting.get("location", ""),
                        "notes": meeting.get("notes", ""),
                        "date": date.strftime("%Y-%m-%d"),
                    })
            except (ValueError, TypeError):
                continue

        items.sort(key=lambda x: x.get("time", "99:99"))
        return items

    def get_upcoming_meetings(self, minutes_ahead: int) -> list[dict]:
        """获取未来N分钟内即将开始的会议。"""
        now = datetime.now()
        window_end = now + timedelta(minutes=minutes_ahead)
        upcoming = []

        for meeting in self.meetings:
            try:
                m_dt = datetime.fromisoformat(meeting.get("datetime", ""))
                if now <= m_dt <= window_end:
                    upcoming.append(meeting)
            except (ValueError, TypeError):
                continue

        return upcoming
