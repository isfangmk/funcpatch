"""批量事务、预演校验、生命周期测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

import funcpatch.loader as loader  # noqa: E402
from funcpatch import (  # noqa: E402
    AuditReport,
    PatchSpec,
    Registry,
    SelectionConfig,
    bootstrap,
    validate,
    validate_spec,
)


def _spec(attr: str, marker: str, owner: str = "a", **kw) -> PatchSpec:
    def impl(*args, **kwargs):
        return {"X-Source": marker}

    return PatchSpec(owner=owner, target_module="_target", target_attr=attr, replacement=impl, **kw)


def _reg(specs: list[PatchSpec], *, strict: bool = False) -> Registry:
    return Registry(SelectionConfig("a", {}, True), specs, strict=strict)


# ------------------------------------------------------------------ 事务


def test_apply_all_success():
    reg = _reg([_spec("build_headers", "p1"), _spec("greet", "p2")])
    result = reg.apply_all(["_target:build_headers", "_target:greet"])
    assert result.ok
    assert len(result.applied) == 2
    assert _target.build_headers()["X-Source"] == "p1"


def test_apply_all_rolls_back_on_failure():
    """第二个失败 → 第一个也回滚，不留半成品。"""
    bad = PatchSpec("a", "_target", "no_such_attr", lambda: None)
    reg = _reg([_spec("build_headers", "p1"), bad])
    result = reg.apply_all(["_target:build_headers", "_target:no_such_attr"])
    assert not result.ok
    assert result.rolled_back == ["_target:build_headers"]
    assert result.applied == []
    assert _target.build_headers()["X-Source"] == "original"


def test_transaction_rolls_back_on_exception():
    reg = _reg([_spec("build_headers", "p1")])
    with pytest.raises(RuntimeError):
        with reg.transaction():
            reg.apply("_target:build_headers")
            raise RuntimeError("boom")
    assert _target.build_headers()["X-Source"] == "original"


def test_transaction_keeps_changes_on_success():
    reg = _reg([_spec("build_headers", "p1")])
    with reg.transaction():
        reg.apply("_target:build_headers")
    assert _target.build_headers()["X-Source"] == "p1"


# ------------------------------------------------------------------ 预演校验


def test_validate_ok():
    spec = _spec("build_headers", "p1")
    result = validate_spec(spec)
    assert result.ok
    assert result.to_dict()["ok"] is True


def test_validate_hash_mismatch():
    spec = _spec("build_headers", "p1", expect_hash="bad")
    result = validate_spec(spec)
    assert not result.ok
    assert any("hash mismatch" in p for p in result.problems)


def test_validate_bad_target():
    spec = PatchSpec("a", "_target", "no_such_attr", lambda: None)
    result = validate_spec(spec)
    assert not result.ok
    assert "target resolution failed" in result.problems


def test_validate_owner_mismatch():
    spec = _spec("build_headers", "p1")
    result = validate_spec(spec, owner="b")
    assert not result.ok
    assert any("owner mismatch" in p for p in result.problems)


def test_validate_batch():
    good = _spec("build_headers", "p1")
    bad = _spec("build_headers", "p1", expect_hash="bad")
    results = validate([good, bad])
    assert results[0].ok and not results[1].ok


def test_registry_plan():
    good = _spec("build_headers", "p1")
    reg = _reg([good])
    plan = reg.plan()
    assert len(plan) == 1
    assert plan[0]["target"] == "_target:build_headers"
    assert plan[0]["would_apply"] is True
    assert plan[0]["selected"] == "a"


def test_registry_plan_already_applied():
    """已应用目标预演为幂等成功，reason 标明 already applied。"""
    spec = _spec("build_headers", "p1")
    reg = _reg([spec])
    assert reg.apply(spec.target) is True
    try:
        plan = [p for p in reg.plan() if p["target"] == spec.target][0]
        assert plan["would_apply"] is True
        assert plan["reason"] == "already applied"
    finally:
        reg.revert_all()


def test_registry_plan_disabled():
    reg = Registry(SelectionConfig("a", {}, False), [_spec("build_headers", "p1")])
    plan = reg.plan()
    assert plan[0]["would_apply"] is False
    assert plan[0]["reason"] == "disabled"


# ------------------------------------------------------------------ 生命周期


def test_bootstrap_is_idempotent():
    spec = _spec("build_headers", "p1")
    reg1 = bootstrap(specs=[spec])
    reg2 = bootstrap(specs=[spec])
    assert reg1 is reg2


def test_shutdown_reverts_and_clears():
    spec = _spec("build_headers", "p1")
    reg = bootstrap(config=SelectionConfig("a", {}, True), specs=[spec])
    reg.apply("_target:build_headers")
    assert _target.build_headers()["X-Source"] == "p1"

    count = loader.shutdown()
    assert count == 1
    assert loader.get_registry() is None
    assert _target.build_headers()["X-Source"] == "original"


def test_bootstrap_disabled_registers_no_hooks():
    cfg = SelectionConfig("a", {}, False)
    bootstrap(config=cfg, specs=[_spec("build_headers", "p1")])
    assert loader._HOOKS == {}


def test_audit_new_since_last_log():
    report = AuditReport()
    report.entries.append({"owner": "a", "target": "t"})
    assert report.new_since_last_log() == 1
    assert report.log() == 1
    assert report.new_since_last_log() == 0


def test_audit_clear_and_to_dict():
    report = AuditReport()
    report.entries.append({"owner": "a", "target": "t"})
    report.conflicts.append({"target": "t", "chosen": "a", "skipped": "b"})
    data = report.to_dict()
    assert len(data["entries"]) == 1 and len(data["conflicts"]) == 1
    report.clear()
    assert report.to_dict() == {"entries": [], "conflicts": [], "rejections": []}
