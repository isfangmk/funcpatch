"""部署前校验：不修改任何状态，检查补丁能否成功应用。

用于 CI / 发布流水线在真正 bootstrap 之前发现配置错误：
目标不可解析、owner 未命中、hash 不符等问题都能提前暴露。
"""

from __future__ import annotations

import importlib
import inspect
import warnings
from dataclasses import dataclass, field
from typing import Any

import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

from ._descriptors import unwrap_descriptor
from ._requirements import check_requires
from ._targeting import resolve_original
from .exceptions import DeprecatedTargetWarning, FunCPatchWarning
from .spec import PatchSpec, dependency_hash, source_hash


@dataclass
class ValidationResult:
    """单条补丁的校验结果。"""

    spec: PatchSpec
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.spec.owner,
            "target": self.spec.target,
            "ok": self.ok,
            "problems": list(self.problems),
            "warnings": list(self.warnings),
        }


def _resolve_target(spec: PatchSpec) -> tuple[Any, str] | None:
    """解析 (parent, attr)；失败返回 None。"""
    resolve_path = wrapt_patches.resolve_path  # pyright: ignore[reportAttributeAccessIssue]
    try:
        module = __import__(spec.target_module, fromlist=["*"])
    except Exception:
        # 目标模块本身导入失败（缺依赖、环境问题等）：预演应报告解析失败，
        # 而不是让异常中断整批校验。
        return None
    try:
        parent, attr, _original = resolve_path(module, spec.target_attr)
    except Exception:
        return None
    return parent, attr


def _import_error(spec: PatchSpec) -> str | None:
    """尝试导入目标模块，返回失败原因；导入成功返回 None。"""
    try:
        __import__(spec.target_module, fromlist=["*"])
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _check_signature(
    spec: PatchSpec, parent: Any, attr: str, raw: Any, result: ValidationResult
) -> None:
    """完整的签名兼容性检查（借鉴 pluggy._verify_hook / unittest.mock autospec）。

    用 ``signature.bind`` 做真实实参绑定，覆盖参数名、数量、默认值、
    keyword-only 与 positional-only；wrap 模式单独按 wrapt 协议校验。
    不匹配只记录警告并发出 FunCPatchWarning，不阻断部署。
    """
    from .introspection import get_attribute

    repl_sig = inspect.signature(spec.replacement)

    if spec.mode == "wrap":
        # wrapt 协议：(wrapped, instance, args, kwargs)。四参数命名形式最规范；
        # 也接受任意至少 1 个参数（首个接收 wrapped）的非正式 wrapper，
        # 因为 wrapt 支持 *args/**kwargs 等多种写法，严格绑定会误报。
        params = list(repl_sig.parameters.values())
        accepts_many = len(params) >= 4 and all(
            p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
            for p in params[:4]
        )
        has_varargs = any(p.kind is p.VAR_POSITIONAL for p in params)
        if not accepts_many and not has_varargs and len(params) < 1:
            msg = (
                "signature mismatch: wrap replacement must accept the wrapped callable "
                "as its first argument (wrapt protocol: wrapped, instance, args, kwargs)"
            )
            result.warnings.append(msg)
            warnings.warn(msg, FunCPatchWarning, stacklevel=3)
        return

    # replace：用描述符安全的原始函数取签名（classmethod 含 cls、property 含 self）。
    descriptor_or_func = get_attribute(parent, attr)
    raw_for_sig = unwrap_descriptor(descriptor_or_func, spec.property_part) or raw
    target_sig = inspect.signature(raw_for_sig)

    # 生成两组哨兵实参：
    #   - 全位置（POSITIONAL_ONLY / POSITIONAL_OR_KEYWORD 依次进 args）
    #   - 全关键字（POSITIONAL_OR_KEYWORD / KEYWORD_ONLY 进 kwargs）
    # 两组都必须绑定成功才视为兼容：全位置能捕获参数个数问题，
    # 全关键字能捕获参数名不匹配。独立尝试避免 (a, *args) 这类目标
    # 因两组哨兵叠加而被误判。
    sentinel = object()
    target_params = list(target_sig.parameters.values())

    positional_args: list[Any] = []
    for p in target_params:
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            positional_args.append(sentinel)
        elif p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional_args.append(sentinel)

    keyword_kwargs: dict[str, Any] = {}
    for p in target_params:
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            keyword_kwargs["__funcpatch_extra__"] = sentinel
        elif p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            keyword_kwargs[p.name] = sentinel

    # 两种方式都绑定成功才视为完全兼容；任一失败都告警。
    # 这样能捕获参数名不匹配（关键字方式失败），也不误报合理的 *args/**kwargs。
    last_error: TypeError | None = None
    for candidate_args, candidate_kwargs in (
        (positional_args, {}),
        ((), keyword_kwargs),
    ):
        try:
            repl_sig.bind(*candidate_args, **candidate_kwargs)
        except TypeError as exc:
            last_error = exc
            break

    if last_error is not None:
        msg = (
            f"signature mismatch: replacement cannot accept target signature "
            f"{target_sig}: {last_error} (mode={spec.mode})"
        )
        result.warnings.append(msg)
        warnings.warn(msg, FunCPatchWarning, stacklevel=3)


