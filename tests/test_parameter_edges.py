"""参数校验、诊断边界与 hash 回退路径测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import PatchSpec, Registry, SelectionConfig, get_applied_info, is_patched  # noqa: E402
from funcpatch.spec import source_hash  # noqa: E402


def test_spec_validation_empty_owner():
    with pytest.raises(ValueError):
        PatchSpec("", "m", "a", lambda: None)


def test_spec_validation_empty_module():
    with pytest.raises(ValueError):
        PatchSpec("a", "", "attr", lambda: None)


def test_spec_validation_empty_attr():
    with pytest.raises(ValueError):
        PatchSpec("a", "m", "", lambda: None)


def test_spec_validation_non_callable():
    with pytest.raises(TypeError):
        PatchSpec("a", "m", "attr", replacement="not callable")  # type: ignore[arg-type]


def test_spec_validation_bad_mode():
    with pytest.raises(ValueError):
        PatchSpec("a", "m", "attr", lambda: None, mode="bad")  # type: ignore[arg-type]


def test_source_hash_fallback_for_builtin():
    """内置函数没有源码，hash 应回退到字节码/repr 路径。"""
    h = source_hash(len)
    assert isinstance(h, str) and len(h) == 16


def test_source_hash_stable():
    h1 = source_hash(_target.build_headers)
    h2 = source_hash(_target.build_headers)
    assert h1 == h2


def test_is_patched_unknown_target():
    assert is_patched("_target:no_such_attr") is False
    assert get_applied_info("_target:no_such_attr") is None


def test_is_patched_with_registry():
    def impl(*args, **kwargs):
        return {"X-Source": "patched"}

    spec = PatchSpec("a", "_target", "build_headers", impl)
    reg = Registry(SelectionConfig("a", {}, True), [spec])
    assert is_patched("_target:build_headers", registry=reg) is False
    reg.apply("_target:build_headers")
    assert is_patched("_target:build_headers", registry=reg) is True
    reg.revert("_target:build_headers")


def test_select_no_candidates():
    reg = Registry(SelectionConfig("a", {}, True), [])
    chosen, skipped = reg.select("_target:build_headers")
    assert chosen is None and skipped == []


def test_revert_missing_returns_false():
    reg = Registry(SelectionConfig("a", {}, True), [])
    assert reg.revert("_target:build_headers") is False
    assert reg.revert("_target:build_headers", missing_ok=False) is False


def test_revert_missing_strict_raises():
    from funcpatch import TargetNotFoundError

    reg = Registry(SelectionConfig("a", {}, True), [], strict=True)
    with pytest.raises(TargetNotFoundError):
        reg.revert("_target:build_headers", missing_ok=False)
