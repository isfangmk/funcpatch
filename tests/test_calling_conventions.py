"""函数类型身份保持与 property setter/deleter wrap 模式测试。"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import PatchSpec, Registry, SelectionConfig  # noqa: E402


def _reg(specs: list[PatchSpec]) -> Registry:
    return Registry(SelectionConfig("a", {}, True), specs)


async def _collect(fn, *args):
    out = []
    async for item in fn(*args):
        out.append(item)
    return out


# ------------------------------------------------------------------ 调用约定身份


@pytest.mark.asyncio
async def test_async_generator_replace_keeps_identity():
    async def impl(count):
        for i in range(count):
            yield i + 100

    reg = _reg([PatchSpec("a", "_target", "async_numbers", impl)])
    assert reg.apply("_target:async_numbers") is True
    assert inspect.isasyncgenfunction(_target.async_numbers)
    assert await _collect(_target.async_numbers, 3) == [100, 101, 102]
    reg.revert("_target:async_numbers")
    assert await _collect(_target.async_numbers, 3) == [0, 1, 2]


@pytest.mark.asyncio
async def test_coroutine_replacement_on_async_generator_target():
    """协程 replacement 作用于异步生成器目标时，结果作为单元素产出，不抛 TypeError。"""
    state = {"on": True}

    async def impl(count):
        return 99

    spec = PatchSpec("a", "_target", "async_numbers", impl, enabled=lambda: state["on"])
    reg = _reg([spec])
    assert reg.apply("_target:async_numbers") is True
    try:
        assert inspect.isasyncgenfunction(_target.async_numbers)
        assert await _collect(_target.async_numbers, 3) == [99]
        state["on"] = False
        assert await _collect(_target.async_numbers, 3) == [0, 1, 2]
    finally:
        reg.revert_all()


@pytest.mark.asyncio
async def test_async_generator_enabled_keeps_identity():
    """enabled 动态开关下 async generator 保持协程身份。"""
    state = {"on": True}

    async def impl(count):
        for i in range(count):
            yield i + 100

    spec = PatchSpec("a", "_target", "async_numbers", impl, enabled=lambda: state["on"])
    reg = _reg([spec])
    assert reg.apply("_target:async_numbers") is True
    assert inspect.isasyncgenfunction(_target.async_numbers)

    assert await _collect(_target.async_numbers, 2) == [100, 101]
    state["on"] = False
    assert await _collect(_target.async_numbers, 2) == [0, 1]
    reg.revert("_target:async_numbers")


@pytest.mark.asyncio
async def test_async_generator_wrap_keeps_identity():
    async def wrapper(original, instance, args, kwargs):
        async for item in original(*args, **kwargs):
            yield item * 10

    reg = _reg([PatchSpec("a", "_target", "async_numbers", wrapper, mode="wrap")])
    assert reg.apply("_target:async_numbers") is True
    assert inspect.isasyncgenfunction(_target.async_numbers)
    assert await _collect(_target.async_numbers, 3) == [0, 10, 20]
    reg.revert("_target:async_numbers")


@pytest.mark.asyncio
async def test_coroutine_enabled_keeps_identity():
    async def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "async_greet", impl, enabled=lambda: True)
    reg = _reg([spec])
    assert reg.apply("_target:async_greet") is True
    assert inspect.iscoroutinefunction(_target.async_greet)
    assert await _target.async_greet("x") == "patched-x"
    reg.revert("_target:async_greet")


# ------------------------------------------------------------------ property set/del wrap


def test_wrap_property_setter():
    """wrap 模式替换 setter，getter 不受影响，且可回滚。"""

    def wrapper(original, instance, args, kwargs):
        # property setter 经 wrapt 绑定后 instance 可能为 None，self 在 args[0]
        obj = instance if instance is not None else args[0]
        result = original(*args, **kwargs)
        obj._value = f"wrapped:{obj._value}"
        return result

    spec = PatchSpec("a", "_target", "Mutable.value", wrapper, mode="wrap", property_part="set")
    reg = _reg([spec])
    assert reg.apply("_target:Mutable.value") is True

    obj = _target.Mutable()
    obj.value = "x"
    assert obj.value == "wrapped:x"
    assert reg.revert("_target:Mutable.value") is True

    obj2 = _target.Mutable()
    obj2.value = "y"
    assert obj2.value == "y"


def test_wrap_property_getter_and_setter_coexist():
    """分别替换 getter 与 setter，互不干扰。"""

    def get_wrapper(original, instance, args, kwargs):
        return original(*args, **kwargs) + "-G"

    get_spec = PatchSpec("a", "_target", "Mutable.value", get_wrapper, mode="wrap")
    reg1 = _reg([get_spec])
    assert reg1.apply("_target:Mutable.value") is True
    assert _target.Mutable().value == "original-G"

    # 回滚 getter 后再替换 setter，确保两条链路独立
    assert reg1.revert("_target:Mutable.value") is True

    def set_wrapper(original, instance, args, kwargs):
        obj = instance if instance is not None else args[0]
        original(*args, **kwargs)
        obj._value = "S:" + obj._value

    set_spec = PatchSpec(
        "a", "_target", "Mutable.value", set_wrapper, mode="wrap", property_part="set"
    )
    reg2 = _reg([set_spec])
    assert reg2.apply("_target:Mutable.value") is True
    obj = _target.Mutable()
    obj.value = "z"
    assert obj.value == "S:z"
    reg2.revert("_target:Mutable.value")
