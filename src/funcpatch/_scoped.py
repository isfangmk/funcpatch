"""作用域/临时补丁：透传 wrapt 的 scoped_function_wrapper / transient_function_wrapper。

两者都只在特定范围内生效，退出后自动回滚，不经过 Registry 的持久化应用：
  * scoped_patch：with 块内生效
  * transient_patch：被装饰函数调用期间生效

两者都接受 wrapt 风格的 wrapper（签名 (wrapped, instance, args, kwargs)），
即 funcpatch 的 mode="wrap" 语义。这样能正确调用原函数，避免混用两套模型。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

from ._enabled import resolve_enabled
from .spec import PatchSpec

# wrapt.patches 的内部函数部分静态检查器不解析符号，走模块引用并忽略。
scoped_function_wrapper = wrapt_patches.scoped_function_wrapper  # pyright: ignore[reportAttributeAccessIssue]
transient_function_wrapper = wrapt_patches.transient_function_wrapper  # pyright: ignore[reportAttributeAccessIssue]

WraptWrapper = Callable[[Any, Any, tuple, dict], Any]


def _wrapper_from_spec(spec: PatchSpec) -> WraptWrapper:
    """把 PatchSpec 转成 wrapt wrapper 签名。

    wrapt wrapper 签名：(wrapped, instance, args, kwargs)。
    mode="wrap" 的 replacement 已是该签名，直接使用。
    mode="replace" 的 replacement 是完整实现，包装成忽略原函数的 wrapper。
    """
    replacement = spec.replacement
    enabled = spec.enabled

    if spec.mode == "wrap":
        base = replacement
    else:

        def base(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
            if instance is None:
                return replacement(*args, **kwargs)
            return replacement(instance, *args, **kwargs)

    def wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
        if not resolve_enabled(enabled):
            return wrapped(*args, **kwargs)
        return base(wrapped, instance, args, kwargs)

    return wrapper


@contextmanager
def scoped_patch(
    target_module: str, target_attr: str, spec: PatchSpec
) -> Generator[None, None, None]:
    """with 块内应用补丁，退出自动回滚。

    用法：
        with scoped_patch("app.core.config", "Settings.build_headers", spec):
            ...  # 期间目标函数被替换
    """
    # scoped 不支持 wrapt 的 "?" 延迟语法：进入 with 时目标模块必须已导入。
    module = importlib.import_module(target_module)
    with scoped_function_wrapper(module, target_attr, _wrapper_from_spec(spec)):
        yield


def transient_patch(
    target_module: str, target_attr: str, spec: PatchSpec
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰一个函数，使其调用期间目标函数被临时替换。"""
    module = importlib.import_module(target_module)
    decorator = transient_function_wrapper(module, target_attr)
    return decorator(_wrapper_from_spec(spec))
