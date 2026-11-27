"""Registry：补丁注册表，执行"单一生效"不变式。

职责：discover → select → verify → apply → revert → audit。

两种模式：
  * replace（默认）：完全替换函数实现，函数体由补丁拥有；保存原始引用供回滚。
  * wrap：用 wrapt.FunctionWrapper 包一层，可调用原函数；用 handle 身份回滚。

回滚依赖 wrapt 的 resolve_path / resolve_owner 语义：
  * 安装位置用 resolve_path（允许 shadow 继承属性）
  * 回滚位置用 resolve_owner（回到真正定义处，避免留下影子副本）
  * 普通函数 wrap 模式用安装返回的 handle 做身份匹配（代理对象 __eq__ 被委托，不能用相等）
  * 描述符（classmethod/staticmethod/property）的 wrap 模式直接恢复保存的描述符对象
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import wrapt
import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

from ._claims import claim_key, claim_target, claims_snapshot, release_target
from ._descriptors import (
    is_descriptor,
    preserve_descriptor,
    unwrap_descriptor,
    wrap_with_descriptor,
)
from ._diagnostics import is_patched, mark_replacement
from ._enabled import make_dispatcher
from .audit import AuditReport, _timestamp
from .config import SelectionConfig
from .exceptions import (
    ConflictError,
    PatchRejectedError,
    PathResolutionError,
    TargetNotFoundError,
)
from .introspection import get_attribute
from .spec import PatchSpec, dependency_hash, source_hash

# wrapt.patches 的函数为内部实现，部分静态检查器不解析其符号，统一走模块引用并忽略告警。
resolve_owner = wrapt_patches.resolve_owner  # pyright: ignore[reportAttributeAccessIssue]
resolve_path = wrapt_patches.resolve_path
unwrap_object = wrapt_patches.unwrap_object  # pyright: ignore[reportAttributeAccessIssue]

logger = logging.getLogger("funcpatch.registry")

# add 模式标记：属性原本不存在，回滚时删除而非恢复。
_ADDED = object()

# property 基线：记录目标首次被补丁前的完整 property 对象。
# 理由：property 的 get/set/delete 可被不同 owner 独立打补丁，后应用者保存的
# original 里已经包含前序补丁。回滚某一 part 时必须恢复到"从未被打过补丁"的
# 原始函数，而不是当时快照（否则会清掉别人的补丁或让旧补丁“复活”）。
_BASELINE_PROPERTIES: dict[str, property] = {}
_BASELINE_LOCK = threading.RLock()


def _baseline_property(target: str, current: Any) -> property | None:
    """登记并返回 property 目标的原始基线（只在首次打补丁时记录）。"""
    if not isinstance(current, property):
        return None
    with _BASELINE_LOCK:
        return _BASELINE_PROPERTIES.setdefault(target, current)


@dataclass
class _Applied:
    """已应用补丁的内部记录。"""

    spec: PatchSpec
    parent: Any
    attr: str
    original: Any  # 安装前的完整属性（函数或描述符对象），用于回滚
    raw_original: Callable[..., Any] | None = None  # 底层可调用对象，供 get_original 复用
    handle: Any = None  # 普通函数 wrap 模式的 wrapper 对象，用于 unwrap_object


@dataclass
class _UndoPoint:
    """事务回滚点：记录目标改前的完整状态。"""

    target: str
    applied: _Applied | None
    current_object: Any  # 改动前目标属性上实际存放的对象
    property_part: str = "get"  # 改动涉及的 property 部分（用于精确释放占用）


@dataclass
class ApplyResult:
    """批量应用的结构化结果。"""

    applied: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    rolled_back: list[str] = field(default_factory=list)
    preexisting: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


class Registry:
    """补丁注册表。一个 Registry 实例对应一次部署。

    strict=False（默认）保持 fail-safe：失败只记录并返回 False，不抛异常。
    strict=True 时拒绝点抛出对应领域异常，便于部署前校验或 CI 里 fail-fast。
    """

    def __init__(
        self, config: SelectionConfig, specs: list[PatchSpec], *, strict: bool = False
    ) -> None:
        self.config = config
        self.specs = list(specs)
        self.strict = strict
        self._applied: dict[str, _Applied] = {}
        # 被阻塞的 owner（借鉴 pluggy.set_blocked）：被阻塞者永不参与选择。
        self._blocked_owners: set[str] = set()
        # 事件监听器（借鉴 pluggy.add_hookcall_monitoring）：
        #   listener(event: Literal["apply","revert","reject"], detail: dict)
        self._listeners: list[Callable[[str, dict], None]] = []
        # 事务栈：每层记录目标在每次改动前的实现快照。
        self._tx_stack: list[list[_UndoPoint]] = []
        # 保护 apply/revert 的幂等检查与状态写入，避免并发重复应用。
        self._lock = threading.RLock()

    def _record_undo(self, target: str) -> None:
        """在改动目标前记录 undo 点（仅在事务上下文中生效）。"""
        if not self._tx_stack:
            return
        current_object = _ADDED  # 目标不存在时用它标记“改动前无此属性”
        try:
            module, _sep, attr_path = target.partition(":")
            module_obj = __import__(module, fromlist=["*"])
            _parent, _attr, current_object = resolve_path(module_obj, attr_path)
        except Exception:  # pragma: no cover - 目标尚不存在时无快照
            pass
        existing = self._applied.get(target)
        if existing is not None:
            part = existing.spec.property_part
        else:
            part = next((s.property_part for s in self.specs if s.target == target), "get")
        self._tx_stack[-1].append(_UndoPoint(target, existing, current_object, property_part=part))

    # ------------------------------------------------------------------ owner 阻塞 / 事件

    def block_owner(self, owner: str) -> None:
        """阻塞某 owner：被阻塞者不再参与目标选择（幂等）。"""
        with self._lock:
            self._blocked_owners.add(owner)

    def unblock_owner(self, owner: str) -> bool:
        """解除阻塞，返回此前是否处于阻塞状态。"""
        with self._lock:
            if owner in self._blocked_owners:
                self._blocked_owners.discard(owner)
                return True
            return False

    def is_blocked(self, owner: str) -> bool:
        return owner in self._blocked_owners

    def add_listener(self, listener: Callable[[str, dict], None]) -> Callable[[], None]:
        """注册事件监听器，返回取消注册函数。

        事件类型：apply / revert / reject，detail 含 target/owner 等信息。
        """
        with self._lock:
            self._listeners.append(listener)

        def remove() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return remove

    def _emit(self, event: Literal["apply", "revert", "reject"], detail: dict) -> None:
        """通知监听器；单个监听器异常不影响补丁主流程。"""
        for listener in list(self._listeners):
            try:
                listener(event, detail)
            except Exception as exc:  # pragma: no cover - 防御性
                logger.warning("事件监听器处理 %s 失败：%s", event, exc)

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

    def revert_where(
        self,
        *,
        owner: str | None = None,
        tags: tuple[str, ...] = (),
        module: str | None = None,
    ) -> list[str]:
        """按条件批量回滚已应用补丁，返回成功回滚的 target 列表。

        owner / tags / module 同时给出时取交集；都不给等价于 revert_all()。
        """
        matched: list[str] = []
        for target, applied in list(self._applied.items()):
            spec = applied.spec
            if owner is not None and spec.owner != owner:
                continue
            if tags and not (set(tags) & set(spec.tags)):
                continue
            if module is not None and spec.target_module != module:
                continue
            matched.append(target)
        reverted: list[str] = []
        for target in matched:
            if self.revert(target):
                reverted.append(target)
        return reverted

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

        # 被阻塞的 owner 不参与选择（pluggy.set_blocked 语义）
        if owner in self._blocked_owners:
            logger.warning("owner=%s 已被阻塞，跳过目标 %s", owner, target)
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

    # ------------------------------------------------------------------ 拒绝处理

    def _reject(
        self,
        reason: str,
        target: str,
        owner: str,
        report: AuditReport | None,
        exc_type: type[Exception] = PatchRejectedError,
    ) -> bool:
        """统一记录一次拒绝：审计 + 日志 + 事件 + strict 模式下抛异常。"""
        self._emit("reject", {"target": target, "owner": owner, "reason": reason})
        if report is not None:
            report.rejections.append(
                {"owner": owner, "target": target, "reason": reason, "at": _timestamp()}
            )
        logger.error("补丁拒绝 owner=%s target=%s：%s", owner, target, reason)
        if self.strict:
            if exc_type is PatchRejectedError:
                raise PatchRejectedError(target, reason)
            if exc_type is PathResolutionError:
                raise PathResolutionError(f"解析目标 {target} 失败：{reason}")
            if exc_type is TargetNotFoundError:
                raise TargetNotFoundError(f"owner={owner or '(none)'} 未注册目标 {target}")
            if exc_type is ConflictError:
                raise ConflictError(reason)
            raise exc_type(reason)
        return False

    # ------------------------------------------------------------------ 应用

    def apply(self, target: str, report: AuditReport | None = None) -> bool:
        """应用目标补丁（线程安全）。模块必须已导入（由 loader 保证）。"""
        with self._lock:
            return self._apply_locked(target, report)

    def _apply_add(
        self,
        target: str,
        chosen: PatchSpec,
        module: str,
        attr_path: str,
        report: AuditReport | None,
    ) -> bool:
        """添加原本不存在的属性/方法（mode='add'）。

        attr_path 支持点分路径（如 ``Settings.new_method``）；解析父对象后
        确认最终属性尚不存在，避免静默覆盖主分支已有实现。
        """
        try:
            module_obj = __import__(module, fromlist=["*"])
            parent_path, _sep, final_attr = attr_path.rpartition(".")
            if parent_path:
                # resolve_path 返回 (父对象, 属性名, 值)；新属性挂到解析出的值上。
                _holder, _attr, parent = resolve_path(module_obj, parent_path)
                if parent is None:
                    return self._reject(
                        f"add parent not found: {parent_path}",
                        target,
                        chosen.owner,
                        report,
                        PathResolutionError,
                    )
            else:
                parent = module_obj
        except Exception as exc:
            return self._reject(
                f"resolve parent failed: {exc}", target, chosen.owner, report, PathResolutionError
            )

        # 目标属性必须原本不存在；存在则拒绝，避免覆盖主分支实现。
        if hasattr(parent, final_attr):
            return self._reject(
                f"add target already exists: {attr_path}",
                target,
                chosen.owner,
                report,
                ConflictError,
            )

        ok, reason = claim_target(
            target,
            chosen.owner,
            self,
            lambda: is_patched(target),
            property_part=chosen.property_part,
        )
        if not ok:
            return self._reject(reason, target, chosen.owner, report, ConflictError)

        try:
            mark_replacement(chosen.replacement, chosen.owner, target)
            wrapt.apply_patch(parent, final_attr, chosen.replacement)
            self._applied[target] = _Applied(chosen, parent, final_attr, _ADDED, chosen.replacement)
        except Exception as exc:
            release_target(target, self, property_part=chosen.property_part)
            return self._reject(f"add failed: {exc}", target, chosen.owner, report)

        if report:
            report.entries.append({"owner": chosen.owner, "target": target, "at": _timestamp()})
        self._emit("apply", {"target": target, "owner": chosen.owner})
        logger.info("补丁已应用（add）：target=%s owner=%s", target, chosen.owner)
        return True

    def _apply_locked(self, target: str, report: AuditReport | None) -> bool:
        if target in self._applied:
            return True  # 幂等
        self._record_undo(target)

        if not self.config.enabled:
            return self._reject("disabled", target, self.config.owner_for(target) or "", report)

        chosen, skipped = self.select(target)
        if chosen is None:
            owner = self.config.owner_for(target)
            return self._reject(
                "no selected owner",
                target,
                owner or "",
                report,
                TargetNotFoundError if owner else PatchRejectedError,
            )
        if report:
            for owner in skipped:
                report.conflicts.append(
                    {
                        "target": target,
                        "chosen": chosen.owner,
                        "skipped": owner,
                        "at": _timestamp(),
                    }
                )

        module, _sep, attr_path = target.partition(":")

        if chosen.mode == "add":
            # 添加原本不存在的属性/方法：解析父对象，确认属性尚不存在再安装。
            return self._apply_add(target, chosen, module, attr_path, report)

        try:
            module_obj = __import__(module, fromlist=["*"])
            parent, attr, original = resolve_path(module_obj, attr_path)
        except Exception as exc:
            return self._reject(
                f"resolve failed: {exc}", target, chosen.owner, report, PathResolutionError
            )

        # 描述符（classmethod/staticmethod/property）取底层函数做版本校验与包装
        raw_original = unwrap_descriptor(original, chosen.property_part)
        if raw_original is None or not callable(raw_original):
            return self._reject(
                f"target has no callable for part {chosen.property_part!r}",
                target,
                chosen.owner,
                report,
                PathResolutionError,
            )
        if isinstance(original, property):
            _baseline_property(target, original)

        # 版本校验：主分支函数被改过则拒绝应用，避免静默失效
        if chosen.expect_hash:
            actual = source_hash(raw_original)
            if actual != chosen.expect_hash:
                reason = f"hash mismatch: expect={chosen.expect_hash} actual={actual}"
                return self._reject(reason, target, chosen.owner, report)

        # 依赖闭包校验：目标调用的 helper / 类改过时也拒绝，避免静默跑在旧假设上。
        if chosen.expect_deps_hash:
            actual_deps = dependency_hash(raw_original)
            if actual_deps != chosen.expect_deps_hash:
                reason = (
                    f"dependency hash mismatch: expect={chosen.expect_deps_hash} "
                    f"actual={actual_deps}"
                )
                return self._reject(reason, target, chosen.owner, report)

        # 部署包版本约束：不满足则拒绝应用（与 expect_hash 同级护栏）
        if chosen.requires:
            from ._requirements import check_requires

            problems = check_requires(chosen.requires)
            if problems:
                return self._reject("; ".join(problems), target, chosen.owner, report)

        # 废弃目标告警（不阻断）
        if chosen.deprecated:
            import warnings

            from .exceptions import DeprecatedTargetWarning

            warnings.warn(
                f"deprecated patch target {target}: {chosen.deprecated}",
                DeprecatedTargetWarning,
                stacklevel=2,
            )

        # 进程级占用检查：把"单一生效"从单实例提升到整个进程。
        # 安装前先声明占用，若已有其它 Registry 存活并占用该目标则拒绝，
        # 避免后 apply 的补丁静默覆盖前者。
        ok, reason = claim_target(
            target,
            chosen.owner,
            self,
            lambda: is_patched(target),
            property_part=chosen.property_part,
        )
        if not ok:
            return self._reject(reason, target, chosen.owner, report, ConflictError)

        from ._suppression import wrap_enabled

        effective_enabled = wrap_enabled(chosen.enabled)

        try:
            if chosen.mode == "wrap":
                # wrapt 原生支持 enabled（bool / callable，每次调用时求值）
                wrapper = wrapt.FunctionWrapper(
                    raw_original, chosen.replacement, enabled=effective_enabled
                )
                mark_replacement(wrapper, chosen.owner, target)
                to_install = wrap_with_descriptor(original, wrapper, chosen.property_part)
                wrapt.apply_patch(parent, attr, to_install)
                # 描述符包裹后 wrapper 不在 resolve_path 的 __wrapped__ 链上，
                # 因此只有普通函数才保存 handle 供 unwrap_object 使用。
                handle = None if is_descriptor(original) else wrapper
                self._applied[target] = _Applied(
                    chosen, parent, attr, original, raw_original, handle
                )
            else:  # replace
                # replace 无 wrapt 包装层，用 dispatcher 实现同等 enabled 语义；
                # effective_enabled 始终把上下文抑制纳入判定。
                impl = make_dispatcher(chosen.replacement, raw_original, effective_enabled)
                mark_replacement(impl, chosen.owner, target)
                to_install = preserve_descriptor(original, impl, chosen.property_part)
                wrapt.apply_patch(parent, attr, to_install)
                self._applied[target] = _Applied(chosen, parent, attr, original, raw_original)
        except Exception as exc:
            release_target(target, self, property_part=chosen.property_part)
            return self._reject(f"apply failed: {exc}", target, chosen.owner, report)

        if report:
            entry: dict[str, Any] = {
                "owner": chosen.owner,
                "target": target,
                "at": _timestamp(),
            }
            from .discovery import get_spec_origin

            origin = get_spec_origin(chosen)
            if origin:
                entry["origin"] = origin
            report.entries.append(entry)
        self._emit("apply", {"target": target, "owner": chosen.owner, "mode": chosen.mode})
        logger.info("补丁已生效：owner=%s target=%s mode=%s", chosen.owner, target, chosen.mode)
        return True

    def apply_module(self, module_name: str, report: AuditReport | None = None) -> int:
        """应用某模块下的所有目标，返回成功应用数量。"""
        count = 0
        for spec in self.specs_for_module(module_name):
            if self.apply(spec.target, report):
                count += 1
        return count

    def apply_all(self, targets: list[str], report: AuditReport | None = None) -> ApplyResult:
        """批量应用；任一失败则只回滚本次新应用项，先前已应用的不受影响。"""
        result = ApplyResult()
        newly_applied: list[str] = []
        with self._lock:
            for target in targets:
                if target in self._applied:
                    # 已经存在：保留原状，不做任何回滚/记录为本次成功。
                    result.preexisting.append(target)
                    continue
                # 记录本次 apply 前的 rejection 数量，失败时只取本次新增的原因，
                # 避免误报之前其它目标留下的 rejection。
                rejections_before = len(report.rejections) if report is not None else 0
                try:
                    ok = self._apply_locked(target, report)
                except Exception as exc:  # strict 模式下抛出的领域异常
                    result.failed.append((target, str(exc)))
                    break
                if ok:
                    newly_applied.append(target)
                    result.applied.append(target)
                else:
                    if report is not None and len(report.rejections) > rejections_before:
                        reason = report.rejections[-1]["reason"]
                    else:
                        reason = "apply returned False"
                    result.failed.append((target, reason))
                    break

            if result.failed:
                # 只撤销本次真正新建的补丁；回滚失败的仍留在 applied 中。
                for target in reversed(newly_applied):
                    if self._revert_locked(target):
                        result.rolled_back.append(target)
                        result.applied.remove(target)
                    else:
                        result.failed.append((target, "rollback failed"))
        return result

    @contextmanager
    def transaction(self) -> Generator[Registry, None, None]:
        """事务上下文：块内对目标的改动在异常时恢复到进入该操作前的状态。

        内部每次 apply/revert 前都会记录 undo 点（见 _record_undo），
        异常时逆序回放，因此块内对同一目标的 revert→reapply 也能正确回退。
        支持嵌套：内层异常回放到内层开始处，外层继续持有自己的 undo 栈。
        """
        self._tx_stack.append([])
        try:
            yield self
        except BaseException:
            undo_log = self._tx_stack[-1]
            with self._lock:
                for point in reversed(undo_log):
                    target = point.target
                    current = self._applied.get(target)
                    if point.current_object is _ADDED:
                        # 改动前目标不存在（add 模式）：回放时删除已添加的属性。
                        # undo 点记录于 apply 之前，point.applied 可能为 None，
                        # 此时从目标字符串解析父对象与最终属性名。
                        try:
                            if current is not None:
                                delattr(current.parent, current.attr)
                            elif point.applied is not None:
                                delattr(point.applied.parent, point.applied.attr)
                            else:
                                module_name, _sep, attr_path = target.partition(":")
                                parent_path, _dot, final_attr = attr_path.rpartition(".")
                                module_obj = __import__(module_name, fromlist=["*"])
                                if parent_path:
                                    _holder, _attr, owner_obj = resolve_path(
                                        module_obj, parent_path
                                    )
                                else:
                                    owner_obj = module_obj
                                if hasattr(owner_obj, final_attr):
                                    delattr(owner_obj, final_attr)
                        except AttributeError:
                            pass
                    elif point.current_object is not None:
                        # 把目标属性恢复为改动前的实际对象（用 resolve_owner 定位定义处）
                        try:
                            owner, attr, _cur = resolve_owner(
                                point.applied.parent
                                if point.applied
                                else __import__(target.partition(":")[0], fromlist=["*"]),
                                target.partition(":")[2],
                            )
                            wrapt.apply_patch(owner, attr, point.current_object)
                        except Exception:  # pragma: no cover
                            pass
                    # 恢复 Registry 记录
                    if point.applied is None:
                        self._applied.pop(target, None)
                        release_target(target, self, property_part=point.property_part)
                        self._cleanup_property_baseline(target)
                    else:
                        self._applied[target] = point.applied
                        claim_target(
                            target,
                            point.applied.spec.owner,
                            self,
                            lambda t=target: is_patched(t),
                            property_part=point.applied.spec.property_part,
                        )
            raise
        finally:
            self._tx_stack.pop()

    # ------------------------------------------------------------------ 回滚

    def revert(self, target: str, *, missing_ok: bool = True) -> bool:
        """回滚目标补丁（线程安全）。"""
        with self._lock:
            return self._revert_locked(target, missing_ok=missing_ok)

    def _revert_locked(self, target: str, *, missing_ok: bool = True) -> bool:
        applied = self._applied.get(target)
        if applied is None:
            # 没有可回滚的补丁时返回 False（表示"未回滚"）；strict 模式下按 missing_ok
            # 决定是否为调用方抛错，便于批处理把"目标不存在"当异常对待。
            if self.strict and not missing_ok:
                raise TargetNotFoundError(f"目标 {target} 未应用补丁，无法回滚")
            return False

        self._record_undo(target)
        try:
            if applied.spec.mode == "add":
                # add 模式：属性原本不存在，直接删除（记录被事务回放时保留原对象）。
                if applied.original is _ADDED:
                    delattr(applied.parent, applied.attr)
                else:
                    wrapt.apply_patch(applied.parent, applied.attr, applied.original)
            elif applied.spec.mode == "wrap" and applied.handle is not None:
                module, _sep, attr_path = target.partition(":")
                module_obj = __import__(module, fromlist=["*"])
                # 普通函数：用 handle 身份匹配，保留其上方的第三方包装。
                unwrap_object(module_obj, attr_path, applied.handle, missing_ok=False)
            else:
                # replace 模式与描述符 wrap 模式：用 resolve_owner 定位真正定义处，
                # 直接恢复安装前保存的属性，避免留下影子副本。
                owner, attr, current = resolve_owner(applied.parent, applied.attr)
                part = applied.spec.property_part
                baseline = None
                if isinstance(applied.original, property) or isinstance(current, property):
                    with _BASELINE_LOCK:
                        baseline = _BASELINE_PROPERTIES.get(target)
                if baseline is not None and isinstance(current, property):
                    # 只恢复本补丁拥有的那一部分，且取“首次打补丁前”的原始函数：
                    #   - 不清掉别的 owner 打在其它 part 上的补丁；
                    #   - 不把 prior 快照里的旧补丁“复活”。
                    saved_func = unwrap_descriptor(baseline, part)
                    if saved_func is not None:
                        to_restore = preserve_descriptor(current, saved_func, part)
                        wrapt.apply_patch(owner, attr, to_restore)
                    else:
                        wrapt.apply_patch(owner, attr, applied.original)
                else:
                    wrapt.apply_patch(owner, attr, applied.original)
        except Exception as exc:
            # 失败时保留记录，允许后续重试；不能让原始实现永久失联。
            logger.warning("回滚补丁 %s 失败：%s", target, exc)
            return False

        del self._applied[target]
        release_target(target, self, property_part=applied.spec.property_part)
        self._cleanup_property_baseline(target)
        self._emit("revert", {"target": target, "owner": applied.spec.owner})
        logger.info("补丁已回滚：target=%s", target)
        return True

    @staticmethod
    def _cleanup_property_baseline(target: str) -> None:
        """当 property 所有 part 都已释放时，清除基线并恢复完整原始 property。"""
        with _BASELINE_LOCK:
            baseline = _BASELINE_PROPERTIES.get(target)
            if baseline is None:
                return
            # 任一 part 仍占用则保留基线，供后续回滚使用。
            for part in ("get", "set", "delete"):
                key = claim_key(target, part)
                if key in claims_snapshot():
                    return
            del _BASELINE_PROPERTIES[target]
        # 没有引用了，恢复完整原始 property（无需重新加锁）
        module, _sep, attr_path = target.partition(":")
        try:
            owner, attr, _cur = resolve_owner(__import__(module, fromlist=["*"]), attr_path)
            wrapt.apply_patch(owner, attr, baseline)
        except Exception as exc:  # pragma: no cover
            logger.warning("恢复 property 基线 %s 失败：%s", target, exc)

    def revert_all(self) -> int:
        count = 0
        for target in list(self._applied):
            if self.revert(target):
                count += 1
        return count

    def get_original(self, target: str) -> Callable[..., Any] | None:
        """返回被替换的原始函数（底层 callable），供补丁内部复用原逻辑。

        对 classmethod/staticmethod/property 返回其底层函数，而不是 None。
        """
        applied = self._applied.get(target)
        if applied is None:
            return None
        return applied.raw_original

    def get_wrapper(self, target: str) -> Any | None:
        """返回当前生效的包装器/替代函数（wrapt 链首），未应用返回 None。"""
        applied = self._applied.get(target)
        if applied is None:
            return None
        # 描述符包裹后链首在描述符内；静态读取属性，避免触发 property getter。
        current = get_attribute(applied.parent, applied.attr)
        return unwrap_descriptor(current, applied.spec.property_part)

    def is_applied(self, target: str) -> bool:
        return target in self._applied

    # ------------------------------------------------------------------ 预演

    def plan(self, *, include_diff: bool = False) -> list[dict[str, Any]]:
        """预演每个目标会做什么，不修改注册表中的任何补丁状态。

        注意：校验目标 hash 需要 import 目标模块；若该模块尚未导入，
        import 本身可能触发已注册的后导入钩子（由 wrapt 管理）。
        返回项含 target / owner / selected / would_apply / reason。

        include_diff=True 时，额外为 replace 模式的补丁生成 unified diff，
        展示"这个函数会被改成什么样"。wrap 模式是运行时拦截而非替换函数体，
        不生成 diff 以免误导。
        """
        from ._claims import can_claim
        from .validation import validate_spec

        plans: list[dict[str, Any]] = []
        for target in self.targets():
            chosen, skipped = self.select(target)
            entry: dict[str, Any] = {
                "target": target,
                "owner": self.config.owner_for(target),
                "selected": chosen.owner if chosen else None,
                "skipped": skipped,
                "would_apply": False,
                "reason": "",
            }
            if chosen is not None:
                entry["mode"] = chosen.mode
            if include_diff and chosen is not None and chosen.mode == "replace":
                entry["diff"] = self._preview_diff(chosen)
            if not self.config.enabled:
                entry["reason"] = "disabled"
            elif chosen is None:
                entry["reason"] = "no selected owner"
            elif self.is_applied(target):
                # 与 apply() 的幂等行为一致：已应用目标预演为“无需再应用”。
                entry["would_apply"] = True
                entry["reason"] = "already applied"
            else:
                ok, reason = can_claim(
                    target,
                    self,
                    property_part=chosen.property_part,
                    is_still_patched=lambda t=target: is_patched(t),
                )
                if not ok:
                    # 陈旧占用：can_claim 用通用文案，这里补全 owner 便于诊断
                    entry["reason"] = reason
                else:
                    result = validate_spec(chosen)
                    entry["would_apply"] = result.ok
                    entry["reason"] = "; ".join(result.problems)
            plans.append(entry)
        return plans

    def _preview_diff(self, spec: PatchSpec) -> str:
        """生成单条 replace 补丁的 unified diff；无法取源码时返回空串。"""
        from ._diff import render_diff, source_of

        try:
            module_obj = __import__(spec.target_module, fromlist=["*"])
            _parent, _attr, original = resolve_path(module_obj, spec.target_attr)
        except Exception:
            return ""
        raw = unwrap_descriptor(original, spec.property_part)
        if raw is None:
            return ""
        return render_diff(source_of(raw), source_of(spec.replacement), spec.target)
