"""作用域/临时补丁：透传 wrapt 的 scoped_function_wrapper / transient_function_wrapper。

两者都只在特定范围内生效，退出后自动回滚，不经过 Registry 的持久化应用：
  * scoped_patch：with 块内生效
  * transient_patch：被装饰函数调用期间生效

虽然是临时补丁，仍遵循 funcpatch 的安全约束：
  * 校验 expect_hash（目标被主分支改过时拒绝）
  * 检查进程级占用（已有持久化补丁在作用域内临时覆盖算冲突）
  * 记审计日志

两者都接受 wrapt 风格的 wrapper（签名 (wrapped, instance, args, kwargs)），
即 funcpatch 的 mode="wrap" 语义。这样能正确调用原函数，避免混用两套模型。
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

from ._claims import claim_target, release_target
from ._descriptors import unwrap_descriptor
from ._diagnostics import is_marked
from ._enabled import resolve_enabled
from ._suppression import wrap_enabled
from .spec import PatchSpec, source_hash

logger = logging.getLogger("funcpatch.scoped")

# wrapt.patches 的内部函数部分静态检查器不解析符号，走模块引用并忽略。
scoped_function_wrapper = wrapt_patches.scoped_function_wrapper  # pyright: ignore[reportAttributeAccessIssue]
transient_function_wrapper = wrapt_patches.transient_function_wrapper  # pyright: ignore[reportAttributeAccessIssue]
resolve_path = wrapt_patches.resolve_path  # pyright: ignore[reportAttributeAccessIssue]

WraptWrapper = Callable[[Any, Any, tuple, dict], Any]


def _wrapper_from_spec(spec: PatchSpec) -> WraptWrapper:
    """把 PatchSpec 转成 wrapt wrapper 签名。

    wrapt wrapper 签名：(wrapped, instance, args, kwargs)。
    mode="wrap" 的 replacement 已是该签名，直接使用。
    mode="replace" 的 replacement 是完整实现，包装成忽略原函数的 wrapper。
    """
    replacement = spec.replacement
    enabled = wrap_enabled(spec.enabled)

    if spec.mode == "wrap":
        base = replacement
    else:

        def base(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
            if instance is None:
                return replacement(*args, **kwargs)
            return replacement(instance, *args, **kwargs)

    def wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
        if not resolve_enabled(enabled):
            return wrapped(*args, **kwargs)
        return base(wrapped, instance, args, kwargs)

    return wrapper


class _ScopedOwner:
    """每次作用域补丁调用的独立占用者标识。"""

    __slots__ = ("__weakref__",)


def _validate_scoped(spec: PatchSpec, target_module: str, target_attr: str) -> None:
    """作用域补丁也做 hash 校验，避免绕过安全约束。"""
    module = importlib.import_module(target_module)
    try:
        _parent, _attr, current = resolve_path(module, target_attr)
    except Exception as exc:
        raise ValueError(f"无法解析目标 {target_module}:{target_attr}: {exc}") from exc

    raw = unwrap_descriptor(current, spec.property_part)
    if raw is None or not callable(raw):
        raise ValueError(f"目标 {target_module}:{target_attr} 没有可调用对象")

    if spec.expect_hash:
        actual = source_hash(raw)
        if actual != spec.expect_hash:
            raise ValueError(
                f"版本校验失败 {target_module}:{target_attr}: "
                f"expect={spec.expect_hash} actual={actual}"
            )


def _acquire_claim(target: str, spec: PatchSpec, owner: _ScopedOwner) -> None:
    """声明目标占用；冲突则抛 ValueError。"""
    ok, reason = claim_target(
        target,
        spec.owner,
        owner,
        lambda: is_marked(target, spec.property_part),
        property_part=spec.property_part,
    )
    if not ok:
        raise ValueError(f"作用域补丁冲突：{reason}")


@contextmanager
def scoped_patch(
    target_module: str, target_attr: str, spec: PatchSpec
) -> Generator[None, None, None]:
    """with 块内应用补丁，退出自动回滚。

    用法：
        with scoped_patch("app.core.config", "Settings.build_headers", spec):
            ...  # 期间目标函数被替换
    """
    # scoped 不支持 wrapt 的 "?" 延迟语法：先确保目标模块已导入再解析。
    module = importlib.import_module(target_module)
    _validate_scoped(spec, target_module, target_attr)
    target = f"{target_module}:{target_attr}"
    owner = _ScopedOwner()
    _acquire_claim(target, spec, owner)
    try:
        with scoped_function_wrapper(module, target_attr, _wrapper_from_spec(spec)):
            logger.info("作用域补丁生效：owner=%s target=%s", spec.owner, target)
            yield
    finally:
        release_target(target, owner, property_part=spec.property_part)
        logger.info("作用域补丁结束：target=%s", target)


def transient_patch(
    target_module: str, target_attr: str, spec: PatchSpec
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰一个函数，使其调用期间目标函数被临时替换。

    wrapt 的 transient_function_wrapper 接受 (target, name) 并返回装饰器，
    把 wrapper 交给该装饰器后应用到被装饰函数上；patch 仅在被装饰函数调用期间生效。
    """
    module = importlib.import_module(target_module)
    target = f"{target_module}:{target_attr}"
    wrapper = _wrapper_from_spec(spec)

    # 一个共享 owner + 线程安全活跃计数：
    #   - 单线程递归：thread-local depth 保证只在最外层 acquire/release；
    #   - 多线程并发：共享 owner 让 claim_target 的重入判定放行；
    #     活跃计数保证只有最后一个线程退出时才释放占用，避免先退出线程
    #     提前释放、其它线程仍在执行时目标被第二个 Registry 接管。
    owner = _ScopedOwner()
    local = threading.local()
    state_lock = threading.Lock()
    active_threads = 0

    def guarded_wrapper(wrapped: Any, instance: Any, args: tuple, kwargs: dict) -> Any:
        nonlocal active_threads
        depth = getattr(local, "depth", 0)
        _validate_scoped(spec, target_module, target_attr)
        if depth == 0:
            with state_lock:
                first_thread = active_threads == 0
                active_threads += 1
            if first_thread:
                _acquire_claim(target, spec, owner)
        local.depth = depth + 1
        try:
            return wrapper(wrapped, instance, args, kwargs)
        finally:
            local.depth = depth
            if depth == 0:
                with state_lock:
                    active_threads -= 1
                    last_thread = active_threads == 0
                if last_thread:
                    release_target(target, owner, property_part=spec.property_part)

    decorator = transient_function_wrapper(module, target_attr)
    return decorator(guarded_wrapper)
