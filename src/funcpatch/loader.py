"""Loader：用 wrapt 的 post-import-hook 延迟应用补丁。

关键：引导阶段目标模块（如 app.core.config）还没进 sys.path，
因此只注册"模块名 + 回调字符串"，不 import 目标模块。
wrapt 的 ImportHookFinder 会在目标模块首次被 import 后触发回调。
"""

from __future__ import annotations

import logging

import wrapt.importer

from .audit import AuditReport
from .config import SelectionConfig
from .discovery import discover_all
from .registry import Registry
from .spec import PatchSpec

logger = logging.getLogger("funcpatch.loader")

_REGISTRY: Registry | None = None
_REPORT: AuditReport | None = None


def get_registry() -> Registry | None:
    return _REGISTRY


def get_report() -> AuditReport | None:
    return _REPORT


def _on_module_loaded(module: object, registry: Registry, report: AuditReport) -> None:
    """wrapt 在目标模块 import 后调用的回调。"""
    module_name = getattr(module, "__name__", "")
    registry.apply_module(module_name, report)
    report.log()


def bootstrap(
    config: SelectionConfig | None = None,
    specs: list[PatchSpec] | None = None,
) -> Registry:
    """初始化 funcpatch：发现补丁并按模块注册延迟 hook。

    由部署方在进程启动早期调用（或在 .pth 引导里调用）。
    """
    global _REGISTRY, _REPORT

    resolved_config = config or _load_default_config()
    resolved_specs = specs if specs is not None else discover_all()
    registry = Registry(resolved_config, resolved_specs)
    report = AuditReport()

    _REGISTRY = registry
    _REPORT = report

    def _make_callback(r: Registry, rep: AuditReport):
        def callback(module: object) -> None:
            _on_module_loaded(module, r, rep)

        return callback

    for module_name in {s.target_module for s in resolved_specs}:
        # 用闭包携带 registry/report，注册 post-import-hook；
        # 若模块已导入，wrapt 会立即触发回调。
        wrapt.importer.register_post_import_hook(_make_callback(registry, report), module_name)
        logger.info("已为目标模块注册加载钩子：%s", module_name)

    return registry


def _load_default_config() -> SelectionConfig:
    from .config import load_config

    return load_config()
