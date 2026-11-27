"""测试隔离：每个测试后恢复所有目标模块状态。

funcpatch 修改的是模块级函数/类属性，若测试间不隔离会相互污染。
这里快照并恢复测试中可能触及的全部目标。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402


@pytest.fixture(autouse=True)
def restore_target_state():
    snapshot = {
        "build_headers": _target.build_headers,
        "greet": _target.greet,
        "async_greet": _target.async_greet,
        "async_numbers": _target.async_numbers,
        "Settings.build_headers": _target.Settings.build_headers,
        "Descriptors.who": _target.Descriptors.__dict__["who"],
        "Descriptors.static": _target.Descriptors.__dict__["static"],
        "Descriptors.prop": _target.Descriptors.__dict__["prop"],
        "Mutable.value": _target.Mutable.__dict__["value"],
        "raising_target": _target.raising_target,
        "_dep_prefix": _target._dep_prefix,
        "with_dependency": _target.with_dependency,
    }
    original_keys = set(vars(_target))
    yield
    # 删除测试期间动态注入的属性，避免跨测试残留。
    for name in sorted(set(vars(_target)) - original_keys):
        delattr(_target, name)
    # 描述符用动态 setattr 恢复：静态类型检查器不接受直接给 property 赋值，
    # ruff B010 也不接受常量属性名的 setattr，故把名字放进变量驱动循环。
    plain = (
        "build_headers",
        "greet",
        "async_greet",
        "async_numbers",
        "raising_target",
        "_dep_prefix",
        "with_dependency",
    )
    for name in plain:
        setattr(_target, name, snapshot[name])
    settings_attr = "build_headers"
    setattr(_target.Settings, settings_attr, snapshot["Settings.build_headers"])
    for cls_name, attr in (
        ("Descriptors", "who"),
        ("Descriptors", "static"),
        ("Descriptors", "prop"),
        ("Mutable", "value"),
    ):
        cls = getattr(_target, cls_name)
        setattr(cls, attr, snapshot[f"{cls_name}.{attr}"])


@pytest.fixture(autouse=True)
def reset_loader_state():
    """每个测试后清理 loader 全局状态，避免 bootstrap 幂等影响。"""
    import funcpatch.loader as loader
    from funcpatch._claims import clear_all

    clear_all()
    loader._REGISTRY = None
    loader._REPORT = None
    loader._HOOKS.clear()
    yield
    clear_all()
    loader._REGISTRY = None
    loader._REPORT = None
    loader._HOOKS.clear()
