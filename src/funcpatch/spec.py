"""PatchSpec：补丁的纯数据描述。

借鉴 gorilla.Patch 的数据对象模式，增加 owner 与版本校验（expect_hash）。
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True)
class PatchSpec:
    """一条补丁的描述。

    owner:           补丁归属方（部署时用 FUNC_PATCH_OWNER / 配置选择）
    target_module:    目标模块点分名，如 "app.core.config"
    target_attr:      目标属性点分路径，如 "Settings.build_headers"
    replacement:      替代实现（完整函数体由补丁拥有）
    expect_hash:      目标函数预期源码 hash；为空表示不校验
    mode:             "replace" 完全替换实现；"wrap" 包一层可调用原函数
    enabled:          bool 或 callable；False 时调用原函数（透传 wrapt FunctionWrapper）
    description:      人类可读说明
    """

    owner: str
    target_module: str
    target_attr: str
    replacement: Callable[..., Any]
    expect_hash: str = ""
    mode: str = "replace"
    enabled: bool | Callable[[], bool] = True
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def target(self) -> str:
        return f"{self.target_module}:{self.target_attr}"

    def __post_init__(self) -> None:
        if not self.owner or not self.target_module or not self.target_attr:
            raise ValueError("PatchSpec 的 owner / target_module / target_attr 不能为空")
        if not callable(self.replacement):
            raise TypeError("replacement 必须是可调用对象")
        if self.mode not in ("replace", "wrap"):
            raise ValueError(f"mode 必须是 'replace' 或 'wrap'，当前为 {self.mode!r}")
