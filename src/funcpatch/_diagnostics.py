"""诊断 API：判断函数是否被 funcpatch 改过、取包装器、回滚。

wrapt 用 __wrapped__ 链 + handle 身份匹配（见 wrapt.patches），
本模块把这些能力以"目标字符串"为入口暴露给 funcpatch 用户。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from .registry import Registry

find_wrapper = wrapt_patches.find_wrapper  # pyright: ignore[reportAttributeAccessIssue]
is_wrapped_by = wrapt_patches.is_wrapped_by  # pyright: ignore[reportAttributeAccessIssue]

# replace 模式的标记：安装时给 replacement 打上该属性
PATCH_MARK = "__funcpatch_replacement__"


def mark_replacement(func: Any, owner: str, target: str) -> Any:
    """给替代函数打标记，供诊断识别。

    对 wrapt 代理必须用 __self_setattr__：普通 setattr 会被代理转发到
    __wrapped__（见 wrapt.wrappers.ObjectProxy.__setattr__），导致标记
    泄露到原函数上、revert 后残留误报。
    """
    marker = {"owner": owner, "target": target}
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
    return getattr(func, PATCH_MARK, None)


def _resolve_func(target: str) -> Any:
    module, _sep, attr_path = target.partition(":")
    try:
        obj = __import__(module, fromlist=["*"])
        for part in attr_path.split("."):
            obj = getattr(obj, part)
        return obj
    except (ImportError, AttributeError):
        return None
