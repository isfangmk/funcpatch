"""补丁发现：目录扫描 + entry point 双支持。

开发期：把补丁写进自建的包，用 discover_from_directory 指定包名后自动扫描发现。
默认扫描的 "funcpatch.patches" 指已安装的 funcpatch 包下的 patches 子包——
项目里不要自建同名目录，那会遮蔽已安装的 funcpatch。
生产期：每个 owner 做成独立 pip 包，声明 entry point 组 "funcpatch.patches"。
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import pkgutil
from collections.abc import Callable, Iterable
from types import ModuleType
from typing import Any

from .decorators import collect_patched
from .spec import PatchSpec

logger = logging.getLogger("funcpatch.discovery")

ENTRY_POINT_GROUP = "funcpatch.patches"

# entry point 来源追溯：spec id → {distribution, version, ep_name}。
# 用 id(spec) 作键避免污染 frozen 的 PatchSpec 数据对象。
_SPEC_ORIGINS: dict[int, dict[str, str]] = {}


def get_spec_origin(spec: PatchSpec) -> dict[str, str] | None:
    """返回该 spec 的 entry point 来源（发行包名/版本/ep 名），非 entry point 返回 None。"""
    return _SPEC_ORIGINS.get(id(spec))


def _record_origin(spec: PatchSpec, ep: Any) -> None:
    dist = getattr(ep, "dist", None)
    _SPEC_ORIGINS[id(spec)] = {
        "distribution": getattr(dist, "name", "") or "",
        "version": getattr(dist, "version", "") or "",
        "ep_name": getattr(ep, "name", "") or "",
    }


def _collect_specs(module: ModuleType) -> list[PatchSpec]:
    """从模块中收集所有 PatchSpec：数据式实例 + 装饰式声明。"""
    specs: list[PatchSpec] = []
    for _name, obj in vars(module).items():
        if isinstance(obj, PatchSpec):
            specs.append(obj)
    # 装饰式 @patch 声明
    specs.extend(collect_patched(module))
    return specs


def _iter_package_modules(package: str, recursive: bool) -> Iterable[str]:
    """产出包名及其子模块名；recursive=True 时递归进入子包。

    借鉴 gorilla 的 _module_iterator：遍历时只产出名字，实际 import
    交给调用方做，便于对每个模块单独做失败隔离（语法错误、运行时异常同样跳过）。
    """
    yield package
    try:
        pkg = importlib.import_module(package)
    except ImportError as exc:
        logger.debug("目录扫描包 %s 不存在：%s", package, exc)
        return

    paths = getattr(pkg, "__path__", None)
    if paths is None:
        return

    if recursive:
        for info in pkgutil.walk_packages(paths, prefix=f"{package}."):
            yield info.name
    else:
        for info in pkgutil.iter_modules(paths):
            if not info.ispkg:
                yield f"{package}.{info.name}"


def discover_from_directory(
    package: str = "funcpatch.patches",
    filter_fn: Callable[[PatchSpec], bool] | None = None,
    *,
    recursive: bool = False,
) -> list[PatchSpec]:
    """扫描包目录下所有模块，收集 PatchSpec。"""
    specs: list[PatchSpec] = []
    for name in _iter_package_modules(package, recursive):
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            logger.debug("跳过包 %s：%s", name, exc)
            continue
        found = _collect_specs(module)
        if found:
            logger.debug("目录扫描发现 %d 条补丁：%s", len(found), name)
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
        # entry point 可指向单个 PatchSpec、任意可迭代的 PatchSpec，或返回它们的函数
        if callable(obj) and not isinstance(obj, PatchSpec):
            try:
                obj = obj()
            except Exception as exc:
                logger.warning("entry point %s 调用失败：%s", ep.name, exc)
                continue
        if isinstance(obj, PatchSpec):
            _record_origin(obj, ep)
            specs.append(obj)
        elif isinstance(obj, Iterable) and not isinstance(obj, (str, bytes, dict)):
            for spec in obj:
                if isinstance(spec, PatchSpec):
                    _record_origin(spec, ep)
                    specs.append(spec)
                else:
                    logger.warning("entry point %s 返回了非 PatchSpec 项：%r", ep.name, spec)
        else:
            logger.warning("entry point %s 未返回 PatchSpec", ep.name)
    return specs


def discover_all(
    package: str = "funcpatch.patches",
    group: str = ENTRY_POINT_GROUP,
    filter_fn: Callable[[PatchSpec], bool] | None = None,
    *,
    recursive: bool = False,
) -> list[PatchSpec]:
    """同时执行两种发现，合并去重（按 owner+target+replacement 身份）。

    filter_fn 对两种来源的 spec 都生效。
    """
    specs = discover_from_directory(package, filter_fn, recursive=recursive)
    eps = discover_from_entry_points(group)
    if filter_fn is not None:
        eps = [s for s in eps if filter_fn(s)]
    specs += eps
    seen: set[tuple[str, str, int]] = set()
    unique: list[PatchSpec] = []
    for spec in specs:
        key = (spec.owner, spec.target, id(spec.replacement))
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique
