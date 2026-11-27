"""进程级目标占用表：把"单一生效"从单个 Registry 提升到整个进程。

背景：Registry 内的 _applied 只能防止同一实例重复应用。若代码里创建了两个
Registry 实例（例如两次 bootstrap 用不同配置），它们都能 patch 同一目标，
后apply 的会静默覆盖前者，违反 funcpatch 的核心不变式。

这里用弱引用记录"哪个 Registry 占用了哪个目标"：
  * 两个都存活的实例 → 第二个被拒绝并记冲突；
  * 实例已释放但补丁仍在 → 也拒绝（提示先恢复，不留后门）；
  * 实例已释放且补丁已不在 → 视为陈旧记录，允许新实例接管。
"""

from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class _Claim:
    owner: str
    registry: weakref.ReferenceType[Any]
    key: str


_LOCK = threading.RLock()
_CLAIMS: dict[str, _Claim] = {}


def claim_key(target: str, property_part: str = "get") -> str:
    """占用键：property 的 get/set/delete 视为不同目标。"""
    return f"{target}#{property_part}" if property_part != "get" else target


def can_claim(
    target: str,
    registry: Any,
    *,
    property_part: str = "get",
    is_still_patched: Callable[[], bool] | None = None,
    owner: str = "",
) -> tuple[bool, str]:
    """只读判定 registry 能否占用目标，不修改任何状态。

    供 plan() 复用 apply() 的同一套判定，避免出现"plan 说能应用、apply 却拒绝"。
    owner 为当前申请方，用于生成与 claim_target 一致的冲突说明。
    """
    key = claim_key(target, property_part)
    with _LOCK:
        existing = _CLAIMS.get(key)
        if existing is None:
            return True, ""
        live = existing.registry()
        if live is not None:
            if live is registry:
                return True, ""
            return False, _conflict_reason(existing.owner, owner)
    if is_still_patched is not None and is_still_patched():
        return False, "target has a stale claim and is still patched"
    return True, ""


def _conflict_reason(existing_owner: str, current_owner: str) -> str:
    """生成统一的冲突说明。

    只读判定（can_claim）与实际占用（claim_target）必须给出同样的文案，
    否则同一次冲突在 plan 与 apply 中会呈现为两种不同的原因。
    """
    if current_owner:
        return f"target already claimed by owner={existing_owner}; current owner={current_owner}"
    return f"target already claimed by owner={existing_owner}"


def claim_target(
    target: str,
    owner: str,
    registry: Any,
    is_still_patched: Callable[[], bool],
    *,
    property_part: str = "get",
) -> tuple[bool, str]:
    """尝试占用目标，返回 (是否成功, 失败原因)。

    is_still_patched 在锁外求值（它可能触发 import hook 回调并再次获取锁），
    避免与 Registry 的 RLock 形成锁顺序反转。
    """
    key = claim_key(target, property_part)
    # 先判断 stale 状态：只在可能陈旧时才在锁外调用回调。
    with _LOCK:
        existing = _CLAIMS.get(key)
        live = existing.registry() if existing is not None else None
        stale = existing is not None and live is None

    if stale:
        still_patched = is_still_patched()
    else:
        still_patched = False

    with _LOCK:
        existing = _CLAIMS.get(key)
        if existing is not None:
            live = existing.registry()
            if live is not None and live is not registry:
                return False, _conflict_reason(existing.owner, owner)
            if live is None and still_patched:
                return False, (
                    f"target has a stale claim from owner={existing.owner} "
                    "and is still patched; revert or clear claim first"
                )
        _CLAIMS[key] = _Claim(owner, weakref.ref(registry), key)
        return True, ""


def release_target(target: str, registry: Any, *, property_part: str = "get") -> None:
    """释放自己持有的目标占用；不是自己的记录不动。"""
    key = claim_key(target, property_part)
    with _LOCK:
        existing = _CLAIMS.get(key)
        if existing is not None and existing.registry() is registry:
            del _CLAIMS[key]


def claim_holder(target: str, property_part: str = "get") -> Any | None:
    """返回当前占用该目标的 Registry 实例；无人占用返回 None。

    用于在目标已被别的 Registry 接管时，仍能取到原始实现
    （目标位置上的对象此时已是替代实现，直接取会得到替代实现的源码）。
    """
    key = claim_key(target, property_part)
    with _LOCK:
        existing = _CLAIMS.get(key)
        if existing is None:
            return None
        return existing.registry()


def clear_claim(target: str, *, property_part: str = "get") -> bool:
    """释放任意目标占用（用于陈旧占用的显式恢复），返回是否确实释放。"""
    key = claim_key(target, property_part)
    with _LOCK:
        if key in _CLAIMS:
            del _CLAIMS[key]
            return True
        return False


def claims_snapshot() -> dict[str, dict[str, Any]]:
    """导出当前占用情况，供诊断与恢复。"""
    with _LOCK:
        return {
            key: {"owner": claim.owner, "alive": claim.registry() is not None}
            for key, claim in _CLAIMS.items()
        }


def clear_all() -> None:
    """清空全部占用记录（进程关闭 / 测试隔离）。"""
    with _LOCK:
        _CLAIMS.clear()
