"""事务边界：无快照回滚与 BaseException 回滚。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    PatchSpec,
    Registry,
    SelectionConfig,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_transaction_no_snapshot_rollback():
    def impl(name):
        return f"p-{name}"

    clear_all()
    reg = Registry(SelectionConfig("a", {}, True), [PatchSpec("a", "_target", "greet", impl)])
    reg.apply("_target:greet")
    # 目标已应用时 undo 点 current_object 非 None，覆盖常规路径；
    # 这里事务内 revert 再 apply，验证 undo 栈能处理。
    with pytest.raises(RuntimeError):
        with reg.transaction():
            reg.revert("_target:greet")
            reg.apply("_target:greet")
            raise RuntimeError("boom")
    assert reg.is_applied("_target:greet")
    reg.revert("_target:greet")
    clear_all()


def test_transaction_rolls_back_on_base_exception():
    """transaction 声明捕获 BaseException，KeyboardInterrupt 也应回滚。"""

    def impl(name):
        return f"patched-{name}"

    reg = _reg([PatchSpec("a", "_target", "greet", impl)])
    reg.apply("_target:greet")
    assert _target.greet("x") == "patched-x"

    with pytest.raises(KeyboardInterrupt):
        with reg.transaction():
            reg.revert("_target:greet")
            raise KeyboardInterrupt()

    # 异常后恢复进入事务时的状态（已打补丁）
    assert _target.greet("x") == "patched-x"
    assert reg.is_applied("_target:greet")
    reg.revert("_target:greet")
    clear_all()
