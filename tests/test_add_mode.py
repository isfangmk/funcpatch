"""add 模式：为目标类添加原本不存在的方法/属性，支持回滚与校验。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    AuditReport,
    DeprecatedTargetWarning,
    PatchSpec,
    Registry,
    SelectionConfig,
    validate_spec,
)
from funcpatch._claims import claims_snapshot, clear_all  # noqa: E402


def _reg(specs, config=None):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs)


def test_add_mode_adds_method_and_reverts():
    target = "_target:Settings.added_method"
    spec = PatchSpec(
        "a", "_target", "Settings.added_method", lambda self, x: f"added-{x}", mode="add"
    )
    reg = _reg([spec])
    assert not hasattr(_target.Settings, "added_method")
    try:
        assert reg.apply(target) is True
        method_name = "added_method"
        assert getattr(_target.Settings(), method_name)("x") == "added-x"
        assert reg.is_applied(target)
    finally:
        assert reg.revert(target) is True
        assert not hasattr(_target.Settings, "added_method")
        clear_all()


def test_add_mode_rejects_existing_attribute():
    spec = PatchSpec("a", "_target", "greet", lambda name: name, mode="add")
    reg = _reg([spec])
    report = AuditReport()
    assert reg.apply("_target:greet", report) is False
    assert any("already exists" in r["reason"] for r in report.rejections)


def test_add_mode_rejects_unresolvable_parent():
    """父对象不存在时拒绝应用并记录原因。"""
    spec = PatchSpec("a", "_target", "NoSuchClass.method", lambda self: 1, mode="add")
    reg = _reg([spec])
    report = AuditReport()
    assert reg.apply(spec.target, report) is False
    assert any("resolve parent failed" in r["reason"] for r in report.rejections)


def test_add_mode_validate_unresolvable_parent():
    """校验时父对象解析失败应报 problem 而非抛异常。"""
    spec = PatchSpec("a", "_target", "NoSuchClass.method", lambda self: 1, mode="add")
    result = validate_spec(spec)
    assert result.ok is False
    assert any("parent resolution failed" in p for p in result.problems)


def test_add_mode_validate_existing_and_missing():
    missing = PatchSpec("a", "_target", "Settings.brand_new", lambda self: 1, mode="add")
    existing = PatchSpec("a", "_target", "greet", lambda: 1, mode="add")
    assert validate_spec(missing).ok is True
    result = validate_spec(existing)
    assert result.ok is False
    assert any("already exists" in p for p in result.problems)


def test_add_mode_claim_released_on_revert():
    target = "_target:Settings.temp_attr"
    spec = PatchSpec("a", "_target", "Settings.temp_attr", lambda self: 1, mode="add")
    reg = _reg([spec])
    try:
        reg.apply(target)
        assert target in claims_snapshot()
        reg.revert(target)
        assert target not in claims_snapshot()
    finally:
        clear_all()


def test_add_mode_rolls_back_in_transaction():
    target = "_target:Settings.tx_attr"
    spec = PatchSpec("a", "_target", "Settings.tx_attr", lambda self: 1, mode="add")
    reg = _reg([spec])
    try:
        with pytest.raises(RuntimeError):
            with reg.transaction():
                reg.apply(target)
                assert hasattr(_target.Settings, "tx_attr")
                raise RuntimeError("boom")
        assert not hasattr(_target.Settings, "tx_attr")
    finally:
        clear_all()


def test_add_mode_validate_unimportable_module_reports_problem():
    """目标模块不可导入时应报告问题，而不是抛异常中断整批校验。"""
    spec = PatchSpec("a", "_no_such_module_xyz", "Cls.meth", lambda self: 1, mode="add")
    result = validate_spec(spec)
    assert result.ok is False
    assert any("import failed" in p for p in result.problems)


def test_add_mode_plan_unimportable_module_reports_reason():
    """预演同样不应抛异常：目标不可导入应体现在 reason 里。"""
    spec = PatchSpec("a", "_no_such_module_xyz", "Cls.meth", lambda self: 1, mode="add")
    reg = _reg([spec])
    plan = reg.plan()
    assert plan[0]["would_apply"] is False
    assert "import failed" in plan[0]["reason"]


def test_add_mode_respects_requires_constraint():
    """部署版本约束不满足时应拒绝添加属性。"""
    target = "_target:Settings.added_req"
    spec = PatchSpec(
        "a",
        "_target",
        "Settings.added_req",
        lambda self: 1,
        mode="add",
        requires=("wrapt>=999",),
    )
    reg = _reg([spec])
    report = AuditReport()
    assert reg.apply(target, report) is False
    assert any("version conflict" in r["reason"] for r in report.rejections)
    assert not hasattr(_target.Settings, "added_req")
    clear_all()


def test_add_mode_respects_disabled_flag():
    """enabled=False 时不应添加属性。"""
    target = "_target:Settings.added_disabled"
    spec = PatchSpec(
        "a", "_target", "Settings.added_disabled", lambda self: 1, mode="add", enabled=False
    )
    reg = _reg([spec])
    report = AuditReport()
    assert reg.apply(target, report) is False
    assert any("disabled" in r["reason"] for r in report.rejections)
    assert not hasattr(_target.Settings, "added_disabled")
    clear_all()


def test_add_mode_warns_on_deprecated_target():
    """废弃目标应发出告警（与 replace / wrap 一致）。"""
    target = "_target:Settings.added_dep"
    spec = PatchSpec(
        "a",
        "_target",
        "Settings.added_dep",
        lambda self: 1,
        mode="add",
        deprecated="改用 Settings.new_api",
    )
    reg = _reg([spec])
    with pytest.warns(DeprecatedTargetWarning):
        assert reg.apply(target) is True
    reg.revert_all()
    clear_all()
