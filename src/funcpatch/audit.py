"""审计日志：冲突、版本校验、生效报告。

框架的可观测性层：每次部署能明确看到"谁在哪个目标上生效"，
误部署多个 owner 时立刻告警。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

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


@dataclass
class AuditReport:
    """一次应用的审计报告。"""

    entries: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)

    def log(self) -> None:
        for entry in self.entries:
            logger.info("生效补丁：owner=%s target=%s", entry["owner"], entry["target"])
        for conflict in self.conflicts:
            logger.warning(
                "补丁冲突：target=%s 生效 owner=%s，未生效 owner=%s",
                conflict["target"],
                conflict["chosen"],
                conflict["skipped"],
            )
        for rej in self.rejections:
            logger.error(
                "补丁拒绝：owner=%s target=%s 原因=%s",
                rej["owner"],
                rej["target"],
                rej["reason"],
            )
