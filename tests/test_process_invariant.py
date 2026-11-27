"""进程级单一生效：跨 Registry 实例也不能叠加补丁。

核心不变式是"一个目标一次部署只有一个 owner 生效"。此前它只在单个
Registry 内成立；两个实例可以对同一目标分别 apply，后者静默覆盖前者。
本测试用进程级占用表把这个漏洞封死。
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    AuditReport,
    ConflictError,
    PatchSpec,
    Registry,
    SelectionConfig,
    claims_snapshot,
)
from funcpatch._claims import clear_all  # noqa: E402

TARGET = "_target:build_headers"


def _spec(owner: str, tag: str) -> PatchSpec:
    def impl(*args, **kwargs):
        return {"X-Source": tag}

    return PatchSpec(owner, "_target", "build_headers", impl)


def _reg(owner: str, specs) -> Registry:
    return Registry(SelectionConfig(owner, {}, True), specs)


def test_cross_registry_second_apply_rejected():
    r1 = _reg("a", [_spec("a", "A")])
    r2 = _reg("b", [_spec("b", "B")])

    assert r1.apply(TARGET) is True
    # 第二个 Registry 必须被拒绝，不能静默覆盖
    report = AuditReport()
    assert r2.apply(TARGET, report) is False
    assert _target.build_headers()["X-Source"] == "A"
    assert any("owned by registry" in r["reason"] for r in report.rejections)

    # 清理：先回滚才释放占用
    assert r1.revert(TARGET) is True


def test_cross_registry_strict_raises_conflict():
    r1 = _reg("a", [_spec("a", "A")])
    r2 = Registry(SelectionConfig("b", {}, True), [_spec("b", "B")], strict=True)
    r1.apply(TARGET)
    with pytest.raises(ConflictError):
        r2.apply(TARGET)
    r1.revert(TARGET)


def test_claim_released_after_revert_then_reapply():
    r1 = _reg("a", [_spec("a", "A")])
    assert r1.apply(TARGET) is True
    assert TARGET in claims_snapshot()
    assert r1.revert(TARGET) is True
    assert TARGET not in claims_snapshot()

    # 占用释放后，另一实例可以接管
    r2 = _reg("b", [_spec("b", "B")])
    assert r2.apply(TARGET) is True
    assert _target.build_headers()["X-Source"] == "B"
    r2.revert(TARGET)


def test_failed_apply_does_not_hold_claim():
    bad = PatchSpec("a", "_target", "no_such_attr", lambda: None)
    reg = _reg("a", [bad])
    assert reg.apply("_target:no_such_attr") is False
    assert "_target:no_such_attr" not in claims_snapshot()


def test_stale_claim_with_still_patched_target_blocks():
    """Registry 实例被回收但补丁还在：也应阻止新实例接管。"""
    r1 = _reg("a", [_spec("a", "A")])
    r1.apply(TARGET)
    del r1
    gc.collect()

    # 目标函数上仍有 funcpatch 标记，陈旧占用不应被自动放行
    r2 = _reg("b", [_spec("b", "B")])
    report = AuditReport()
    assert r2.apply(TARGET, report) is False
    assert any("stale claim" in r["reason"] for r in report.rejections)

    # 手动恢复原函数后清理占用，再让新实例接管
    import wrapt.patches as wp  # type: ignore[import-untyped]

    def original(cookie=None):
        headers = {"Content-Type": "application/json", "X-Source": "original"}
        if cookie:
            headers["cookie"] = cookie
        return headers

    parent, attr, _ = wp.resolve_path(_target, "build_headers")
    wp.apply_patch(parent, attr, original)
    clear_all()
    assert r2.apply(TARGET) is True
    r2.revert(TARGET)