def validate_spec(
    spec: PatchSpec, owner: str | None = None, *, check_signature: bool = False
) -> ValidationResult:
    """校验单条 spec 能否应用。

    owner 为 None 时只做与选择无关的静态检查（目标可解析、hash 匹配）；
    传入 owner 时还会检查该 spec 是否是所选 owner。
    check_signature=True 时用 signature.bind 检查替代实现与目标的参数兼容性
    （参数名、种类、默认值、位置限定/关键字限定），不匹配时记录警告并发
    FunCPatchWarning，不影响 ok。
    """
    result = ValidationResult(spec)

    if owner is not None and spec.owner != owner:
        result.ok = False
        result.problems.append(f"owner mismatch: selected={owner} spec={spec.owner}")

    # 部署包版本约束：不满足则阻断（与 hash 校验同级）。
    for problem in check_requires(spec.requires):
        result.ok = False
        result.problems.append(problem)

    # 废弃目标告警：不阻断，但明确提示迁移。
    if spec.deprecated:
        msg = f"deprecated patch target {spec.target}: {spec.deprecated}"
        result.warnings.append(msg)
        warnings.warn(msg, DeprecatedTargetWarning, stacklevel=2)

    if spec.mode == "add":
        # add 模式要求目标属性原本不存在；验证父对象可解析即可。
        try:
            module_obj = importlib.import_module(spec.target_module)
        except Exception as exc:
            # 目标模块导入失败：报告问题而不是让异常中断整批校验。
            result.ok = False
            result.problems.append(f"target module import failed: {type(exc).__name__}: {exc}")
            return result
        parent_path, _sep, final_attr = spec.target_attr.rpartition(".")
        try:
            if parent_path:
                _holder, _attr, parent = wrapt_patches.resolve_path(module_obj, parent_path)
            else:
                parent = module_obj
        except Exception:
            result.ok = False
            result.problems.append("add target parent resolution failed")
            return result
        if hasattr(parent, final_attr):
            result.ok = False
            result.problems.append(f"add target already exists: {spec.target_attr}")
        return result

    resolved = _resolve_target(spec)
    if resolved is None:
        result.ok = False
        import_error = _import_error(spec)
        if import_error:
            result.problems.append(f"target module import failed: {import_error}")
        else:
            result.problems.append("target resolution failed")
        return result

    parent, attr = resolved
    current = getattr(parent, attr, None)
    raw = unwrap_descriptor(current, spec.property_part)
    if raw is None or not callable(raw):
        result.ok = False
        result.problems.append(f"no callable for part {spec.property_part!r}")
        return result

    # 目标已被某个 Registry 接管时，当前位置上的对象是替代实现，
    # 直接取源码得到的是替代实现的 hash；回溯到原实现再比对。
    raw = resolve_original(spec.target, spec.property_part, raw)

    if spec.expect_hash:
        actual = source_hash(raw)
        if actual != spec.expect_hash:
            result.ok = False
            result.problems.append(f"hash mismatch: expect={spec.expect_hash} actual={actual}")

    if spec.expect_deps_hash:
        actual_deps = dependency_hash(raw)
        if actual_deps != spec.expect_deps_hash:
            result.ok = False
            result.problems.append(
                f"dependency hash mismatch: expect={spec.expect_deps_hash} actual={actual_deps}"
            )

    # 签名兼容性（借鉴 pluggy._verify_hook）：可选、不阻断部署。
    if not check_signature:
        return result

    try:
        _check_signature(spec, parent, attr, raw, result)
    except (ValueError, TypeError):
        # 内置函数等无法取签名时跳过比较，hash 校验仍生效。
        pass

    return result


def validate(
    specs: list[PatchSpec], owner: str | None = None, *, check_signature: bool = False
) -> list[ValidationResult]:
    """批量校验，返回结果列表（不做任何修改）。"""
    return [validate_spec(spec, owner, check_signature=check_signature) for spec in specs]
