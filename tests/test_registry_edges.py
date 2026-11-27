"""注册表边界：失败释放占用、第三方包装保留、批量回滚、陈旧占用。"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


import _target  # noqa: E402
import wrapt  # noqa: E402

from funcpatch import (  # noqa: E402
    AuditReport,
    PatchSpec,
    Registry,
    SelectionConfig,
)
from funcpatch import registry as registry_mod  # noqa: E402
from funcpatch._claims import claims_snapshot, clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_apply_failure_releases_claim(monkeypatch):
    """wrapt.apply_patch 抛异常时应释放占用、记录拒绝。"""
    report = AuditReport()
    reg = _reg([PatchSpec("a", "_target", "greet", lambda n: "x")])

    original_apply = registry_mod.wrapt.apply_patch

    def broken_apply(parent, attr, value):
        raise RuntimeError("apply boom")

    monkeypatch.setattr(registry_mod.wrapt, "apply_patch", broken_apply)
    try:
        assert reg.apply("_target:greet", report) is False
    finally:
        monkeypatch.setattr(registry_mod.wrapt, "apply_patch", original_apply)
    assert "_target:greet" not in claims_snapshot()
    assert any(r["reason"].startswith("apply failed") for r in report.rejections)
    clear_all()


def test_revert_keeps_third_party_wrapper():
    """funcpatch wrap 回滚不应拆掉上层第三方 wrapt 包装。"""

    def impl(wrapped, instance, args, kwargs):
        return f"patched-{args[0]}"

    reg = _reg([PatchSpec("a", "_target", "greet", impl, mode="wrap")])
    assert reg.apply("_target:greet") is True

    def third_party(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs) + "-third"

    wrapt.wrap_function_wrapper(_target, "greet", third_party)
    assert _target.greet("x") == "patched-x-third"

    reg.revert("_target:greet")
    # funcpatch 层已回滚，第三方包装仍在
    assert _target.greet("x") == "hello x-third"
    clear_all()


def test_apply_all_strict_collects_domain_exception():
    reg = _reg(
        [
            PatchSpec("a", "_target", "greet", lambda n: f"p-{n}"),
            PatchSpec("a", "_target", "no_such_attr", lambda: None, expect_hash="deadbeef"),
        ],
        strict=True,
    )
    result = reg.apply_all(["_target:greet", "_target:no_such_attr"])
    assert not result.ok
    assert result.failed
    assert any("resolve failed" in reason or "deadbeef" in reason for _, reason in result.failed)
    clear_all()


def test_revert_where_module_filter():
    def impl(*a, **k):
        return "x"

    specs = [
        PatchSpec("a", "_target", "greet", impl, tags=("g",)),
        PatchSpec("a", "_target", "build_headers", impl, tags=("h",)),
    ]
    reg = _reg(specs)
    reg.config = SelectionConfig("a", {}, True)
    reg.apply("_target:greet")
    reg.apply("_target:build_headers")

    reverted = reg.revert_where(module="_target")
    assert set(reverted) == {"_target:greet", "_target:build_headers"}
    assert not reg._applied
    clear_all()


def test_revert_where_by_owner_and_tag():
    def impl(name):
        return f"patched-{name}"

    s1 = PatchSpec("a", "_target", "greet", impl, tags=("g1",))
    s2 = PatchSpec("b", "_target", "build_headers", impl, tags=("g2",))
    reg = _reg([s1, s2], SelectionConfig("a", {}, True))
    reg.config = SelectionConfig("a", {"_target:build_headers": "b"}, True)
    assert reg.apply("_target:greet") is True
    assert reg.apply("_target:build_headers") is True

    reverted = reg.revert_where(owner="a")
    assert reverted == ["_target:greet"]
    assert reg.is_applied("_target:build_headers")
    reverted2 = reg.revert_where(tags=("g2",))
    assert reverted2 == ["_target:build_headers"]
    clear_all()


def test_revert_where_skips_non_matching_tags_and_module():
    """revert_where 按 tags / module 过滤时，不匹配的目标被跳过。"""

    def impl(*a, **k):
        return "x"

    specs = [
        PatchSpec("a", "_target", "greet", impl, tags=("g",)),
        PatchSpec("a", "_target", "build_headers", impl, tags=("other",)),
    ]
    reg = _reg(specs)
    reg.apply("_target:greet")
    reg.apply("_target:build_headers")
    try:
        # tags 不匹配：只回滚带 g 的 greet
        assert reg.revert_where(tags=("g",)) == ["_target:greet"]
        assert reg.is_applied("_target:build_headers")
        # module 不匹配：什么都不回滚
        assert reg.revert_where(module="some_other_module") == []
        assert reg.is_applied("_target:build_headers")
    finally:
        reg.revert_all()
        clear_all()


def test_unapplied_target_queries_return_none():
    reg = _reg([])
    assert reg.get_original("_target:greet") is None
    assert reg.get_wrapper("_target:greet") is None
    clear_all()


def test_plan_stale_claim_reports_conflict():
    """stale claim 且目标仍带补丁时，plan 应报不可应用。"""
    clear_all()
    r1 = _reg([PatchSpec("a", "_target", "greet", lambda n: f"p-{n}")])
    assert r1.apply("_target:greet") is True
    del r1
    gc.collect()

    # 不能用 _reg：它会 clear_all 抹掉 stale claim
    planner = Registry(
        SelectionConfig("b", {}, True),
        [PatchSpec("b", "_target", "greet", lambda n: "b")],
    )
    entry = [p for p in planner.plan() if p["target"] == "_target:greet"][0]
    assert entry["would_apply"] is False
    assert "stale claim" in entry["reason"]
    clear_all()


def test_targets_deduplicates():
    def impl(*a, **k):
        pass

    specs = [
        PatchSpec("a", "_target", "greet", impl),
        PatchSpec("b", "_target", "greet", impl),
    ]
    reg = Registry(SelectionConfig("a", {}, True), specs)
    assert reg.targets() == ["_target:greet"]

    plans = reg.plan()
    assert len([p for p in plans if p["target"] == "_target:greet"]) == 1
