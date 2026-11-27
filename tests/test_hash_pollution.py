"""已打补丁目标的版本校验：hash 必须比对原实现，而非替代实现。

补丁生效后，目标位置上的对象已被替换成替代实现。若直接对它取源码，
得到的是替代实现的 hash，会导致：

  * 版本校验误报 "hash mismatch"（原实现其实没变过）；
  * `funcpatch hash` 采集到替代实现的 hash，填进 expect_hash 后补丁永远无法应用；
  * 第二个 owner 申请同一目标时，真实原因（目标已被占用）被 hash 原因掩盖。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    AuditReport,
    PatchSpec,
    Registry,
    SelectionConfig,
    source_hash,
    validate_spec,
)
from funcpatch._claims import clear_all  # noqa: E402

TARGET = "_target:build_headers"


def _reg(specs, owner="a"):
    """构造 Registry；注意不要清空占用表——跨 Registry 的占用场景依赖它。"""
    return Registry(SelectionConfig(owner, {}, True), specs)


def _impl(tag="patched"):
    def impl(cookie=None):
        return {"X-Source": tag}

    return impl


def test_source_hash_of_patched_target_is_polluted():
    """前提确认：补丁生效后，目标位置上的对象已是替代实现。"""
    clear_all()
    original_hash = source_hash(_target.build_headers)
    spec = PatchSpec("a", "_target", "build_headers", _impl())
    reg = _reg([spec])
    assert reg.apply(TARGET) is True
    try:
        assert source_hash(_target.build_headers) != original_hash
    finally:
        reg.revert_all()
        clear_all()


def test_validate_uses_original_hash_when_target_already_patched():
    """目标已被接管时，校验应比对原实现，不应报假 hash mismatch。"""
    clear_all()
    original_hash = source_hash(_target.build_headers)
    spec = PatchSpec("a", "_target", "build_headers", _impl(), expect_hash=original_hash)
    reg = _reg([spec])
    assert reg.apply(TARGET) is True
    try:
        result = validate_spec(spec)
        assert result.ok is True, result.problems
        assert result.problems == []
    finally:
        reg.revert_all()
        clear_all()


def test_second_owner_conflict_reported_as_conflict_not_hash_mismatch():
    clear_all()
    """第二个 owner 的真实原因是被占用，不应被 hash mismatch 掩盖。"""
    original_hash = source_hash(_target.build_headers)
    reg_a = _reg([PatchSpec("a", "_target", "build_headers", _impl("A"))], owner="a")
    assert reg_a.apply(TARGET) is True

    spec_b = PatchSpec("b", "_target", "build_headers", _impl("B"), expect_hash=original_hash)
    reg_b = _reg([spec_b], owner="b")
    report = AuditReport()
    try:
        assert reg_b.apply(TARGET, report) is False
        reasons = [r["reason"] for r in report.rejections]
        assert reasons, "应记录拒绝原因"
        assert any("claimed by owner=a" in r for r in reasons), reasons
        assert not any("hash mismatch" in r for r in reasons), reasons
    finally:
        reg_a.revert_all()
        reg_b.revert_all()
        clear_all()


def test_apply_with_correct_hash_succeeds_after_other_owner_reverted():
    clear_all()
    """占用释放后，持正确 hash 的补丁应能正常应用。"""
    original_hash = source_hash(_target.build_headers)
    reg_a = _reg([PatchSpec("a", "_target", "build_headers", _impl("A"))], owner="a")
    assert reg_a.apply(TARGET) is True
    assert reg_a.revert(TARGET) is True

    spec_b = PatchSpec("b", "_target", "build_headers", _impl("B"), expect_hash=original_hash)
    reg_b = _reg([spec_b], owner="b")
    try:
        assert reg_b.apply(TARGET) is True
        assert _target.build_headers()["X-Source"] == "B"
    finally:
        reg_b.revert_all()
        clear_all()


def test_cli_hash_reports_original_hash_when_target_patched(monkeypatch, capsys):
    clear_all()
    """funcpatch hash 在目标已被打补丁时仍应给出原实现的 hash。"""
    from funcpatch import cli as cli_mod

    original_hash = source_hash(_target.build_headers)
    spec = PatchSpec("a", "_target", "build_headers", _impl())
    reg = _reg([spec])
    assert reg.apply(TARGET) is True
    try:
        monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [spec])
        assert cli_mod.main(["hash"]) == 0
        out = capsys.readouterr().out
        assert original_hash in out
        # 采集到的必须是原实现的 hash，而不是替代实现的
        assert source_hash(_impl()) not in out
    finally:
        reg.revert_all()
        clear_all()


def test_conflict_reason_identical_in_plan_and_apply():
    clear_all()
    """plan 与 apply 对同一次冲突必须给出同样的原因，否则排查会走偏。"""
    reg_a = _reg([PatchSpec("a", "_target", "build_headers", _impl("A"))], owner="a")
    assert reg_a.apply(TARGET) is True
    spec_b = PatchSpec("b", "_target", "build_headers", _impl("B"))
    reg_b = _reg([spec_b], owner="b")
    try:
        report = AuditReport()
        reg_b.apply(TARGET, report)
        apply_reason = report.rejections[-1]["reason"]
        plan_reason = reg_b.plan()[0]["reason"]
        assert apply_reason == plan_reason
        assert "claimed by owner=a" in apply_reason
    finally:
        reg_a.revert_all()
        reg_b.revert_all()
        clear_all()
