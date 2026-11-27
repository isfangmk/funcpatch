"""关键行为回归测试：事务、回滚、生命周期与并发。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    AuditReport,
    PatchSpec,
    Registry,
    SelectionConfig,
    claims_snapshot,
)
from funcpatch._claims import clear_all  # noqa: E402


def _spec(attr: str, tag: str, owner: str = "a", **kw) -> PatchSpec:
    def impl(*args, **kwargs):
        return {"X-Source": tag}

    return PatchSpec(owner, "_target", attr, impl, **kw)


def _reg(specs: list[PatchSpec]) -> Registry:
    clear_all()
    return Registry(SelectionConfig("a", {}, True), specs)


# ------------------------------------------------------------------ apply_all


def test_apply_all_does_not_revert_preexisting():
    """apply_all 失败时保留批次前已应用的补丁。"""
    pre = _spec("build_headers", "pre")
    reg = _reg([pre, _spec("greet", "g")])
    reg.apply("_target:build_headers")

    result = reg.apply_all(["_target:build_headers", "_target:greet", "_target:no_such_attr"])

    assert not result.ok
    assert "_target:build_headers" in result.preexisting
    # 批次前的补丁必须原样保留
    assert reg.is_applied("_target:build_headers")
    assert _target.build_headers()["X-Source"] == "pre"


def test_apply_all_keeps_applied_list_on_rollback_failure():
    result_snapshot = []

    reg = _reg([_spec("greet", "g")])
    # 让 revert 失败
    import funcpatch.registry as regmod

    def broken_resolve(*args, **kwargs):
        raise RuntimeError("revert boom")

    orig = regmod.resolve_owner
    regmod.resolve_owner = broken_resolve
    try:
        result = reg.apply_all(["_target:greet", "_target:no_such_attr"])
    finally:
        regmod.resolve_owner = orig
    result_snapshot.append(result)

    result = result_snapshot[0]
    assert not result.ok
    assert ("_target:greet", "rollback failed") in result.failed
    assert "_target:greet" in result.applied  # 仍装着，不能谎报成功或回滚


# ------------------------------------------------------------------ transaction


def test_transaction_revert_then_reapply_rolls_back():
    """事务块内 revert→reapply 同一目标后，异常时回退到初始状态。"""
    initial = _spec("build_headers", "initial")
    reg = _reg([initial, _spec("build_headers", "new", owner="b")])
    reg.apply("_target:build_headers")
    assert _target.build_headers()["X-Source"] == "initial"

    with pytest.raises(RuntimeError):
        with reg.transaction():
            reg.revert("_target:build_headers")
            reg2 = Registry(
                SelectionConfig("b", {}, True),
                [_spec("build_headers", "new", owner="b")],
            )
            reg2.apply("_target:build_headers")
            raise RuntimeError("boom")

    # 必须恢复到事务开始时的 initial 实现
    assert _target.build_headers()["X-Source"] == "initial"
    assert reg.is_applied("_target:build_headers")
    clear_all()


def test_transaction_nested():
    reg = _reg([_spec("greet", "outer"), _spec("build_headers", "inner")])
    with reg.transaction():
        reg.apply("_target:greet")
        try:
            with reg.transaction():
                reg.apply("_target:build_headers")
                raise RuntimeError("inner")
        except RuntimeError:
            pass
        # 内层已回滚，外层仍在
        assert _target.greet("x") == {"X-Source": "outer"}
        assert not reg.is_applied("_target:build_headers")
    reg.revert("_target:greet")


# ------------------------------------------------------------------ get_report


def test_get_report_exposed():
    from funcpatch import get_report, loader

    loader._REPORT = AuditReport()
    assert get_report() is loader._REPORT


# ------------------------------------------------------------------ loader / shutdown


def test_shutdown_does_not_clear_foreign_claims():
    """shutdown 不清除其它 Registry 的占用。"""
    import funcpatch.loader as loader
    from funcpatch import bootstrap
    from funcpatch._claims import clear_all as _clear

    _clear()
    # 全局 registry 通过 bootstrap 建立
    bootstrap(config=SelectionConfig("a", {}, True), specs=[_spec("build_headers", "a")])
    # 另一个独立 registry 占用不同目标
    foreign = _reg([_spec("greet", "foreign")])
    foreign.apply("_target:greet")

    loader.shutdown()

    # 外键的占用仍在
    assert "_target:greet" in claims_snapshot()
    assert foreign.is_applied("_target:greet")
    foreign.revert("_target:greet")
    _clear()


def test_concurrent_bootstrap_single_registry():
    import threading

    import funcpatch.loader as loader
    from funcpatch import bootstrap, get_registry
    from funcpatch._claims import clear_all as _clear

    _clear()
    loader._REGISTRY = None
    loader._REPORT = None
    loader._HOOKS.clear()

    results = []

    def job(owner):
        results.append(
            bootstrap(
                config=SelectionConfig(owner, {}, True),
                specs=[PatchSpec(owner, "_target", "greet", lambda *a, **k: owner)],
            )
        )

    threads = [threading.Thread(target=job, args=(o,)) for o in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results[0] is results[1] is get_registry()
    loader.shutdown()
    _clear()


def test_rebootstrap_uses_stable_hook():
    """shutdown 后重新 bootstrap：hook 应作用于新 Registry，不重复注册。"""
    import funcpatch.loader as loader
    from funcpatch import bootstrap
    from funcpatch._claims import clear_all as _clear

    _clear()
    loader._REGISTRY = None
    loader._REPORT = None
    loader._HOOKS.clear()

    first = bootstrap(config=SelectionConfig("a", {}, True), specs=[_spec("greet", "a")])
    hook_count_before = loader._HOOKS.get("_target")
    loader.shutdown()
    second = bootstrap(config=SelectionConfig("b", {}, True), specs=[_spec("greet", "b")])

    assert first is not second
    assert loader._HOOKS.get("_target") is hook_count_before  # 同一个 hook，未重复注册
    loader.shutdown()
    _clear()


# ------------------------------------------------------------------ claims 恢复与 property_part


def test_clear_claim_public_recovery():
    """陈旧占用可通过公开 API 恢复，无需私有 clear_all。"""
    import gc

    from funcpatch import claims_snapshot, clear_claim

    r1 = _reg([_spec("build_headers", "a")])
    r1.apply("_target:build_headers")
    del r1
    gc.collect()
    assert "_target:build_headers" in claims_snapshot()

    assert clear_claim("_target:build_headers") is True
    assert clear_claim("_target:build_headers") is False  # 幂等

    r2 = _reg([_spec("build_headers", "b")])
    assert r2.apply("_target:build_headers") is True
    r2.revert("_target:build_headers")


def test_property_part_claim_keys_distinct():
    """property get/set 是不同目标，不该互相阻塞。"""
    from funcpatch import claim_key

    assert claim_key("_target:Mutable.value", "get") == "_target:Mutable.value"
    assert claim_key("_target:Mutable.value", "set") == "_target:Mutable.value#set"
    assert claim_key("_target:Mutable.value", "delete") == "_target:Mutable.value#delete"


def test_get_set_different_owners_coexist():
    def getter(self):
        return "patched-get"

    def setter(self, value):
        self._value = f"patched:{value}"

    get_spec = PatchSpec("a", "_target", "Mutable.value", getter, property_part="get")
    set_spec = PatchSpec("b", "_target", "Mutable.value", setter, property_part="set")

    clear_all()
    r1 = Registry(SelectionConfig("a", {}, True), [get_spec])
    r2 = Registry(SelectionConfig("b", {}, True), [set_spec])
    assert r1.apply("_target:Mutable.value") is True
    assert r2.apply("_target:Mutable.value") is True  # 不同 part 不冲突

    obj = _target.Mutable()
    assert obj.value == "patched-get"
    obj.value = "x"
    assert obj._value == "patched:x"
    r1.revert("_target:Mutable.value")
    r2.revert("_target:Mutable.value")
    clear_all()


# ------------------------------------------------------------------ plan / 签名 / 审计并发


def test_plan_reports_claim_conflict():
    """plan 检查占用表，冲突目标不报可应用。"""

    clear_all()
    owner_a = Registry(SelectionConfig("a", {}, True), [_spec("build_headers", "a")])
    assert owner_a.apply("_target:build_headers") is True

    planner = Registry(SelectionConfig("b", {}, True), [_spec("build_headers", "b", owner="b")])
    plan = [p for p in planner.plan() if p["target"] == "_target:build_headers"][0]
    assert plan["would_apply"] is False
    assert "claimed by owner=a" in plan["reason"]

    owner_a.revert("_target:build_headers")
    clear_all()


def test_signature_check_real_wrapt_wrapper_no_false_positive():
    from funcpatch import validate_spec

    def wrapper(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    spec = PatchSpec("a", "_target", "build_headers", wrapper, mode="wrap")
    result = validate_spec(spec, check_signature=True)
    assert result.warnings == []


def test_signature_check_classmethod_no_false_positive():
    from funcpatch import validate_spec

    def impl(cls):
        return cls.__name__

    spec = PatchSpec("a", "_target", "Descriptors.who", impl)
    result = validate_spec(spec, check_signature=True)
    assert result.warnings == []


def test_audit_concurrent_log_no_lost_entries():
    import threading

    from funcpatch import AuditReport

    report = AuditReport()
    total = 500

    def produce():
        for i in range(total):
            report.entries.append({"owner": "a", "target": f"t{i}"})

    def consume():
        for _ in range(total):
            report.log()

    t1 = threading.Thread(target=produce)
    t2 = threading.Thread(target=consume)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    report.log()  # 冲刷剩余
    # 游标最终追上实际条目数（不丢条目）
    assert report.new_since_last_log() == 0


# ------------------------------------------------------------------ property 部分回滚


def test_property_partial_revert_preserves_other_owner_patch():
    """回滚 get 不应清掉别人打在 set 上的补丁，也不应让旧补丁复活。"""
    from funcpatch import claim_key

    def getter(self):
        return "PATCHED-GET"

    def setter(self, value):
        self._value = f"PATCHED:{value}"

    get_spec = PatchSpec("a", "_target", "Mutable.value", getter, property_part="get")
    set_spec = PatchSpec("b", "_target", "Mutable.value", setter, property_part="set")

    clear_all()
    # 用独立 Registry 模拟两个 owner 共存
    r1 = Registry(SelectionConfig("a", {}, True), [get_spec])
    r2 = Registry(SelectionConfig("b", {}, True), [set_spec])
    assert r1.apply("_target:Mutable.value") is True
    assert r2.apply("_target:Mutable.value") is True

    obj = _target.Mutable()
    assert obj.value == "PATCHED-GET"
    obj.value = "x"
    assert obj._value == "PATCHED:x"

    # 回滚 get：get 恢复原始实现（读 _value），set 补丁仍在
    assert r1.revert("_target:Mutable.value") is True
    obj2 = _target.Mutable()
    obj2.value = "x"
    assert obj2._value == "PATCHED:x"  # set 补丁仍在
    assert obj2.value == "PATCHED:x"  # get 已恢复原始（读被 set 改写的值）

    # 回滚 set：两个 part 都恢复原始
    assert r2.revert("_target:Mutable.value") is True
    obj3 = _target.Mutable()
    obj3.value = "y"
    assert obj3._value == "y"
    assert obj3.value == "y"

    assert claim_key("_target:Mutable.value", "set") not in claims_snapshot()
    clear_all()


def test_transaction_rollback_property_releases_claim():
    """事务回滚 property(set) 补丁后不应泄漏占用。"""
    from funcpatch import claim_key

    def setter(self, value):
        self._value = value

    spec = PatchSpec("a", "_target", "Mutable.value", setter, property_part="set")
    clear_all()
    reg = Registry(SelectionConfig("a", {}, True), [spec])
    try:
        with reg.transaction():
            assert reg.apply("_target:Mutable.value") is True
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert claim_key("_target:Mutable.value", "set") not in claims_snapshot()
    clear_all()


def test_apply_all_failure_uses_this_batch_rejection_reason():
    """apply_all 失败原因应取本次新增的 rejection，而非之前遗留的。"""
    clear_all()
    report = AuditReport()
    # 预先制造一条无关 rejection
    report.rejections.append({"owner": "x", "target": "old", "reason": "old reason", "at": ""})

    reg = _reg([_spec("greet", "g")])
    result = reg.apply_all(["_target:greet", "_target:no_such_attr"], report)
    assert not result.ok
    assert result.failed
    # 失败原因应是本次目标解析失败，而不是 "old reason"
    assert "old reason" not in result.failed[-1][1]
    clear_all()


def test_audit_log_tolerates_malformed_entries():
    """条目缺字段时 log 不应抛异常，且游标仍前进不丢条目。"""
    from funcpatch import AuditReport

    report = AuditReport()
    report.entries.append({"at": ""})  # 缺 owner/target
    report.entries.append({"owner": "a", "target": "t", "at": ""})
    n = report.log()  # 不应抛 KeyError
    assert n == 2
    assert report.new_since_last_log() == 0
