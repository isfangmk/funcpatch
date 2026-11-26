"""边界能力测试：异步函数、描述符（classmethod/staticmethod/property）、线程安全。

这些是成熟 patch 框架必须处理、而裸 setattr 会出错的场景。
"""

from __future__ import annotations

import inspect
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import PatchSpec, Registry, SelectionConfig  # noqa: E402


def _reg(owner: str, specs: list[PatchSpec]) -> Registry:
    return Registry(SelectionConfig(owner, {}, True), specs)


# --------------------------------------------------------------- 异步函数


@pytest.mark.asyncio
async def test_async_replace():
    """replace 替换 async 函数：替换后仍是 coroutine function 且可 await。"""

    async def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "async_greet", impl)
    reg = _reg("a", [spec])
    assert reg.apply("_target:async_greet") is True

    assert inspect.iscoroutinefunction(_target.async_greet)
    assert await _target.async_greet("x") == "patched-x"

    reg.revert("_target:async_greet")
    assert await _target.async_greet("x") == "async hello x"


@pytest.mark.asyncio
async def test_async_wrap():
    """wrap 模式包装 async 函数：wrapper 可 await 原函数。"""

    async def wrapper(original, instance, args, kwargs):
        r = await original(*args, **kwargs)
        return r.upper()

    spec = PatchSpec("a", "_target", "async_greet", wrapper, mode="wrap")
    reg = _reg("a", [spec])
    assert reg.apply("_target:async_greet") is True

    assert inspect.iscoroutinefunction(_target.async_greet)
    assert await _target.async_greet("x") == "ASYNC HELLO X"

    reg.revert("_target:async_greet")
    assert await _target.async_greet("x") == "async hello x"


# --------------------------------------------------------------- 描述符


def test_classmethod_replace():
    """classmethod 替换保留描述符语义，通过类访问仍自动绑定 cls。"""

    def impl(cls):
        return f"patched-{cls.__name__}"

    spec = PatchSpec("a", "_target", "Descriptors.who", impl)
    reg = _reg("a", [spec])
    assert reg.apply("_target:Descriptors.who") is True

    assert _target.Descriptors.who() == "patched-Descriptors"
    reg.revert("_target:Descriptors.who")
    assert _target.Descriptors.who() == "class-Descriptors"


def test_staticmethod_replace():
    def impl():
        return "static-patched"

    spec = PatchSpec("a", "_target", "Descriptors.static", impl)
    reg = _reg("a", [spec])
    assert reg.apply("_target:Descriptors.static") is True
    assert _target.Descriptors.static() == "static-patched"
    reg.revert("_target:Descriptors.static")
    assert _target.Descriptors.static() == "static-original"


def test_property_replace():
    def impl(self):
        return "prop-patched"

    spec = PatchSpec("a", "_target", "Descriptors.prop", impl)
    reg = _reg("a", [spec])
    assert reg.apply("_target:Descriptors.prop") is True
    assert _target.Descriptors().prop == "prop-patched"
    reg.revert("_target:Descriptors.prop")
    assert _target.Descriptors().prop == "prop-original"


# --------------------------------------------------------------- 线程安全


def test_concurrent_apply_idempotent():
    """并发 apply 同一目标：只有一个成功应用，其余幂等返回。"""
    calls = []

    def greet_impl(name):
        calls.append(1)
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", greet_impl)
    reg = _reg("a", [spec])

    results = []

    def worker():
        results.append(reg.apply("_target:greet"))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(results)  # 全部返回 True（幂等）
    assert len(calls) == 0  # 没有真的调用，只验证 apply 幂等
    assert reg.is_applied("_target:greet")
    reg.revert("_target:greet")
    assert _target.greet("x") == "hello x"
