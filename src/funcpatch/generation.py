"""批量补丁生成（借鉴 gorilla.create_patches）。

场景：一个 owner 要替换某个类的所有公开方法，手写 N 条 PatchSpec 很繁琐。
create_patches 按成员自动生成，支持 MRO 遍历、filter 过滤、嵌套类递归，
并保留 funcpatch 的 owner / expect_hash / mode 等语义。
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from .introspection import default_filter, get_attribute, get_base, get_members
from .spec import PatchSpec


def create_patches(
    owner: str,
    target_module: str,
    root: Any,
    *,
    target_prefix: str = "",
    replacement: Callable[..., Any] | None = None,
    filter_fn: Callable[[str, Any], bool] | None = default_filter,
    traverse_bases: bool = True,
    recursive: bool = False,
    expect_hash: str = "",
    expect_deps_hash: str = "",
    mode: str = "replace",
    description: str = "",
    tags: tuple[str, ...] = (),
) -> list[PatchSpec]:
    """为目标类/模块的成员批量生成 PatchSpec。

    replacement 为 None 时，用成员原始对象作为 replacement（即"原样保留"，
    通常配合后续 filter 使用）；提供一个函数时，所有成员共用该函数作为实现，
    适配函数需自行处理 instance / args。

    filter_fn(name, member) 返回 False 的成员被跳过；None 表示不过滤。
    target_prefix 为根对象在模块中的属性路径（如 ``"Descriptors"``），
    生成的目标为 ``prefix.member``；缺省为空表示根对象本身就是模块。
    recursive=True 时递归进入嵌套类（目标属性路径用点号连接）。
    """
    specs: list[PatchSpec] = []
    seen: set[int] = set()

    def walk(obj: Any, prefix: str) -> None:
        if id(obj) in seen:
            return
        seen.add(id(obj))
        for name, member in get_members(obj, traverse_bases=traverse_bases, filter_fn=filter_fn):
            attr_path = f"{prefix}.{name}" if prefix else name
            impl = replacement if replacement is not None else get_base(member)
            if impl is None or not callable(impl):
                continue
            specs.append(
                PatchSpec(
                    owner=owner,
                    target_module=target_module,
                    target_attr=attr_path,
                    replacement=copy.copy(impl),
                    expect_hash=expect_hash,
                    expect_deps_hash=expect_deps_hash,
                    mode=mode,
                    description=description,
                    tags=tags,
                )
            )
            if recursive and isinstance(member, type):
                # 递归进入嵌套类：目标路径追加类名
                walk(member, attr_path)

    walk(root, target_prefix)
    return specs


def find_patches(module: Any, *, recursive: bool = True) -> list[PatchSpec]:
    """从模块中找出所有通过 @patch / @patches 声明的补丁（gorilla.find_patches 语义）。

    与 collect_patched 不同，这里按模块成员遍历并用 get_base 解包描述符，
    能发现挂在 classmethod / staticmethod 底层函数上的声明。
    """
    from .decorators import PATCH_ATTR

    found: list[PatchSpec] = []
    seen: set[int] = set()  # 已扫描的对象（模块/类），避免循环引用
    seen_bases: set[int] = set()  # 已处理的函数 base，避免重复收集声明

    def scan(obj: Any) -> None:
        if id(obj) in seen:
            return
        seen.add(id(obj))
        for _name, member in get_members(obj, filter_fn=None):
            base = get_base(member)
            if base is not None and id(base) not in seen_bases:
                declared = getattr(base, PATCH_ATTR, None)
                if declared:
                    found.extend(declared)
                seen_bases.add(id(base))
            if recursive and isinstance(member, type):
                scan(member)

    scan(module)
    return found


def get_original_attribute(obj: Any, name: str) -> Any:
    """描述符安全地取原始属性（gorilla.get_attribute 语义）。"""
    return get_attribute(obj, name)
