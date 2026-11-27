"""审计日志：拒绝原因的打印。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from funcpatch import (  # noqa: E402
    AuditReport,
    Registry,
    SelectionConfig,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_audit_logs_rejection(caplog):
    import logging

    report = AuditReport()
    report.rejections.append({"owner": "a", "target": "t", "reason": "boom", "at": ""})
    with caplog.at_level(logging.ERROR):
        n = report.log()
    assert n == 1
    assert any("boom" in rec.message for rec in caplog.records)
