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

部署前校验：
    from funcpatch import validate, bootstrap
    results = validate(specs)      # 不修改任何状态
    if all(r.ok for r in results):
        bootstrap(specs=specs)
"""

from . import _version_check  # noqa: F401  # pyright: ignore[reportUnusedImport]  # 依赖版本守卫
from ._claims import claim_key, claims_snapshot, clear_claim
from ._diagnostics import (
    get_applied_info,
    get_wrapper,
    is_patched,
)
from ._diagnostics import (
    unwrap as unwrap_target,
)
from ._requirements import check_requires
from ._scoped import scoped_patch, transient_patch
from ._suppression import is_suppressed, suppress_patches
from .audit import AuditReport
from .bridge import *  # noqa: F403  # wrapt 能力透传，见 bridge.__all__
from .bridge import __all__ as _bridge_all
from .config import SelectionConfig, load_config, normalize_target, parse_enabled
from .decorators import collect_patched, patch, patches
from .discovery import (
    discover_all,
    discover_from_directory,
    discover_from_entry_points,
    get_spec_origin,
)
from .exceptions import (
    ConflictError,
    DeprecatedTargetWarning,
    FunCPatchError,
    FunCPatchWarning,
    PatchRejectedError,
    PathResolutionError,
    TargetNotFoundError,
)
from .generation import create_patches, find_patches, get_original_attribute
from .introspection import (
    default_filter,
    get_attribute,
    get_base,
    get_members,
)
from .loader import bootstrap, get_registry, get_report, shutdown
from .registry import ApplyResult, Registry
from .spec import PatchSpec, dependency_hash, source_hash
from .validation import ValidationResult, validate, validate_spec

__version__ = "0.3.0"

# pyright: reportUnsupportedDunderAll=false
# 桥接层 50 个名称用展开合并，静态检查器不解析 * 展开，故本地关闭该提示。
__all__ = [
    # wrapt 能力桥接（50 个透传名称）
    *_bridge_all,
    # 描述符安全自省（gorilla 模式）
    "get_attribute",
    "get_base",
    "get_members",
    "default_filter",
    # 批量生成（gorilla 模式）
    "create_patches",
    "find_patches",
    "get_original_attribute",
    # 数据 / 配置
    "PatchSpec",
    "Registry",
    "ApplyResult",
    "SelectionConfig",
    "AuditReport",
    "source_hash",
    "dependency_hash",
    "load_config",
    "normalize_target",
    "parse_enabled",
    # 生命周期
    "bootstrap",
    "shutdown",
    "get_registry",
    "get_report",
    # 发现
    "discover_all",
    "discover_from_directory",
    "discover_from_entry_points",
    "get_spec_origin",
    "check_requires",
    # 上下文抑制
    "suppress_patches",
    "is_suppressed",
    # 声明
    "patch",
    "patches",
    "collect_patched",
    # 作用域
    "scoped_patch",
    "transient_patch",
    # 诊断
    "is_patched",
    "get_applied_info",
    "get_wrapper",
    "unwrap_target",
    "claims_snapshot",
    "clear_claim",
    "claim_key",
    # 校验
    "validate",
    "validate_spec",
    "ValidationResult",
    # 异常 / 警告
    "FunCPatchError",
    "PathResolutionError",
    "TargetNotFoundError",
    "PatchRejectedError",
    "ConflictError",
    "FunCPatchWarning",
    "DeprecatedTargetWarning",
]
