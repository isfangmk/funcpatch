"""上下文局部抑制：wrap/replace 旁路、嵌套与异步任务隔离。"""

from __future__ import annotations

import asyncio
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
    is_suppressed,
    scoped_patch,
    suppress_patches,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_suppress_bypasses_wrap_patch():
    def wrapper(wrapped, instance, args, kwargs):
        return f"patched-{args[0]}"

    reg = _reg([PatchSpec("a", "_target", "greet", wrapper, mode="wrap")])
    assert reg.apply("_target:greet") is True
    try:
        assert _target.greet("x") == "patched-x"
        with suppress_patches():
            assert _target.greet("x") == "hello x"
        assert _target.greet("x") == "patched-x"
    finally:
        reg.revert("_target:greet")
        clear_all()


@pytest.mark.asyncio
async def test_suppression_isolated_between_async_tasks():
    def impl(name):
        return f"patched-{name}"

    reg = _reg([PatchSpec("a", "_target", "greet", impl)])
    assert reg.apply("_target:greet") is True
    release = asyncio.Event()

    async def suppressed_task():
        with suppress_patches():
            release.set()
            await asyncio.sleep(0.05)
            return _target.greet("a")

    async def normal_task():
        await release.wait()
        return _target.greet("b")

    try:
        a, b = await asyncio.gather(suppressed_task(), normal_task())
        assert a == "hello a"  # A 被抑制
        assert b == "patched-b"  # B 不受影响
    finally:
        reg.revert("_target:greet")
        clear_all()


@pytest.mark.asyncio
async def test_suppress_patches_bypasses_patch():
    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl)
    reg = _reg([spec])
    assert reg.apply("_target:greet") is True
    try:
        assert _target.greet("x") == "patched-x"
        assert is_suppressed() is False
        with suppress_patches():
            assert is_suppressed() is True
            assert _target.greet("x") == "hello x"
        assert is_suppressed() is False
        assert _target.greet("x") == "patched-x"
    finally:
        reg.revert("_target:greet")
        clear_all()


def test_suppress_nested():
    assert is_suppressed() is False
    with suppress_patches():
        with suppress_patches():
            assert is_suppressed() is True
        assert is_suppressed() is True
    assert is_suppressed() is False


def test_suppress_bypasses_scoped_patch():
    """作用域补丁同样受上下文抑制控制。"""
    clear_all()

    def impl(name):
        return f"scoped-{name}"

    spec = PatchSpec("a", "_target", "greet", impl)
    with scoped_patch("_target", "greet", spec):
        assert _target.greet("x") == "scoped-x"
        with suppress_patches():
            assert _target.greet("x") == "hello x"
        assert _target.greet("x") == "scoped-x"
    assert _target.greet("x") == "hello x"
    clear_all()
