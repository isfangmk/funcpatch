"""描述符保真：替换类属性时保持原属性的描述符类型。

Python 的类属性有 classmethod / staticmethod / property 等描述符类型。
wrapt.apply_patch 只是裸 setattr，若直接把普通函数塞进去替换一个 classmethod，
通过类/实例访问时不会绑定 cls，语义就变了。

本模块根据原始属性类型，把 replacement 包装成相同描述符类型，保证替换后
访问语义不变。回滚由 registry 保存的原始描述符对象直接恢复。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import wrapt


def preserve_descriptor(original: Any, replacement: Callable[..., Any]) -> Any:
    """按 original 的描述符类型包装 replacement，返回可 setattr 的对象。"""
    if isinstance(original, classmethod):
        return classmethod(replacement)
    if isinstance(original, staticmethod):
        return staticmethod(replacement)
    if isinstance(original, property):
        # property 的 getter/setter/deleter 都用同一个 replacement 替换（调用方按需再细分）
        return property(replacement)
    return replacement


def wrap_with_descriptor(original: Any, wrapper: wrapt.FunctionWrapper) -> Any:
    """wrap 模式：把 wrapper 再按原描述符类型包装。"""
    if isinstance(original, classmethod):
        return classmethod(wrapper)
    if isinstance(original, staticmethod):
        return staticmethod(wrapper)
    if isinstance(original, property):
        return property(wrapper)
    return wrapper


def is_descriptor(original: Any) -> bool:
    return isinstance(original, (classmethod, staticmethod, property))
