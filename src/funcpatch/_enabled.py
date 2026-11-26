"""enabled 开关统一封装。

wrap 模式直接透传给 wrapt.FunctionWrapper（它原生支持 bool/callable）。
replace 模式没有 wrapt 包装层，用一个轻量 dispatcher 实现同等语义：
  - enabled 为 False → 调用原函数
  - enabled 为 callable → 每次调用时求值
  - enabled 为 True → 调用 replacement
"""

from __future__ import annotations

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

    @wraps(replacement)
    def dispatcher(*args: Any, **kwargs: Any) -> Any:
        if resolve_enabled(enabled):
            return replacement(*args, **kwargs)
        return original(*args, **kwargs)

    return dispatcher
