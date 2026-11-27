"""诊断 API：判断函数是否被 funcpatch 改过、取包装器、回滚。

wrapt 用 __wrapped__ 链 + handle 身份匹配（见 wrapt.patches），
本模块把这些能力以"目标字符串"为入口暴露给 funcpatch 用户。
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

from ._descriptors import PropertyPart, unwrap_descriptor

if TYPE_CHECKING:
    from .registry import Registry

find_wrapper = wrapt_patches.find_wrapper  # pyright: ignore[reportAttributeAccessIssue]
is_wrapped_by = wrapt_patches.is_wrapped_by  # pyright: ignore[reportAttributeAccessIssue]
unwrap_object = wrapt_patches.unwrap_object  # pyright: ignore[reportAttributeAccessIssue]
resolve_path = wrapt_patches.resolve_path  # pyright: ignore[reportAttributeAccessIssue]

# replace 模式的标记：安装时给 replacement 打上该属性
PATCH_MARK = "__funcpatch_replacement__"


def mark_replacement(func: Any, owner: str, target: str) -> Any:
    """给替代函数打标记，供诊断识别。

    对 wrapt 代理必须用 __self_setattr__：普通 setattr 会被代理转发到
    __wrapped__（见 wrapt.wrappers.ObjectProxy.__setattr__），导致标记
    泄露到原函数上、revert 后残留误报。

    同一个 replacement 可用于多个目标（@patches / create_patches），
    因此用 targets 列表累积所有目标：target 字段保留首个，兼容旧读取方。
    """
    existing = getattr(func, PATCH_MARK, None)
    if isinstance(existing, dict) and "targets" in existing:
        if target not in existing["targets"]:
            existing["targets"].append(target)
        return func
    marker = {"owner": owner, "target": target, "targets": [target]}
    self_setattr = getattr(func, "__self_setattr__", None)
    if self_setattr is not None:
        self_setattr(PATCH_MARK, marker)
    else:
        try:
            setattr(func, PATCH_MARK, marker)
        except (AttributeError, TypeError):
            pass
    return func


def is_patched(target: str, registry: Registry | None = None) -> bool:
    """目标是否已被 funcpatch 应用补丁。

    优先查 registry 状态；registry 不可用时，检查函数上的 PATCH_MARK
    或 wrapt 包装链中是否含 funcpatch 标记。
    """
    if registry is not None:
        # 有 registry 时以它为单一真相源，不查可能残留的函数标记
        return registry.is_applied(target)
    func = _resolve_func(target)
    if func is None:
        return False
    if getattr(func, PATCH_MARK, None) is not None:
        return True
    return is_wrapped_by(func, predicate=lambda f: getattr(f, PATCH_MARK, None) is not None)


def get_applied_info(target: str) -> dict | None:
    """返回补丁标记信息（owner/target），未打补丁返回 None。"""
    func = _resolve_func(target)
    if func is None:
        return None
    marker = getattr(func, PATCH_MARK, None)
    if not isinstance(marker, dict):
        return None
    result = dict(marker)
    # 共享 replacement 时 marker.target 是首个目标；按查询目标校准。
    if isinstance(result.get("targets"), list) and target in result["targets"]:
        result["target"] = target
    return result


def get_wrapper(target: str) -> Any | None:
    """返回目标当前的可调用对象（可能是 wrapt 包装器）。

    与 Registry.get_wrapper 不同，此函数不依赖 registry 实例，
    适合在诊断脚本里直接按目标字符串查询。
    """
    return _resolve_func(target)


def unwrap(target: str) -> Any | None:
    """拆掉目标上的 funcpatch 包装，返回原始函数；没有包装返回 None。

    仅处理 funcpatch 自己打的包装链（按 PATCH_MARK 身份定位 handle），
    不触碰第三方包装器。
    """
    func = _resolve_func(target)
    if func is None:
        return None
    module, _sep, attr_path = target.partition(":")
    try:
        module_obj = __import__(module, fromlist=["*"])
        parent, attr, _current = resolve_path(module_obj, attr_path)
    except Exception:
        return None
    try:
        return unwrap_object(parent, attr, func, missing_ok=True)
    except Exception:
        return None


def is_marked(target: str, property_part: PropertyPart = "get") -> bool:
    """目标当前属性上是否仍带 funcpatch 标记（不依赖 registry 状态）。

    与 is_patched(target) 的区别：后者在传入 registry 时以 registry 为准，
    这里只看函数上的实际标记，因此能反映"补丁是否仍然真的生效"。
    目标模块被 reload 后，旧补丁失效，标记随之消失，这里即返回 False。

    property_part 指定要检查的部分（get / set / delete）。property 的各部分
    可以被不同 owner 独立打补丁，检查某一 part 时不应被其它 part 的标记
    干扰。
    """
    func = _resolve_func(target, property_part)
    if func is None:
        return False
    if getattr(func, PATCH_MARK, None) is not None:
        return True
    return is_wrapped_by(func, predicate=lambda f: getattr(f, PATCH_MARK, None) is not None)


def _resolve_func(target: str, property_part: PropertyPart = "get") -> Any | None:
    """按目标字符串解析出可调用对象，描述符感知。

    property → fget/fset/fdel（按 property_part）；classmethod/staticmethod → __func__；
    普通函数原样。这样标记无论打在 replacement 还是描述符底层函数上都能被发现。
    """
    module, _sep, attr_path = target.partition(":")
    try:
        obj = __import__(module, fromlist=["*"])
        parts = attr_path.split(".")
        for part in parts[:-1]:
            # 逐级用 getattr_static，避免触发任意描述符的用户代码
            obj = inspect.getattr_static(obj, part)
        attr = parts[-1]
        # 关键：用 getattr_static 而非 getattr，property 不会执行 getter
        # （getter 可能有副作用或抛异常，诊断必须是只读的）。
        current = inspect.getattr_static(obj, attr)
        # 先看指定的部分是否带标记；再看其它部分（标记可能打在包装链上）。
        raw = unwrap_descriptor(current, property_part)  # type: ignore[arg-type]
        if raw is not None and getattr(raw, PATCH_MARK, None) is not None:
            return raw
        for part in ("get", "set", "delete"):
            raw = unwrap_descriptor(current, part)  # type: ignore[arg-type]
            if raw is not None and getattr(raw, PATCH_MARK, None) is not None:
                return raw
        return (
            unwrap_descriptor(current, property_part)
            or unwrap_descriptor(current, "get")
            or current
        )
    except (ImportError, AttributeError, TypeError):
        return None
