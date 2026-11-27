"""wrapt 能力桥接层：把 wrapt 的成熟工具以 funcpatch 命名空间透传给用户。

wrapt 已成熟实现的能力不重造，funcpatch 只负责暴露。
这里全部是薄封装或直接 re-export，不含任何自研代理/钩子逻辑。

用户因此只需 ``from funcpatch import ...`` 即可用全套 wrapt 工具，
而不必直接依赖 wrapt 的私有模块路径（如 wrapt.patches）。
"""

from __future__ import annotations

import wrapt
import wrapt.importer  # pyright: ignore[reportMissingImports]
import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

# ---------------------------------------------------------------- 代理 / 包装器

ObjectProxy = wrapt.ObjectProxy
BaseObjectProxy = wrapt.BaseObjectProxy
CallableObjectProxy = wrapt.CallableObjectProxy
FunctionWrapper = wrapt.FunctionWrapper
BoundFunctionWrapper = wrapt.BoundFunctionWrapper
PartialCallableObjectProxy = wrapt.PartialCallableObjectProxy
AutoObjectProxy = wrapt.AutoObjectProxy
LazyObjectProxy = wrapt.LazyObjectProxy
WeakFunctionProxy = wrapt.WeakFunctionProxy
AttributeWrapper = wrapt.AttributeWrapper

partial = wrapt.partial
lazy_import = wrapt.lazy_import

# ---------------------------------------------------------------- 装饰器 / 签名

decorator = wrapt.decorator
function_wrapper = wrapt.function_wrapper
lru_cache = wrapt.lru_cache
adapter_factory = wrapt.adapter_factory
AdapterFactory = wrapt.AdapterFactory
bind_state_to_wrapper = wrapt.bind_state_to_wrapper
with_signature = wrapt.with_signature
with_doc = wrapt.with_doc

# ---------------------------------------------------------------- 调用约定桥接

async_to_sync = wrapt.async_to_sync
sync_to_async = wrapt.sync_to_async
mark_as_sync = wrapt.mark_as_sync
mark_as_async = wrapt.mark_as_async
synchronized = wrapt.synchronized

# ---------------------------------------------------------------- 补丁应用 / 链诊断

apply_patch = wrapt.apply_patch
unwrap_object = wrapt.unwrap_object
wrap_object = wrapt.wrap_object
wrap_object_attribute = wrapt.wrap_object_attribute
wrap_function_wrapper = wrapt.wrap_function_wrapper
patch_function_wrapper = wrapt.patch_function_wrapper
scoped_function_wrapper = wrapt.scoped_function_wrapper
transient_function_wrapper = wrapt.transient_function_wrapper

find_wrapper = wrapt.find_wrapper
is_wrapped_by = wrapt.is_wrapped_by
wrapper_chain = wrapt.wrapper_chain
unwrapped = wrapt.unwrapped
resolve_path = wrapt.resolve_path
resolve_owner = wrapt.resolve_owner

MISSING = wrapt.MISSING

# ---------------------------------------------------------------- 导入钩子

register_post_import_hook = wrapt.importer.register_post_import_hook
discover_post_import_hooks = wrapt.importer.discover_post_import_hooks
notify_module_loaded = wrapt.importer.notify_module_loaded
when_imported = wrapt.importer.when_imported

# ---------------------------------------------------------------- 异常

WraptPathResolutionError = wrapt.PathResolutionError
TargetModuleNotFoundError = wrapt.TargetModuleNotFoundError
WrapperNotFoundError = wrapt.WrapperNotFoundError
WrapperNotOutermostError = wrapt.WrapperNotOutermostError
WrapperNotInitializedError = wrapt.WrapperNotInitializedError
WrapperChainTooDeepError = wrapt.WrapperChainTooDeepError

# 内部别名：用于 funcpatch 自身实现（保持单一 wrapt.patches 引用点）
_resolve_path = wrapt_patches.resolve_path
_resolve_owner = wrapt_patches.resolve_owner
_unwrap_object = wrapt_patches.unwrap_object
_find_wrapper = wrapt_patches.find_wrapper
_is_wrapped_by = wrapt_patches.is_wrapped_by

__all__ = [
    # 代理 / 包装器
    "ObjectProxy",
    "BaseObjectProxy",
    "CallableObjectProxy",
    "FunctionWrapper",
    "BoundFunctionWrapper",
    "PartialCallableObjectProxy",
    "AutoObjectProxy",
    "LazyObjectProxy",
    "WeakFunctionProxy",
    "AttributeWrapper",
    "partial",
    "lazy_import",
    # 装饰器 / 签名
    "decorator",
    "function_wrapper",
    "lru_cache",
    "adapter_factory",
    "AdapterFactory",
    "bind_state_to_wrapper",
    "with_signature",
    "with_doc",
    # 调用约定
    "async_to_sync",
    "sync_to_async",
    "mark_as_sync",
    "mark_as_async",
    "synchronized",
    # 补丁 / 链诊断
    "apply_patch",
    "unwrap_object",
    "wrap_object",
    "wrap_object_attribute",
    "wrap_function_wrapper",
    "patch_function_wrapper",
    "scoped_function_wrapper",
    "transient_function_wrapper",
    "find_wrapper",
    "is_wrapped_by",
    "wrapper_chain",
    "unwrapped",
    "resolve_path",
    "resolve_owner",
    "MISSING",
    # 导入钩子
    "register_post_import_hook",
    "discover_post_import_hooks",
    "notify_module_loaded",
    "when_imported",
    # 异常
    "WraptPathResolutionError",
    "TargetModuleNotFoundError",
    "WrapperNotFoundError",
    "WrapperNotOutermostError",
    "WrapperNotInitializedError",
    "WrapperChainTooDeepError",
]
