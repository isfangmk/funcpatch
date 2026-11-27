"""Loader：用 wrapt 的 post-import-hook 延迟应用补丁。

关键：引导阶段目标模块（如 app.core.config）还没进 sys.path，
因此只注册"模块名 + 回调字符串"，不 import 目标模块。
wrapt 的 ImportHookFinder 会在目标模块首次被 import 后触发回调。
"""

from __future__ import annotations

import logging
import threading

import wrapt.importer  # pyright: ignore[reportMissingImports]

from .audit import AuditReport
from .config import SelectionConfig
from .discovery import discover_all
from .registry import Registry
from .spec import PatchSpec

logger = logging.getLogger("funcpatch.loader")

_REGISTRY: Registry | None = None
_REPORT: AuditReport | None = None
_HOOKS: dict[str, object] = {}
_LOCK = threading.RLock()  # 保护 bootstrap/shutdown 的全局状态


def get_registry() -> Registry | None:
    return _REGISTRY


def get_report() -> AuditReport | None:
    return _REPORT


def _on_module_loaded(module: object, registry: Registry, report: AuditReport) -> None:
    """wrapt 在目标模块 import 后调用的回调。"""
    module_name = getattr(module, "__name__", "")
    try:
        registry.apply_module(module_name, report)
    except Exception as exc:
        # strict=True 时 apply 可能抛领域异常。post-import-hook 由 wrapt 在
        # 目标模块的 import 语句中同步调用，异常冒泡会中断完全无关的业务 import；
        # strict 的 fail-fast 语义只适用于调用方显式 apply，hook 内改为记录并隔离。
        logger.error("模块 %s 的补丁应用失败：%s", module_name, exc)
    # 只打印本次新增的条目，避免每次 import 都重复打印全部历史。
    report.log()


def _dispatch_module_loaded(module: object) -> None:
    """稳定的 hook 回调：始终读取当前 Registry，不闭包捕获旧实例。

    这样 shutdown 后重新 bootstrap 时，已注册的 hook 会作用于新 Registry，
    无需撤销 wrapt 的 post-import-hook（那无法可靠实现）。
    """
    registry = _REGISTRY
    report = _REPORT
    if registry is None or report is None or not registry.specs:
        return
    _on_module_loaded(module, registry, report)


def bootstrap(
    config: SelectionConfig | None = None,
    specs: list[PatchSpec] | None = None,
    *,
    strict: bool = False,
) -> Registry:
    """初始化 funcpatch：发现补丁并按模块注册延迟 hook。

    由部署方在进程启动早期调用（或在 .pth 引导里调用）。
    幂等：已有实例时直接返回，避免重复注册 hook 与重复打印审计。
    并发安全：整个初始化过程受锁保护。
    """
    global _REGISTRY, _REPORT

    with _LOCK:
        if _REGISTRY is not None:
            logger.debug("funcpatch 已初始化，复用现有 Registry")
            return _REGISTRY

        resolved_config = config or _load_default_config()
        resolved_specs = specs if specs is not None else discover_all()
        registry = Registry(resolved_config, resolved_specs, strict=strict)
        report = AuditReport()

        # 必须在注册 hook 之前发布状态：wrapt 对已导入的模块会同步立即触发
        # hook，若此时 _REGISTRY 仍为 None，_dispatch_module_loaded 会直接返回，
        # 补丁被静默丢弃且以后不会再触发。
        _REGISTRY = registry
        _REPORT = report

        if resolved_config.enabled:
            for module_name in {s.target_module for s in resolved_specs}:
                # 每个模块只注册一个稳定 hook；重复 bootstrap 不会累积，
                # 且 hook 始终作用于最新的 Registry。
                if module_name in _HOOKS:
                    continue
                wrapt.importer.register_post_import_hook(_dispatch_module_loaded, module_name)
                _HOOKS[module_name] = _dispatch_module_loaded
                logger.info("已为目标模块注册加载钩子：%s", module_name)
        else:
            logger.info("funcpatch 全局关闭（FUNC_PATCH_ENABLED=false），未注册加载钩子")

        return registry


def shutdown() -> int:
    """回滚本 Registry 已应用补丁并清空全局状态，返回成功回滚数量。

    只释放本 Registry 持有的目标占用，不影响其它 Registry 实例；
    已注册的 wrapt post-import-hook 无法撤销，但对应的 Registry 已无 spec，
    后续 hook 触发时是空操作。重新 bootstrap 会复用已有 hook，不重复注册。
    """
    global _REGISTRY, _REPORT

    with _LOCK:
        count = 0
        registry = _REGISTRY
        if registry is not None:
            count = registry.revert_all()
            registry.specs.clear()
        _REGISTRY = None
        _REPORT = None
        # 不清 _HOOKS：保留已注册的 hook 以避免重复注册；
        # hook 读取全局变量，_REGISTRY 为 None 时是空操作。
        logger.info("funcpatch 已关闭，回滚 %d 个补丁", count)
        return count


def _load_default_config() -> SelectionConfig:
    from .config import load_config

    return load_config()
