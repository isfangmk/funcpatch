"""作用域补丁边界：目标解析失败、禁用开关、多线程占用。"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    PatchSpec,
    Registry,
    SelectionConfig,
    scoped_patch,
    transient_patch,
)
from funcpatch._claims import claims_snapshot, clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_scoped_patch_missing_target_raises_valueerror():
    from funcpatch import PatchSpec

    spec = PatchSpec("a", "_target", "no_such_attr", lambda: None)
    with pytest.raises(ValueError, match="无法解析目标"):
        with scoped_patch("_target", "no_such_attr", spec):
            pass


def test_scoped_patch_disabled_keeps_original():
    def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", impl, enabled=False)
    with scoped_patch("_target", "greet", spec):
        assert _target.greet("x") == "hello x"
    assert _target.greet("x") == "hello x"


def test_transient_claim_held_until_last_thread_exits():
    """多线程并发时，占用应持续到最后一个线程退出。"""
    clear_all()
    entered = threading.Event()
    b_exited = threading.Event()
    release_a = threading.Event()

    def wrapper(wrapped, instance, args, kwargs):
        if threading.current_thread().name == "A":
            entered.set()
            release_a.wait(5)  # A 保持活跃，直到主线程完成断言
        return wrapped(*args, **kwargs)

    spec = PatchSpec("a", "_target", "greet", wrapper, mode="wrap")

    @transient_patch("_target", "greet", spec)
    def call():
        return _target.greet("x")

    def run(name):
        threading.current_thread().name = name
        try:
            call()
        finally:
            if name == "B":
                b_exited.set()

    t1 = threading.Thread(target=run, args=("A",))
    t1.start()
    assert entered.wait(5)  # A 已持有占用
    assert "_target:greet" in claims_snapshot()

    t2 = threading.Thread(target=run, args=("B",))
    t2.start()
    assert b_exited.wait(5)  # B 已退出
    t2.join()
    # A 仍活跃（还在等 release_a），占用不应因 B 退出而提前释放
    assert "_target:greet" in claims_snapshot()

    release_a.set()
    t1.join(5)
    assert not t1.is_alive()
    assert "_target:greet" not in claims_snapshot()
    clear_all()
