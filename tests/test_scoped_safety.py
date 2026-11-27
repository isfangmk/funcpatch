"""作用域补丁的安全约束：hash 校验与进程占用检查，不能绕过 Registry 规则。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    PatchSpec,
    Registry,
    SelectionConfig,
    claims_snapshot,
    scoped_patch,
    transient_patch,
)
from funcpatch.spec import source_hash  # noqa: E402


def test_scoped_hash_mismatch_rejected():
    """目标 hash 不符时，作用域补丁也应拒绝。"""

    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl, expect_hash="deadbeef")
    with pytest.raises(ValueError, match="版本校验失败"):
        with scoped_patch("_target", "greet", spec):
            pass


def test_scoped_with_valid_hash_works():
    def impl(name):
        return f"patched-{name}"

    h = source_hash(_target.greet)
    spec = PatchSpec("a", "_target", "greet", impl, expect_hash=h)
    with scoped_patch("_target", "greet", spec):
        assert _target.greet("x") == "patched-x"
    assert _target.greet("x") == "hello x"


def test_scoped_conflicts_with_live_registry():
    """已有持久化补丁占用目标时，作用域补丁应报冲突。"""

    def impl(*args, **kwargs):
        return {"X-Source": "persistent"}

    def scoped_impl(*args, **kwargs):
        return {"X-Source": "scoped"}

    reg = Registry(
        SelectionConfig("a", {}, True),
        [PatchSpec("a", "_target", "build_headers", impl)],
    )
    assert reg.apply("_target:build_headers") is True

    spec = PatchSpec("b", "_target", "build_headers", scoped_impl)
    with pytest.raises(ValueError, match="冲突"):
        with scoped_patch("_target", "build_headers", spec):
            pass

    reg.revert("_target:build_headers")


def test_scoped_releases_claim_on_exit():
    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl)
    target = "_target:greet"
    assert target not in claims_snapshot()
    with scoped_patch("_target", "greet", spec):
        assert target in claims_snapshot()
    assert target not in claims_snapshot()


def test_scoped_release_on_exception():
    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl)
    with pytest.raises(RuntimeError):
        with scoped_patch("_target", "greet", spec):
            raise RuntimeError("boom")
    assert "_target:greet" not in claims_snapshot()
    assert _target.greet("x") == "hello x"


def test_transient_releases_claim_after_call():
    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl)
    target = "_target:greet"

    @transient_patch("_target", "greet", spec)
    def call_greet():
        return _target.greet("x")

    assert target not in claims_snapshot()
    assert call_greet() == "patched-x"
    assert target not in claims_snapshot()
    assert _target.greet("x") == "hello x"


def test_transient_hash_mismatch_rejected():
    """装饰时即校验：配置错误应在装饰处暴露，而不是等到调用时。"""

    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl, expect_hash="deadbeef")

    with pytest.raises(ValueError, match="版本校验失败"):
        transient_patch("_target", "greet", spec)


def test_transient_hash_mismatch_rejected_at_call_time():
    """装饰之后目标才被改动时，调用时同样应拒绝。"""
    from funcpatch.spec import source_hash

    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl, expect_hash=source_hash(_target.greet))

    @transient_patch("_target", "greet", spec)
    def call_greet():
        return _target.greet("x")

    original = _target.greet
    try:
        _target.greet = lambda name: "changed"  # noqa: B010
        with pytest.raises(ValueError, match="版本校验失败"):
            call_greet()
    finally:
        _target.greet = original  # noqa: B010


def test_transient_reentrant_call_no_conflict():
    """递归/重入调用被 transient 装饰的函数不应误报占用冲突。"""
    from funcpatch._claims import clear_all

    def wrapper(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    spec = PatchSpec("a", "_target", "greet", wrapper, mode="wrap")
    target = "_target:greet"
    clear_all()

    from typing import Any

    reentrant: dict[str, Any] = {"fn": None}

    @transient_patch("_target", "greet", spec)
    def call_with_reentry(n):
        if n <= 0:
            return "done"
        # 通过模块属性再次调用被装饰函数，触发重入
        return reentrant["fn"](n - 1)

    reentrant["fn"] = call_with_reentry

    assert call_with_reentry(3) == "done"
    assert target not in claims_snapshot()
    assert _target.greet("x") == "hello x"
    clear_all()


def test_scoped_respects_requires_constraint():
    """部署版本约束不满足时，作用域补丁应拒绝应用。"""
    spec = PatchSpec("a", "_target", "greet", lambda name: "patched", requires=("wrapt>=999",))
    with pytest.raises(ValueError, match="版本约束不满足"):
        with scoped_patch("_target", "greet", spec):
            pass


def test_scoped_warns_on_deprecated_target():
    """废弃目标应发出告警（与持久化补丁一致）。"""
    from funcpatch import DeprecatedTargetWarning

    spec = PatchSpec("a", "_target", "greet", lambda name: "patched", deprecated="改用 greet2")
    with pytest.warns(DeprecatedTargetWarning):
        with scoped_patch("_target", "greet", spec):
            pass


def test_scoped_respects_expect_deps_hash():
    """依赖闭包校验同样适用于作用域补丁。"""
    spec = PatchSpec(
        "a", "_target", "greet", lambda name: "patched", expect_deps_hash="0000000000000000"
    )
    with pytest.raises(ValueError, match="依赖版本校验失败"):
        with scoped_patch("_target", "greet", spec):
            pass


def test_transient_respects_requires_constraint():
    """部署版本约束不满足时，临时补丁也应拒绝应用。"""
    spec = PatchSpec("a", "_target", "greet", lambda name: "patched", requires=("wrapt>=999",))
    with pytest.raises(ValueError, match="版本约束不满足"):
        transient_patch("_target", "greet", spec)
