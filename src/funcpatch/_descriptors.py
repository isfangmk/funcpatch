"""描述符保真：替换类属性时保持原属性的描述符类型。

Python 的类属性有 classmethod / staticmethod / property 等描述符类型。
wrapt.apply_patch 只是裸 setattr，若直接把普通函数塞进去替换一个 classmethod，
通过类/实例访问时不会绑定 cls，语义就变了。

本模块根据原始属性类型，把 replacement 包装成相同描述符类型，保证替换后
访问语义不变。回滚由 registry 保存的原始描述符对象直接恢复。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import wrapt

PropertyPart = Literal["get", "set", "delete"]


def unwrap_descriptor(original: Any, part: PropertyPart = "get") -> Callable[..., Any] | None:
    """取描述符底层的可调用对象，供版本校验与包装使用。

    - classmethod / staticmethod → __func__
    - property → 按 part 取 fget / fset / fdel
    - 普通函数 → 原样返回
    """
    if isinstance(original, (classmethod, staticmethod)):
        return original.__func__
    if isinstance(original, property):
        if part == "set":
            return original.fset
        if part == "delete":
            return original.fdel
        return original.fget
    return original if callable(original) else None


def preserve_descriptor(
    original: Any,
    replacement: Callable[..., Any],
    part: PropertyPart = "get",
) -> Any:
    """按 original 的描述符类型包装 replacement，返回可 setattr 的对象。"""
    if isinstance(original, classmethod):
        return classmethod(replacement)
    if isinstance(original, staticmethod):
        return staticmethod(replacement)
    if isinstance(original, property):
        # 只替换指定部分，其余 getter/setter/deleter 保持原样。
        fget, fset, fdel = original.fget, original.fset, original.fdel
        if part == "set":
            fset = replacement
        elif part == "delete":
            fdel = replacement
        else:
            fget = replacement
        return property(fget, fset, fdel, original.__doc__)
    return replacement


def wrap_with_descriptor(
    original: Any,
    wrapper: wrapt.FunctionWrapper,
    part: PropertyPart = "get",
) -> Any:
    """wrap 模式：把 wrapper 再按原描述符类型包装。"""
    return preserve_descriptor(original, wrapper, part)


def is_descriptor(original: Any) -> bool:
    return isinstance(original, (classmethod, staticmethod, property))
