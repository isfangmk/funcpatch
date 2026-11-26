"""Registry：补丁注册表，执行"单一生效"不变式。

职责：discover → select → verify → apply → revert → audit。

两种模式：
  * replace（默认）：完全替换函数实现，函数体由补丁拥有；保存原始引用供回滚。
  * wrap：用 wrapt.FunctionWrapper 包一层，可调用原函数；用 handle 身份回滚。

回滚依赖 wrapt 的 resolve_path / unwrap_object 语义：
  * 安装位置用 resolve_path（允许 shadow 继承属性）
  * 回滚位置用 resolve_owner（回到真正定义处，避免留下影子副本）
  * wrap 模式用安装返回的 handle 做身份匹配（代理对象 __eq__ 被委托，不能用相等）
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import wrapt
import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

from ._descriptors import preserve_descriptor, wrap_with_descriptor
from ._diagnostics import mark_replacement
from ._enabled import make_dispatcher
from .audit import AuditReport
from .config import SelectionConfig
from .spec import PatchSpec, source_hash

# wrapt.patches 的函数为内部实现，部分静态检查器不解析其符号，统一走模块引用并忽略告警。
resolve_owner = wrapt_patches.resolve_owner  # pyright: ignore[reportAttributeAccessIssue]
resolve_path = wrapt_patches.resolve_path
unwrap_object = wrapt_patches.unwrap_object  # pyright: ignore[reportAttributeAccessIssue]

logger = logging.getLogger("funcpatch.registry")


@dataclass
class _Applied:
    """已应用补丁的内部记录。"""

    spec: PatchSpec
    parent: Any
    attr: str
    original: Any
    handle: Any = None  # wrap 模式的 wrapper 对象，用于 unwrap_object


class Registry:
    """补丁注册表。一个 Registry 实例对应一次部署。"""

    def __init__(self, config: SelectionConfig, specs: list[PatchSpec]) -> None:
        self.config = config
        self.specs = list(specs)
        self._applied: dict[str, _Applied] = {}
        # 保护 apply/revert 的幂等检查与状态写入，避免并发重复应用。
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ 查询

    def specs_for_module(self, module_name: str) -> list[PatchSpec]:
        return [s for s in self.specs if s.target_module == module_name]

    def specs_for_target(self, target: str) -> list[PatchSpec]:
        return [s for s in self.specs if s.target == target]

    def targets(self) -> list[str]:
        seen: list[str] = []
        for spec in self.specs:
            if spec.target not in seen:
                seen.append(spec.target)
        return seen

    def select(self, target: str) -> tuple[PatchSpec | None, list[str]]:
        """按三层规则选出唯一生效补丁，返回 (选中补丁, 未生效的 owner 列表)。

        选中者不存在时返回 (None, ...)，调用方应走原始实现（fail-safe）。
        """
        candidates = self.specs_for_target(target)
        if not candidates:
            return None, []

        owner = self.config.owner_for(target)
        if not owner:
            return None, [s.owner for s in candidates]

        chosen = next((s for s in candidates if s.owner == owner), None)
        skipped = [s.owner for s in candidates if s.owner != owner]
        if chosen is None:
            logger.warning(
                "owner=%s 未注册目标 %s 的补丁；可用 owner=%s",
                owner,
                target,
                ", ".join(s.owner for s in candidates),
            )
        return chosen, skipped

    # ------------------------------------------------------------------ 应用

    def apply(self, target: str, report: AuditReport | None = None) -> bool:
        """应用目标补丁（线程安全）。模块必须已导入（由 loader 保证）。"""
        with self._lock:
            return self._apply_locked(target, report)

    def _apply_locked(self, target: str, report: AuditReport | None) -> bool:
        if target in self._applied:
            return True  # 幂等

        chosen, skipped = self.select(target)
        if chosen is None:
            if report:
                report.rejections.append(
                    {
                        "owner": self.config.owner_for(target) or "",
                        "target": target,
                        "reason": "no selected owner",
                    }
                )
            return False
        if report:
            for owner in skipped:
                report.conflicts.append(
                    {"target": target, "chosen": chosen.owner, "skipped": owner}
                )

        module, _sep, attr_path = target.partition(":")
        try:
            module_obj = __import__(module, fromlist=["*"])
            parent, attr, original = resolve_path(module_obj, attr_path)
        except Exception as exc:
            if report:
                report.rejections.append(
                    {"owner": chosen.owner, "target": target, "reason": f"resolve failed: {exc}"}
                )
            logger.error("解析目标 %s 失败：%s", target, exc)
            return False

        # 描述符（classmethod/staticmethod/property）取底层函数做版本校验与包装
        raw_original = (
            original.__func__ if isinstance(original, (classmethod, staticmethod)) else original
        )
        if isinstance(original, property):
            raw_original = original.fget or (lambda *a, **k: None)

        # 版本校验：主分支函数被改过则拒绝应用，避免静默失效
        if chosen.expect_hash:
            actual = source_hash(raw_original)
            if actual != chosen.expect_hash:
                reason = f"hash mismatch: expect={chosen.expect_hash} actual={actual}"
                if report:
                    report.rejections.append(
                        {"owner": chosen.owner, "target": target, "reason": reason}
                    )
                logger.error("版本校验失败 %s：%s", target, reason)
                return False

        try:
            if chosen.mode == "wrap":
                # wrapt 原生支持 enabled（bool / callable，每次调用时求值）
                wrapper = wrapt.FunctionWrapper(
                    raw_original, chosen.replacement, enabled=chosen.enabled
                )
                mark_replacement(wrapper, chosen.owner, target)
                to_install = wrap_with_descriptor(original, wrapper)
                wrapt.apply_patch(parent, attr, to_install)
                self._applied[target] = _Applied(chosen, parent, attr, original, wrapper)
            else:  # replace
                # replace 无 wrapt 包装层，用 dispatcher 实现同等 enabled 语义
                impl = chosen.replacement
                if chosen.enabled is not True:
                    impl = make_dispatcher(chosen.replacement, raw_original, chosen.enabled)
                mark_replacement(impl, chosen.owner, target)
                to_install = preserve_descriptor(original, impl)
                wrapt.apply_patch(parent, attr, to_install)
                self._applied[target] = _Applied(chosen, parent, attr, original)
        except Exception as exc:
            if report:
                report.rejections.append(
                    {"owner": chosen.owner, "target": target, "reason": f"apply failed: {exc}"}
                )
            logger.error("应用补丁 %s 失败：%s", target, exc)
            return False

        if report:
            report.entries.append({"owner": chosen.owner, "target": target})
        logger.info("补丁已生效：owner=%s target=%s mode=%s", chosen.owner, target, chosen.mode)
        return True

    def apply_module(self, module_name: str, report: AuditReport | None = None) -> int:
        """应用某模块下的所有目标，返回成功应用数量。"""
        count = 0
        for spec in self.specs_for_module(module_name):
            if self.apply(spec.target, report):
                count += 1
        return count

    # ------------------------------------------------------------------ 回滚

    def revert(self, target: str, *, missing_ok: bool = True) -> bool:
        """回滚目标补丁（线程安全）。"""
        with self._lock:
            return self._revert_locked(target, missing_ok=missing_ok)

    def _revert_locked(self, target: str, *, missing_ok: bool = True) -> bool:
        applied = self._applied.pop(target, None)
        if applied is None:
            return not missing_ok  # missing_ok=True 时返回 False 表示无需回滚

        try:
            if applied.spec.mode == "wrap" and applied.handle is not None:
                module, _sep, attr_path = target.partition(":")
                module_obj = __import__(module, fromlist=["*"])
                unwrap_object(module_obj, attr_path, applied.handle, missing_ok=False)
            else:
                # replace 模式：用 resolve_owner 定位真正定义处，避免留下影子副本
                owner, attr, _cur = resolve_owner(applied.parent, applied.attr)
                wrapt.apply_patch(owner, attr, applied.original)
        except Exception as exc:
            logger.warning("回滚补丁 %s 失败：%s", target, exc)
            return False
        logger.info("补丁已回滚：target=%s", target)
        return True

    def revert_all(self) -> int:
        count = 0
        for target in list(self._applied):
            if self.revert(target):
                count += 1
        return count

    def get_original(self, target: str) -> Callable[..., Any] | None:
        """返回被替换的原始函数，供补丁内部复用原逻辑。"""
        applied = self._applied.get(target)
        original = applied.original if applied else None
        return original if callable(original) else None

    def is_applied(self, target: str) -> bool:
        return target in self._applied
