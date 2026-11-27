"""装饰式补丁声明（gorilla 风格便利层）。

除了数据式 PatchSpec，也支持装饰式声明：

    @patch("client_a", "app.core.config", "Settings.build_headers")
    def my_impl(self, cookie=None):
        ...

装饰器只收集补丁（挂到函数的 __funcpatch_patches__ 属性），不应用。
应用仍需 Registry / bootstrap，保持"声明与应用分离"。

一个函数可声明多条 spec：

    @patches(
        ("client_a", "app.mod", "f1"),
        ("client_b", "app.mod", "f2"),
    )
    def impl(*args, **kwargs):
        ...
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Literal

from .spec import PatchSpec

PATCH_ATTR = "__funcpatch_patches__"

_SpecDecl = tuple[str, str, str] | PatchSpec


def _add_specs(func: Callable[..., Any], specs: Iterable[PatchSpec]) -> None:
    """把一组 spec 附加到函数上，保留已有声明。"""
    existing = getattr(func, PATCH_ATTR, None)
    if existing is None:
        setattr(func, PATCH_ATTR, list(specs))
    else:
        existing.extend(specs)


def patch(
    owner: str,
    target_module: str,
    target_attr: str,
    *,
    expect_hash: str = "",
    expect_deps_hash: str = "",
    mode: str = "replace",
    enabled: bool | Callable[[], bool] = True,
    description: str = "",
    tags: tuple[str, ...] = (),
    property_part: Literal["get", "set", "delete"] = "get",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰一个函数，声明它为一条 PatchSpec。"""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        spec = PatchSpec(
            owner=owner,
            target_module=target_module,
            target_attr=target_attr,
            replacement=func,
            expect_hash=expect_hash,
            expect_deps_hash=expect_deps_hash,
            mode=mode,
            enabled=enabled,
            description=description or func.__doc__ or "",
            tags=tags,
            property_part=property_part,
        )
        _add_specs(func, [spec])
        return func

    return decorator


def patches(
    declarations: Iterable[_SpecDecl],
    *,
    expect_hash: str = "",
    expect_deps_hash: str = "",
    mode: str = "replace",
    enabled: bool | Callable[[], bool] = True,
    tags: tuple[str, ...] = (),
    property_part: Literal["get", "set", "delete"] = "get",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """一个函数声明多条 PatchSpec。

    declarations 中每项可以是 (owner, module, attr) 三元组，
    也可以是已构造好的 PatchSpec（此时该项自己的参数优先生效）。
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        specs: list[PatchSpec] = []
        for decl in declarations:
            if isinstance(decl, PatchSpec):
                specs.append(decl)
                continue
            owner, module, attr = decl
            specs.append(
                PatchSpec(
                    owner=owner,
                    target_module=module,
                    target_attr=attr,
                    replacement=func,
                    expect_hash=expect_hash,
                    expect_deps_hash=expect_deps_hash,
                    mode=mode,
                    enabled=enabled,
                    description=func.__doc__ or "",
                    tags=tags,
                    property_part=property_part,
                )
            )
        _add_specs(func, specs)
        return func

    return decorator


def collect_patched(module_or_class: Any) -> list[PatchSpec]:
    """从模块/类的成员中收集装饰式声明的补丁。

    用 vars() 而非 getattr() 遍历，避免触发 property/descriptor 的用户代码。
    """
    specs: list[PatchSpec] = []
    members = vars(module_or_class).values()
    for obj in list(members):
        found = getattr(obj, PATCH_ATTR, None)
        if found:
            specs.extend(found)
    return specs
