"""最小示例的运行入口。

    python -m examples.basic.run

演示"应用补丁 → 看到效果 → 回滚恢复"的完整流程。
"""

from __future__ import annotations

from funcpatch import AuditReport, Registry, SelectionConfig

from .patch import patch


def main() -> None:
    from . import demo_module

    print("补丁前:", demo_module.build_headers("alice"))

    registry = Registry(
        SelectionConfig(default_owner="client_a", target_owners={}, enabled=True), [patch]
    )
    report = AuditReport()
    if not registry.apply(patch.target, report):
        print("补丁未生效，拒绝原因:", [r["reason"] for r in report.rejections])
        return
    print("补丁后:", demo_module.build_headers("alice"))

    registry.revert_all()
    print("回滚后:", demo_module.build_headers("alice"))


if __name__ == "__main__":
    main()
