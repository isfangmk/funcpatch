"""补丁发现：目录扫描 + entry point 双支持。

开发期：把补丁写在 funcpatch/patches/ 目录，自动扫描发现。
生产期：每个 owner 做成独立 pip 包，声明 entry point 组 "funcpatch.patches"。
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import pkgutil
from collections.abc import Callable
from types import ModuleType

from .decorators import collect_patched
from .spec import PatchSpec

logger = logging.getLogger("funcpatch.discovery")

ENTRY_POINT_GROUP = "funcpatch.patches"


def _collect_specs(module: ModuleType) -> list[PatchSpec]:
    """从模块中收集所有 PatchSpec：数据式实例 + 装饰式声明。"""
    specs: list[PatchSpec] = []
    for _name, obj in vars(module).items():
        if isinstance(obj, PatchSpec):
            specs.append(obj)
    # 装饰式 @patch 声明
    specs.extend(collect_patched(module))
    return specs


def discover_from_directory(
    package: str = "funcpatch.patches",
    filter_fn: Callable[[PatchSpec], bool] | None = None,
) -> list[PatchSpec]:
    """扫描包目录下所有模块，收集 PatchSpec。"""
    specs: list[PatchSpec] = []
    try:
        pkg = importlib.import_module(package)
    except ImportError as exc:
        logger.debug("目录扫描包 %s 不存在：%s", package, exc)
        return specs

    # 先收集包 __init__.py 自身定义的补丁
    specs.extend(_collect_specs(pkg))

    for info in pkgutil.iter_modules(pkg.__path__):
        try:
            module = importlib.import_module(f"{package}.{info.name}")
        except Exception as exc:
            logger.warning("加载补丁模块 %s 失败：%s", info.name, exc)
            continue
        found = _collect_specs(module)
        if found:
            logger.debug("目录扫描发现 %d 条补丁：%s", len(found), info.name)
        specs.extend(found)

    if filter_fn is not None:
        specs = [s for s in specs if filter_fn(s)]
    return specs


def discover_from_entry_points(group: str = ENTRY_POINT_GROUP) -> list[PatchSpec]:
    """从 entry point 发现补丁包（wrapt discover_post_import_hooks 风格）。"""
    specs: list[PatchSpec] = []
    try:
        eps = importlib.metadata.entry_points(group=group)
    except TypeError:  # Python 3.8/3.9 老 API
        eps = importlib.metadata.entry_points().get(group, ())  # type: ignore[assignment]

    for ep in eps:
        try:
            obj = ep.load()
        except Exception as exc:
            logger.warning("加载 entry point %s 失败：%s", ep.name, exc)
            continue
        # entry point 可指向单个 PatchSpec、可迭代的 PatchSpec，或返回它们的函数
        if callable(obj) and not isinstance(obj, PatchSpec):
            try:
                obj = obj()
            except Exception:
                pass
        if isinstance(obj, PatchSpec):
            specs.append(obj)
        elif isinstance(obj, (list, tuple)):
            specs.extend(s for s in obj if isinstance(s, PatchSpec))
        else:
            logger.warning("entry point %s 未返回 PatchSpec", ep.name)
    return specs


def discover_all(
    package: str = "funcpatch.patches",
    group: str = ENTRY_POINT_GROUP,
    filter_fn: Callable[[PatchSpec], bool] | None = None,
) -> list[PatchSpec]:
    """同时执行两种发现，合并去重（按 owner+target+replacement 身份）。"""
    specs = discover_from_directory(package, filter_fn) + discover_from_entry_points(group)
    seen: set[tuple[str, str, int]] = set()
    unique: list[PatchSpec] = []
    for spec in specs:
        key = (spec.owner, spec.target, id(spec.replacement))
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique
