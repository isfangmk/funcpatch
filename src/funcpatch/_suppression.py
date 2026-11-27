"""上下文局部抑制：在当前上下文临时关闭所有（或指定）补丁。

借鉴 OpenTelemetry instrumentation 的 suppress_instrumentation：
补丁内部复用被 patch 的原函数、或在某个请求里临时旁路定制逻辑时，
避免递归和“补丁调用补丁”造成的状态污染。基于 ContextVar，异步任务安全。
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_suppressed: ContextVar[bool] = ContextVar("funcpatch_suppressed", default=False)


def is_suppressed() -> bool:
    """当前上下文是否处于补丁抑制状态。"""
    return _suppressed.get()


@contextmanager
def suppress_patches() -> Generator[None, None, None]:
    """进入上下文期间关闭补丁（嵌套安全，退出恢复原状态）。"""
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


def wrap_enabled(enabled: bool | Any) -> Any:
    """把 PatchSpec.enabled 与抑制状态组合：被抑制时一律返回 False。

    供 make_dispatcher / scoped wrapper 复用，保持与现有 bool/callable 语义兼容。
    """
    from ._enabled import resolve_enabled

    def combined() -> bool:
        if _suppressed.get():
            return False
        return resolve_enabled(enabled)

    return combined
