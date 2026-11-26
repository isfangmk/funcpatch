"""funcpatch 核心测试：单一生效、版本校验、回滚、审计、发现。"""

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
    source_hash,
)
from funcpatch.discovery import discover_from_directory  # noqa: E402

TARGET = "_target:build_headers"
TARGET_METHOD = "_target:Settings.build_headers"


def _config(owner: str, targets: dict | None = None) -> SelectionConfig:
    return SelectionConfig(default_owner=owner, target_owners=targets or {}, enabled=True)


def _spec(owner: str, target_attr: str, marker: str, **kwargs) -> PatchSpec:
    def replacement(*args, **kwargs_inner):
        return {"X-Source": marker}

    replacement.__name__ = f"replacement_{owner}_{marker}"
    return PatchSpec(
        owner=owner,
        target_module="_target",
        target_attr=target_attr,
        replacement=replacement,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def restore_target():
    """每个测试后恢复目标函数，避免污染。"""
    original = _target.build_headers
    original_method = _target.Settings.build_headers
    yield
    _target.build_headers = original
    _target.Settings.build_headers = original_method


# --------------------------------------------------------------- 单一生效


def test_single_winner_by_owner():
    """两个 owner 改同一目标，只有选中者生效。"""
    a = _spec("client_a", "build_headers", "client_a")
    b = _spec("client_b", "build_headers", "client_b")
    reg = Registry(_config("client_b"), [a, b])  # 选 client_b

    chosen, skipped = reg.select(TARGET)
    assert chosen is not None and chosen.owner == "client_b"
    assert skipped == ["client_a"]

    assert reg.apply(TARGET) is True
    assert _target.build_headers()["X-Source"] == "client_b"


def test_no_owner_applies_nothing():
    """未指定 owner → fail-safe，不应用任何补丁。"""
    a = _spec("client_a", "build_headers", "client_a")
    reg = Registry(_config(""), [a])
    assert reg.apply(TARGET) is False
    assert _target.build_headers()["X-Source"] == "original"


def test_selected_owner_missing_target():
    """选中 owner 未注册该目标 → 告警，不应用。"""
    a = _spec("client_a", "build_headers", "client_a")
    reg = Registry(_config("client_b"), [a])
    assert reg.apply(TARGET) is False
    assert _target.build_headers()["X-Source"] == "original"


def test_target_specific_owner_overrides_default():
    """toml [targets] 精确匹配覆盖 default owner。"""
    a = _spec("client_a", "build_headers", "client_a")
    b = _spec("client_b", "build_headers", "client_b")
    cfg = SelectionConfig(
        default_owner="client_a",
        target_owners={TARGET: "client_b"},
        enabled=True,
    )
    reg = Registry(cfg, [a, b])
    assert reg.apply(TARGET) is True
    assert _target.build_headers()["X-Source"] == "client_b"


# --------------------------------------------------------------- 版本校验


def test_hash_mismatch_rejects():
    """目标函数被改过（hash 不符）→ 拒绝应用。"""
    a = _spec("client_a", "build_headers", "client_a", expect_hash="deadbeef")
    reg = Registry(_config("client_a"), [a])
    assert reg.apply(TARGET) is False
    assert _target.build_headers()["X-Source"] == "original"


def test_hash_match_applies():
    """hash 正确 → 正常应用。"""
    h = source_hash(_target.build_headers)
    a = _spec("client_a", "build_headers", "client_a", expect_hash=h)
    reg = Registry(_config("client_a"), [a])
    assert reg.apply(TARGET) is True
    assert _target.build_headers()["X-Source"] == "client_a"


# --------------------------------------------------------------- 回滚


def test_revert_restores_original():
    """replace 模式回滚恢复原函数。"""
    a = _spec("client_a", "build_headers", "client_a")
    reg = Registry(_config("client_a"), [a])
    reg.apply(TARGET)
    assert _target.build_headers()["X-Source"] == "client_a"
    assert reg.revert(TARGET) is True
    assert _target.build_headers()["X-Source"] == "original"


def test_revert_class_method():
    """类方法替换与回滚（验证 resolve_path/resolve_owner 正确性）。"""
    a = _spec("client_a", "Settings.build_headers", "client_a")
    reg = Registry(_config("client_a"), [a])
    reg.apply(TARGET_METHOD)
    assert _target.Settings().build_headers()["X-Source"] == "client_a"
    assert reg.revert(TARGET_METHOD) is True
    assert _target.Settings().build_headers()["X-Source"] == "original-method"


def test_apply_is_idempotent():
    reg = Registry(_config("client_a"), [_spec("client_a", "build_headers", "x")])
    assert reg.apply(TARGET) is True
    assert reg.apply(TARGET) is True  # 第二次幂等
    assert reg.is_applied(TARGET)


# --------------------------------------------------------------- wrap 模式


def test_wrap_mode_can_call_original():
    """wrap 模式用 wrapt.FunctionWrapper 包一层，可调用原实现。"""

    def wrapper(original, self_or_arg, args, kwargs):
        result = original(*args, **kwargs)
        result = dict(result)
        result["X-Wrapped"] = "yes"
        return result

    spec = PatchSpec(
        owner="client_a",
        target_module="_target",
        target_attr="build_headers",
        replacement=wrapper,
        mode="wrap",
    )
    reg = Registry(_config("client_a"), [spec])
    assert reg.apply(TARGET) is True
    result = _target.build_headers("cookie")
    assert result["X-Source"] == "original"
    assert result["X-Wrapped"] == "yes"
    assert result["cookie"] == "cookie"
    assert reg.revert(TARGET) is True
    assert "X-Wrapped" not in _target.build_headers()


# --------------------------------------------------------------- 审计


def test_audit_reports_conflict():
    a = _spec("client_a", "build_headers", "client_a")
    b = _spec("client_b", "build_headers", "client_b")
    reg = Registry(_config("client_b"), [a, b])
    report = AuditReport()
    reg.apply(TARGET, report)
    assert any(e["owner"] == "client_b" for e in report.entries)
    assert any(c["skipped"] == "client_a" for c in report.conflicts)


def test_audit_reports_rejection():
    a = _spec("client_a", "build_headers", "client_a", expect_hash="bad")
    reg = Registry(_config("client_a"), [a])
    report = AuditReport()
    reg.apply(TARGET, report)
    assert len(report.rejections) == 1
    assert "hash mismatch" in report.rejections[0]["reason"]


# --------------------------------------------------------------- 发现


def test_discovery_from_directory():
    specs = discover_from_directory("funcpatch_demo_patches")
    assert any(s.owner == "client_a" for s in specs)
    assert any(s.owner == "client_b" for s in specs)
