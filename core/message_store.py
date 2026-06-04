"""消息存储模块：缓存群消息，供每日整理使用。"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Optional


class MessageStore:
    """内存中的消息缓冲区，按群组存储最近N小时的消息。

    每条消息存储为: {
        "timestamp": float,
        "sender_name": str,
        "sender_id": str,
        "content": str,
        "group_id": str,
    }
    """

    def __init__(self, keep_hours: int = 24):
        self.keep_hours = keep_hours
        self._store: dict[str, list[dict]] = defaultdict(list)

    def add_message(
        self,
        group_id: str,
        sender_name: str,
        sender_id: str,
        content: str,
    ) -> None:
        """存储一条群消息。"""
        msg = {
            "timestamp": time.time(),
            "sender_name": sender_name,
            "sender_id": sender_id,
            "content": content,
            "group_id": group_id,
        }
        self._store[group_id].append(msg)
        self._cleanup()

    def get_group_messages(
        self, group_id: str, hours: Optional[int] = None
    ) -> list[dict]:
        """获取指定群的最近N小时消息。"""
        self._cleanup()
        keep = hours if hours is not None else self.keep_hours
        cutoff = time.time() - keep * 3600
        return [m for m in self._store.get(group_id, []) if m["timestamp"] >= cutoff]

    def get_all_groups(self) -> list[str]:
        """获取所有有消息的群号列表。"""
        self._cleanup()
        return [gid for gid, msgs in self._store.items() if msgs]

    def format_messages(self, group_id: str, hours: Optional[int] = None) -> str:
        """将群消息格式化为可读文本，供LLM摘要使用。"""
        messages = self.get_group_messages(group_id, hours)
        if not messages:
            return ""

        lines = []
        current_date = ""
        for msg in messages:
            dt = datetime.fromtimestamp(msg["timestamp"])
            date_str = dt.strftime("%m月%d日")
            if date_str != current_date:
                current_date = date_str
                lines.append(f"\n--- {date_str} ---")
            time_str = dt.strftime("%H:%M")
            lines.append(
                f"[{time_str}] {msg['sender_name']}: {msg['content']}"
            )

        return "\n".join(lines)

    def _cleanup(self) -> None:
        """清理所有群的过期消息。"""
        cutoff = time.time() - self.keep_hours * 3600
        for group_id in list(self._store.keys()):
            self._store[group_id] = [
                m for m in self._store[group_id] if m["timestamp"] >= cutoff
            ]
            if not self._store[group_id]:
                del self._store[group_id]
