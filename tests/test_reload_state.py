"""模块 reload 后的补丁状态：诊断与占用必须反映实际生效情况。

目标模块被 importlib.reload 重建后，旧补丁随旧模块对象一并失效，
但 Registry 的内部记录与进程占用表仍保留着旧状态。此时：

  * is_applied 仍报 True，与实际"补丁已不生效"矛盾；
  * 占用记录仍在，新实例无法接管目标——哪怕旧补丁其实早已失效。

修复后：is_applied 反映实际是否仍生效；占用方补丁失效时，其占用视为陈旧，
新实例可以接管。

使用独立的 _reload_target 模块：reload 会替换模块对象本身，
不能用在其它测试共用的 _target 上。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _reload_target  # noqa: E402

from funcpatch import (  # noqa: E402
    PatchSpec,
    Registry,
    SelectionConfig,
    is_patched,
)
from funcpatch._claims import claims_snapshot, clear_all  # noqa: E402

MODULE = "_reload_target"
TARGET = f"{MODULE}:build_headers"


def _impl(tag: str):
    def impl(cookie: str | None = None) -> dict[str, str]:
        return {"X-Source": tag}

    return impl


def _reg(owner: str, tag: str) -> Registry:
    return Registry(
        SelectionConfig(owner, {}, True),
        [PatchSpec(owner, MODULE, "build_headers", _impl(tag))],
    )


def test_is_applied_reflects_reality_after_reload():
    """reload 后补丁实际失效，is_applied 不应再报 True。"""
    clear_all()
    reg = _reg("a", "patched")
    assert reg.apply(TARGET) is True
    try:
        assert reg.is_applied(TARGET) is True
        assert _reload_target.build_headers()["X-Source"] == "patched"

        importlib.reload(_reload_target)

        # reload 后旧补丁失效
        assert _reload_target.build_headers()["X-Source"] == "original"
        # is_applied 不应再报 True —— 它与实际矛盾
        assert reg.is_applied(TARGET) is False
        assert is_patched(TARGET) is False
    finally:
        reg.revert_all()
        clear_all()
        importlib.reload(_reload_target)


def test_new_registry_can_take_over_after_reload():
    """旧补丁失效后，新实例应能接管目标（占用记录视为陈旧）。"""
    clear_all()
    reg_a = _reg("a", "A")
    assert reg_a.apply(TARGET) is True

    importlib.reload(_reload_target)

    reg_b = _reg("b", "B")
    try:
        assert reg_b.apply(TARGET) is True
        assert _reload_target.build_headers()["X-Source"] == "B"
    finally:
        reg_b.revert_all()
        reg_a.revert_all()
        clear_all()
        importlib.reload(_reload_target)


def test_live_conflict_still_blocked_when_patch_effective():
    """补丁仍实际生效时，冲突必须继续被拦截（不能因修复而放松）。"""
    clear_all()
    reg_a = _reg("a", "A")
    assert reg_a.apply(TARGET) is True

    reg_b = _reg("b", "B")
    try:
        assert reg_b.apply(TARGET) is False
        assert _reload_target.build_headers()["X-Source"] == "A"
        assert TARGET in claims_snapshot()
    finally:
        reg_a.revert_all()
        reg_b.revert_all()
        clear_all()
        importlib.reload(_reload_target)


def test_reapply_after_reload_reinstalls_patch():
    """reload 后再次 apply 应重新安装补丁，而不是谎报成功。

    wrapt 的后导入钩子只在模块首次导入时触发，reload 不会重新触发，
    因此补丁不会自动恢复；再次 apply 必须真正把它装回去。
    """
    clear_all()
    reg = _reg("a", "patched")
    assert reg.apply(TARGET) is True
    try:
        importlib.reload(_reload_target)
        assert _reload_target.build_headers()["X-Source"] == "original"

        # 再次 apply：应真正重新安装
        assert reg.apply(TARGET) is True
        assert _reload_target.build_headers()["X-Source"] == "patched"
        assert reg.is_applied(TARGET) is True

        # 回滚应恢复到新模块的原实现
        assert reg.revert(TARGET) is True
        assert _reload_target.build_headers()["X-Source"] == "original"
    finally:
        reg.revert_all()
        clear_all()
        importlib.reload(_reload_target)


def test_apply_is_idempotent_when_patch_effective():
    """补丁仍生效时重复 apply 应保持幂等，不重复安装。"""
    clear_all()
    reg = _reg("a", "patched")
    try:
        assert reg.apply(TARGET) is True
        first = _reload_target.build_headers
        assert reg.apply(TARGET) is True
        assert _reload_target.build_headers is first
    finally:
        reg.revert_all()
        clear_all()
        importlib.reload(_reload_target)
