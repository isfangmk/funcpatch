"""描述符安全的属性工具（借鉴 gorilla 的 get_attribute / _get_base / _get_members）。

问题：直接 ``getattr(cls, name)`` 会触发描述符协议 —— classmethod 变成绑定方法、
property 返回计算结果而不是属性对象。funcpatch 需要拿到底层原始对象。

这里用 ``object.__getattribute__`` 沿 MRO 查找，绕过描述符协议和自定义
``__getattribute__``，拿到的是类字典里物理存放的原始对象。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def get_attribute(obj: Any, name: str) -> Any:
    """描述符安全地取属性：沿 MRO 用 object.__getattribute__ 查找。

    对类返回类字典里的原始对象（不是绑定方法/property 计算结果）；
    对实例/模块退化为普通 getattr 语义。
    """
    if isinstance(obj, type):
        for candidate in inspect.getmro(obj):
            try:
                return object.__getattribute__(candidate, name)
            except AttributeError:
                continue
        raise AttributeError(f"type object {obj.__name__!r} has no attribute {name!r}")
    return getattr(obj, name)


def get_base(obj: Any) -> Any:
    """递归解包到最底层的可调用对象。

    解开 bound method 的 __func__、classmethod/staticmethod 的 __func__、
    property 的 fget，直到不可再解包。用于诊断/装饰式声明定位真实函数。
    """
    seen: set[int] = set()
    current = obj
    while id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (classmethod, staticmethod)):
            current = current.__func__
        elif isinstance(current, property):
            if current.fget is None:
                break
            current = current.fget
        elif hasattr(current, "__func__"):
            # bound method 等对象的底层函数
            current = current.__func__  # pyright: ignore[reportAny, reportFunctionMemberAccess]
        else:
            break
    return current


def get_members(
    obj: Any,
    *,
    traverse_bases: bool = True,
    filter_fn: Callable[[str, Any], bool] | None = None,
) -> list[tuple[str, Any]]:
    """枚举类/模块的成员，MRO 顺序去重、按名字排序（借鉴 gorilla._get_members）。

    - 用 ``__dict__`` 直接读取，不触发描述符；
    - traverse_bases=True 时沿 MRO 查找，派生类覆盖基类同名成员；
    - filter_fn(name, value) 返回 False 的成员被排除。
    """
    objects: list[Any] = []
    if traverse_bases and isinstance(obj, type):
        objects = [base for base in inspect.getmro(obj) if base not in (type, object)]
    else:
        objects = [obj]

    seen: set[str] = set()
    members: dict[str, Any] = {}
    for target in objects:
        for name, value in vars(target).items():
            if name in seen:
                continue
            if filter_fn is not None and not filter_fn(name, value):
                seen.add(name)
                continue
            seen.add(name)
            members[name] = value

    return sorted(members.items())


def default_filter(name: str, obj: Any) -> bool:
    """默认成员过滤：排除模块与下划线开头的名字（gorilla.default_filter 语义）。"""
    return not (inspect.ismodule(obj) or name.startswith("_"))
