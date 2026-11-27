"""PatchSpec：补丁的纯数据描述。

借鉴 gorilla.Patch 的数据对象模式，增加 owner 与版本校验（expect_hash）。
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast


def source_hash(func: Callable[..., Any]) -> str:
    """计算函数源码的 hash，用于版本校验。

    目标函数被主分支改动后，hash 变化，registry 拒绝应用补丁并告警，
    避免补丁静默失效或行为错乱。
    """
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError):
        # 无法取源码（交互式/编译产物）时退回 code object 字节码
        code = getattr(func, "__code__", None)
        source = repr(code.co_code) if code else repr(func)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _is_own_definition(value: Any, module_name: str) -> bool:
    """判断全局值是否是本模块定义的函数/类（排除导入的外部对象）。"""
    if not (inspect.isfunction(value) or inspect.isclass(value)):
        return False
    return getattr(value, "__module__", None) == module_name


def dependency_hash(func: Callable[..., Any]) -> str:
    """计算函数及其模块级依赖的联合 hash。

    覆盖目标函数源码，以及它通过全局名引用、且定义在**同一模块**的函数/类。
    这样主分支改了目标调用的 helper，补丁也能发现并拒绝，避免静默跑在旧假设上。
    不递归追踪跨模块依赖（那会把第三方库变动也算进来，噪声过大），
    也不 hash 常量——常量变化通常伴随函数源码变化。
    """
    pieces = [source_hash(func)]
    module_name = getattr(func, "__module__", "")
    globals_dict = getattr(func, "__globals__", {}) or {}
    code = getattr(func, "__code__", None)
    names = getattr(code, "co_names", ()) if code else ()

    seen: set[int] = set()
    for name in names:
        value = globals_dict.get(name)
        if not _is_own_definition(value, module_name):
            continue
        if id(value) in seen:
            continue
        seen.add(id(value))
        pieces.append(f"{name}:{source_hash(cast(Callable[..., Any], value))}")

    return hashlib.sha256("\n".join(pieces).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PatchSpec:
    """一条补丁的描述。

    owner:           补丁归属方（部署时用 FUNC_PATCH_OWNER / 配置选择）
    target_module:    目标模块点分名，如 "app.core.config"
    target_attr:      目标属性点分路径，如 "Settings.build_headers"
    replacement:      替代实现（完整函数体由补丁拥有）
    expect_hash:      目标函数预期源码 hash；为空表示不校验
    expect_deps_hash: 目标函数 + 同模块依赖的预期联合 hash；为空表示不校验
    mode:             "replace" 完全替换；"wrap" 包一层可调用原函数；
                      "add" 添加原本不存在的属性/方法，回滚时删除
    enabled:          bool 或 callable；False 时调用原函数（透传 wrapt FunctionWrapper）
    description:      人类可读说明
    """

    owner: str
    target_module: str
    target_attr: str
    replacement: Callable[..., Any]
    expect_hash: str = ""
    expect_deps_hash: str = ""
    mode: str = "replace"
    enabled: bool | Callable[[], bool] = True
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    # 当目标是 property 时，指定替换哪一部分；其余部分保持不变。
    property_part: Literal["get", "set", "delete"] = "get"
    # 部署包版本约束（PEP 508，如 "app>=2.3,<3"）；为空表示不校验。
    requires: tuple[str, ...] = ()
    # 目标废弃标记；非空时在 apply/validate 时发 DeprecatedTargetWarning。
    deprecated: str = ""

    @property
    def target(self) -> str:
        return f"{self.target_module}:{self.target_attr}"

    def __post_init__(self) -> None:
        if not self.owner or not self.target_module or not self.target_attr:
            raise ValueError("PatchSpec 的 owner / target_module / target_attr 不能为空")
        if not callable(self.replacement):
            raise TypeError("replacement 必须是可调用对象")
        if self.mode not in ("replace", "wrap", "add"):
            raise ValueError(f"mode 必须是 'replace' / 'wrap' / 'add'，当前为 {self.mode!r}")
        if self.property_part not in ("get", "set", "delete"):
            raise ValueError(
                f"property_part 必须是 'get'/'set'/'delete'，当前为 {self.property_part!r}"
            )
