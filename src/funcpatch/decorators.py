"""装饰式补丁声明（gorilla 风格便利层）。

除了数据式 PatchSpec，也支持装饰式声明：

    @patch("client_a", "app.core.config", "Settings.build_headers")
    def my_impl(self, cookie=None):
        ...

装饰器只收集补丁（挂到函数的 __funcpatch_patches__ 属性），不应用。
应用仍需 Registry / bootstrap，保持"声明与应用分离"。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .spec import PatchSpec

PATCH_ATTR = "__funcpatch_patches__"


def patch(
    owner: str,
    target_module: str,
    target_attr: str,
    *,
    expect_hash: str = "",
    mode: str = "replace",
    enabled: bool | Callable[[], bool] = True,
    description: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰一个函数，声明它为一条 PatchSpec。"""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        spec = PatchSpec(
            owner=owner,
            target_module=target_module,
            target_attr=target_attr,
            replacement=func,
            expect_hash=expect_hash,
            mode=mode,
            enabled=enabled,
            description=description or func.__doc__ or "",
        )
        existing = getattr(func, PATCH_ATTR, None)
        if existing is None:
            setattr(func, PATCH_ATTR, [spec])
        else:
            existing.append(spec)
        return func

    return decorator


def collect_patched(module_or_class: Any) -> list[PatchSpec]:
    """从模块/类的成员中收集装饰式声明的补丁。"""
    specs: list[PatchSpec] = []
    for name in dir(module_or_class):
        try:
            obj = getattr(module_or_class, name)
        except AttributeError:
            continue
        found = getattr(obj, PATCH_ATTR, None)
        if found:
            specs.extend(found)
    return specs
