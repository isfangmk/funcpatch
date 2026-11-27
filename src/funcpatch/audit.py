"""审计日志：冲突、版本校验、生效报告。

框架的可观测性层：每次部署能明确看到"谁在哪个目标上生效"，
误部署多个 owner 时立刻告警。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("funcpatch.audit")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AuditReport:
    """一次应用的审计报告。"""

    entries: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    # 每类条目各自的打印游标，避免每次 import 重复打印历史。
    _cursors: list[int] = field(default_factory=lambda: [0, 0, 0], repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def clear(self) -> None:
        """清空报告并重置游标。"""
        with self._lock:
            self.entries.clear()
            self.conflicts.clear()
            self.rejections.clear()
            self._cursors = [0, 0, 0]

    def new_since_last_log(self) -> int:
        """返回自上次 log() 以来新增的条目数量。"""
        with self._lock:
            sizes = (len(self.entries), len(self.conflicts), len(self.rejections))
            return sum(size - cursor for size, cursor in zip(sizes, self._cursors, strict=True))

    def to_dict(self) -> dict:
        """导出为结构化数据，便于 JSON 序列化 / 上报。"""
        with self._lock:
            return {
                "entries": [dict(e) for e in self.entries],
                "conflicts": [dict(c) for c in self.conflicts],
                "rejections": [dict(r) for r in self.rejections],
            }

    def log(self) -> int:
        """打印本次新增的条目，返回新增数量。

        游标推进受锁保护，并发调用不会重复推进；打印在锁外进行，
        不保证并发调用的输出顺序。
        """
        with self._lock:
            groups: list[list[dict]] = [self.entries, self.conflicts, self.rejections]
            cursor = list(self._cursors)
            new = sum(len(g) - c for g, c in zip(groups, cursor, strict=True))
            snapshots = [list(g[c:]) for g, c in zip(groups, cursor, strict=True)]

        for entry in snapshots[0]:
            logger.info(
                "生效补丁：owner=%s target=%s at=%s",
                entry.get("owner", ""),
                entry.get("target", ""),
                entry.get("at", ""),
            )
        for conflict in snapshots[1]:
            logger.warning(
                "补丁冲突：target=%s 生效 owner=%s，未生效 owner=%s at=%s",
                conflict.get("target", ""),
                conflict.get("chosen", ""),
                conflict.get("skipped", ""),
                conflict.get("at", ""),
            )
        for rej in snapshots[2]:
            logger.error(
                "补丁拒绝：owner=%s target=%s 原因=%s at=%s",
                rej.get("owner", ""),
                rej.get("target", ""),
                rej.get("reason", ""),
                rej.get("at", ""),
            )

        # 打印全部成功后才推进游标；用初始 cursor + 本次快照长度计算，
        # 避免并发 log 时重复推进，且任何打印异常都不会吞掉条目。
        with self._lock:
            self._cursors = [min(cursor[i] + len(snapshots[i]), len(groups[i])) for i in range(3)]
        return new
