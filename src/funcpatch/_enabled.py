"""enabled 开关统一封装。

wrap 模式直接透传给 wrapt.FunctionWrapper（它原生支持 bool/callable）。
replace 模式没有 wrapt 包装层，用一个轻量 dispatcher 实现同等语义：
  - enabled 为 False → 调用原函数
  - enabled 为 callable → 每次调用时求值
  - enabled 为 True → 调用 replacement

dispatcher 会感知目标的调用约定，保证在启用/禁用切换后仍保持正确的函数身份：
  * 普通函数 → def
  * coroutine function（async def） → async def，内部 await
  * async generator function → async def + yield（async for 逐项转发）

这三类身份对 introspection 框架（FastAPI 依赖注入、inspect 等）至关重要。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any

Enabled = bool | Callable[[], bool]


def resolve_enabled(enabled: Enabled) -> bool:
    if callable(enabled):
        return bool(enabled())
    return bool(enabled)


def make_dispatcher(
    replacement: Callable[..., Any], original: Callable[..., Any], enabled: Enabled
) -> Callable[..., Any]:
    """为 replace 模式生成一个带 enabled 语义的替代函数。"""
    is_asyncgen = inspect.isasyncgenfunction(replacement) or inspect.isasyncgenfunction(original)
    if is_asyncgen:
        # async 生成器不能被 await，必须 async for 逐项转发。
        # replacement 与 original 调用约定可能不同（一方是协程、一方是异步生成器），
        # 按实际返回值分别处理，避免对协程对象做 async for。
        @wraps(replacement)
        async def asyncgen_dispatcher(*args: Any, **kwargs: Any) -> Any:
            source = replacement if resolve_enabled(enabled) else original
            result = source(*args, **kwargs)
            if inspect.isawaitable(result):
                yield await result
            else:
                async for item in result:
                    yield item

        return asyncgen_dispatcher

    is_coroutine = inspect.iscoroutinefunction(replacement) or inspect.iscoroutinefunction(original)
    if is_coroutine:

        @wraps(replacement)
        async def async_dispatcher(*args: Any, **kwargs: Any) -> Any:
            if resolve_enabled(enabled):
                return await replacement(*args, **kwargs)
            return await original(*args, **kwargs)

        return async_dispatcher

    @wraps(replacement)
    def dispatcher(*args: Any, **kwargs: Any) -> Any:
        if resolve_enabled(enabled):
            return replacement(*args, **kwargs)
        return original(*args, **kwargs)

    return dispatcher
