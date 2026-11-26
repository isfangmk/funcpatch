"""透传 wrapt 能力的测试：enabled 开关、诊断、作用域/临时补丁、装饰式声明。"""

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
    collect_patched,
    get_applied_info,
    is_patched,
    patch,
    scoped_patch,
    transient_patch,
)


def _reg(owner: str, specs: list[PatchSpec]) -> Registry:
    return Registry(SelectionConfig(owner, {}, True), specs)


@pytest.fixture(autouse=True)
def restore():
    original = _target.build_headers
    original_greet = _target.greet
    yield
    _target.build_headers = original
    _target.greet = original_greet


# --------------------------------------------------------------- enabled


def test_enabled_false_uses_original():
    def impl(cookie=None):
        return {"X": "patched"}

    spec = PatchSpec("a", "_target", "build_headers", impl, enabled=False)
    reg = _reg("a", [spec])
    reg.apply("_target:build_headers")
    assert _target.build_headers()["X-Source"] == "original"
    reg.revert("_target:build_headers")


def test_enabled_callable_toggles():
    state = {"on": False}

    def impl(cookie=None):
        return {"X": "patched"}

    spec = PatchSpec("a", "_target", "build_headers", impl, enabled=lambda: state["on"])
    reg = _reg("a", [spec])
    reg.apply("_target:build_headers")

    assert _target.build_headers()["X-Source"] == "original"
    state["on"] = True
    assert _target.build_headers() == {"X": "patched"}
    state["on"] = False
    assert _target.build_headers()["X-Source"] == "original"
    reg.revert("_target:build_headers")


def test_enabled_wrap_mode():
    def wrapper(wrapped, instance, args, kwargs):
        return {"X": "wrapped"}

    spec = PatchSpec("a", "_target", "build_headers", wrapper, mode="wrap", enabled=False)
    reg = _reg("a", [spec])
    reg.apply("_target:build_headers")
    assert _target.build_headers()["X-Source"] == "original"
    reg.revert("_target:build_headers")


# --------------------------------------------------------------- 诊断 API


def test_is_patched_and_info():
    def impl(cookie=None):
        return {"X": "patched"}

    spec = PatchSpec("a", "_target", "build_headers", impl)
    reg = _reg("a", [spec])
    assert is_patched("_target:build_headers") is False

    reg.apply("_target:build_headers")
    assert is_patched("_target:build_headers", reg) is True
    info = get_applied_info("_target:build_headers")
    assert info is not None and info["owner"] == "a"

    reg.revert("_target:build_headers")
    assert is_patched("_target:build_headers", reg) is False


# --------------------------------------------------------------- scoped / transient


def test_scoped_patch():
    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl)
    assert _target.greet("x") == "hello x"

    with scoped_patch("_target", "greet", spec):
        assert _target.greet("x") == "patched-x"

    assert _target.greet("x") == "hello x"  # 退出自动回滚


def test_transient_patch():
    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl)

    @transient_patch("_target", "greet", spec)
    def call_greet():
        return _target.greet("x")

    assert _target.greet("x") == "hello x"
    assert call_greet() == "patched-x"  # 调用期间临时生效
    assert _target.greet("x") == "hello x"  # 调用后恢复


# --------------------------------------------------------------- 装饰式声明


def test_decorator_style_patch():
    @patch("a", "_target", "greet")
    def impl(name):
        return f"decorated-{name}"

    specs = impl.__funcpatch_patches__  # pyright: ignore[reportFunctionMemberAccess]
    assert len(specs) == 1
    assert specs[0].owner == "a"
    assert specs[0].target == "_target:greet"


def test_collect_patched_from_module():
    import types

    mod = types.ModuleType("fake_patches")

    @patch("b", "_target", "greet")
    def impl(name):
        return name

    mod.impl = impl  # pyright: ignore[reportAttributeAccessIssue]
    specs = collect_patched(mod)
    assert any(s.owner == "b" for s in specs)
