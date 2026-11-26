"""funcpatch — 主分支零改动的函数实现替换框架。

一个目标函数，一次部署，只有一个 owner 生效。

基本用法：
    from funcpatch import PatchSpec, bootstrap

    patch = PatchSpec(
        owner="client_a",
        target_module="app.core.config",
        target_attr="Settings.build_headers",
        replacement=my_build_headers,
    )
    registry = bootstrap()  # 发现补丁 + 注册延迟 hook

部署选择：
    FUNC_PATCH_OWNER=client_a 或 funcpatch.toml
"""

from ._diagnostics import get_applied_info, is_patched
from ._scoped import scoped_patch, transient_patch
from .audit import AuditReport
from .config import SelectionConfig, load_config
from .decorators import collect_patched, patch
from .discovery import (
    discover_all,
    discover_from_directory,
    discover_from_entry_points,
)
from .exceptions import (
    ConflictError,
    PatchRejectedError,
    PathResolutionError,
    TargetNotFoundError,
)
from .loader import bootstrap, get_registry, get_report
from .registry import Registry
from .spec import PatchSpec, source_hash

__version__ = "0.1.0"

__all__ = [
    "PatchSpec",
    "Registry",
    "SelectionConfig",
    "AuditReport",
    "source_hash",
    "load_config",
    "bootstrap",
    "get_registry",
    "get_report",
    "discover_all",
    "discover_from_directory",
    "discover_from_entry_points",
    "patch",
    "collect_patched",
    "scoped_patch",
    "transient_patch",
    "is_patched",
    "get_applied_info",
    "PathResolutionError",
    "TargetNotFoundError",
    "PatchRejectedError",
    "ConflictError",
]
