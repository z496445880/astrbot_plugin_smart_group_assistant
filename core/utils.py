"""工具函数模块：通知、戳一戳、时间解析、群号提取等。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger


# ── 群号提取 ──────────────────────────────────────────────


def extract_qq_group_id(text: str) -> Optional[str]:
    """从文本中提取 QQ 群号。

    支持格式：
    - 纯数字群号（6-10位）
    - "群号：123456789"、"加群 123456789"
    - QQ群链接

    Returns:
        群号字符串，未找到返回 None。
    """
    # 匹配QQ群链接中的群号
    link_patterns = [
        r"qm\.qq\.com[^\s]*[?&]group=(\d{5,15})",
        r"qun\.qq\.com[^\s]*[?&]group=(\d{5,15})",
        r"jq\.qq\.com[^\s]*[?&]_wv=\d+&_wwv=\d+&(\d{5,15})",
    ]
    for pattern in link_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)

    # 匹配"群号"、"加群"等关键词后的数字
    keyword_match = re.search(
        r"(?:群号|加群|群聊|Q[Qq]群|入群|申请加群)[：:\s]*(\d{5,15})", text
    )
    if keyword_match:
        return keyword_match.group(1)

    # 匹配独立的6-10位数字
    standalone = re.findall(r"(?<!\d)(\d{6,10})(?!\d)", text)
    if standalone:
        return standalone[0]

    return None


# ── 时间解析 ──────────────────────────────────────────────


def extract_time_from_text(text: str) -> Optional[datetime]:
    """从文本中提取活动/会议时间。

    支持常见中文时间表达：
    - "12月25日 14:00" / "12-25 14:00"
    - "明天下午3点" / "下周一上午9点"
    - "2025-01-15 14:00"
    - "X分钟后" / "X小时后"

    Returns:
        datetime 对象，无法解析返回 None。
    """
    now = datetime.now()

    # 完整日期时间: 2025-01-15 14:00 / 2025年1月15日 14:00
    full_match = re.search(
        r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?\s*(\d{1,2}):(\d{2})", text
    )
    if full_match:
        try:
            return datetime(
                int(full_match.group(1)),
                int(full_match.group(2)),
                int(full_match.group(3)),
                int(full_match.group(4)),
                int(full_match.group(5)),
            )
        except ValueError:
            pass

    # 月日+时间: 12月25日 14:00 / 12-25 14:00
    md_time = re.search(
        r"(\d{1,2})[月/-](\d{1,2})日?\s*(\d{1,2}):(\d{2})", text
    )
    if md_time:
        try:
            month, day = int(md_time.group(1)), int(md_time.group(2))
            hour, minute = int(md_time.group(3)), int(md_time.group(4))
            year = now.year
            dt = datetime(year, month, day, hour, minute)
            if dt < now:
                dt = datetime(year + 1, month, day, hour, minute)
            return dt
        except ValueError:
            pass

    # 仅时间: 14:00 / 下午3点
    time_only = re.search(r"(\d{1,2})[:：点](\d{0,2})?", text)
    if time_only:
        hour = int(time_only.group(1))
        minute = int(time_only.group(2) or "0")

        # 处理中文时段
        if "凌晨" in text or "半夜" in text:
            if hour == 12:
                hour = 0
        elif "早上" in text or "上午" in text:
            if hour == 12:
                hour = 0
        elif "中午" in text:
            if hour < 10:
                hour += 12
        elif "下午" in text:
            if hour < 12:
                hour += 12
        elif "晚上" in text:
            if hour < 12:
                hour += 12
            if hour == 12:
                hour = 0

        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # 判断相对日期
        if any(w in text for w in ["明天", "明日"]):
            dt += timedelta(days=1)
        elif any(w in text for w in ["后天"]):
            dt += timedelta(days=2)
        elif "下周" in text:
            dt += timedelta(days=7)
        elif dt <= now:
            dt += timedelta(days=1)

        return dt

    # 相对时间: X分钟后、X小时后、X天后
    relative_min = re.search(r"(\d+)\s*分钟后", text)
    if relative_min:
        return now + timedelta(minutes=int(relative_min.group(1)))

    relative_hour = re.search(r"(\d+)\s*小时后", text)
    if relative_hour:
        return now + timedelta(hours=int(relative_hour.group(1)))

    relative_day = re.search(r"(\d+)\s*天后", text)
    if relative_day:
        return now + timedelta(days=int(relative_day.group(1)))

    return None


# ── 通知与戳一戳 ──────────────────────────────────────────


async def notify_owner(
    context,
    config: dict,
    message: str,
    owner_qq: Optional[str] = None,
) -> bool:
    """向主人QQ发送通知消息。

    Args:
        context: AstrBot Context 对象
        config: 插件配置字典
        message: 通知内容（纯文本）
        owner_qq: 主人QQ号，不传则从config读取

    Returns:
        是否发送成功。
    """
    target_qq = owner_qq or config.get("owner_qq", "")
    if not target_qq:
        logger.warning("[智能群助手] 未配置主人QQ号，无法发送通知")
        return False

    try:
        from astrbot.api.event import filter as event_filter

        platform = context.get_platform(event_filter.PlatformAdapterType.AIOCQHTTP)
        if platform and hasattr(platform, "get_client"):
            client = platform.get_client()
            await client.api.call_action(
                "send_private_msg",
                user_id=int(target_qq),
                message=message,
            )
        else:
            logger.warning("[智能群助手] 无法获取 aiocqhttp 平台实例")
            return False

        logger.info(f"[智能群助手] 已向主人 {target_qq} 发送通知")
        return True

    except Exception as e:
        logger.error(f"[智能群助手] 向主人发送通知失败: {e}")
        return False


async def poke_user(context, target_qq: str) -> bool:
    """向指定QQ号发送戳一戳。

    Args:
        context: AstrBot Context 对象
        target_qq: 目标QQ号

    Returns:
        是否发送成功。
    """
    if not target_qq:
        return False

    try:
        from astrbot.api.event import filter as event_filter

        platform = context.get_platform(event_filter.PlatformAdapterType.AIOCQHTTP)
        if platform and hasattr(platform, "get_client"):
            client = platform.get_client()
            await client.friend_poke(user_id=int(target_qq))
            logger.info(f"[智能群助手] 已向 {target_qq} 发送戳一戳")
            return True
        else:
            logger.warning("[智能群助手] 无法获取 aiocqhttp 平台实例进行戳一戳")
            return False

    except Exception as e:
        logger.error(f"[智能群助手] 戳一戳 {target_qq} 失败: {e}")
        return False


# ── 课程表解析 ──────────────────────────────────────────────


def parse_json_schedule(json_str: str) -> list[dict]:
    """从JSON字符串解析课程表。

    Args:
        json_str: JSON字符串，每门课包含 name/day/start_time/end_time

    Returns:
        课程列表，格式: [{"name": ..., "day": 1-7, "start_time": "HH:MM", "end_time": "HH:MM"}, ...]
    """
    import json

    try:
        courses = json.loads(json_str)
        if not isinstance(courses, list):
            return []

        validated = []
        for c in courses:
            if not isinstance(c, dict):
                continue
            name = c.get("name", "未知课程")
            day = c.get("day", 0)
            start = c.get("start_time", "")
            end = c.get("end_time", "")
            if day and start:
                validated.append(
                    {"name": name, "day": int(day), "start_time": start, "end_time": end}
                )
        return validated

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"[智能群助手] 解析JSON课程表失败: {e}")
        return []


def parse_ics_schedule(filepath: str) -> list[dict]:
    """从 .ics 文件解析课程表。

    Args:
        filepath: .ics 文件的绝对路径

    Returns:
        课程列表，格式同 parse_json_schedule。
    """
    import os

    if not os.path.exists(filepath):
        logger.error(f"[智能群助手] .ics 文件不存在: {filepath}")
        return []

    try:
        from icalendar import Calendar

        with open(filepath, "rb") as f:
            cal = Calendar.from_ical(f.read())

        courses = []
        weekday_map = {"MO": 1, "TU": 2, "WE": 3, "TH": 4, "FR": 5, "SA": 6, "SU": 7}

        for component in cal.walk("VEVENT"):
            summary = str(component.get("summary", "未知课程"))
            dtstart = component.get("dtstart")
            dtend = component.get("dtend")

            if not dtstart:
                continue

            start_dt = dtstart.dt
            end_dt = dtend.dt if dtend else start_dt

            rrule = component.get("rrule")
            if rrule:
                byday = rrule.get("BYDAY", [])
                if isinstance(byday, (str,)):
                    byday = [byday]
                for day_code in byday:
                    day_str = str(day_code)[-2:] if len(str(day_code)) > 2 else str(day_code)
                    day_num = weekday_map.get(day_str.upper())
                    if day_num:
                        courses.append({
                            "name": summary,
                            "day": day_num,
                            "start_time": start_dt.strftime("%H:%M") if hasattr(start_dt, "strftime") else str(start_dt)[-8:-3],
                            "end_time": end_dt.strftime("%H:%M") if hasattr(end_dt, "strftime") else str(end_dt)[-8:-3],
                        })
            else:
                if hasattr(start_dt, "weekday"):
                    day_num = start_dt.weekday() + 1
                    courses.append({
                        "name": summary,
                        "day": day_num,
                        "start_time": start_dt.strftime("%H:%M"),
                        "end_time": end_dt.strftime("%H:%M") if hasattr(end_dt, "strftime") else "",
                    })

        logger.info(f"[智能群助手] 从 .ics 文件解析到 {len(courses)} 门课程")
        return courses

    except Exception as e:
        logger.error(f"[智能群助手] 解析 .ics 文件失败: {e}")
        return []


def load_schedule(config: dict) -> list[dict]:
    """根据配置加载课程表（优先 .ics 文件，其次 JSON）。"""
    ics_path = config.get("ics_file_path", "").strip()
    if ics_path:
        courses = parse_ics_schedule(ics_path)
        if courses:
            return courses

    json_str = config.get("course_schedule", "[]")
    return parse_json_schedule(json_str)
