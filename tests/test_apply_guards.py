"""应用期护栏：版本约束、废弃告警、strict 异常隔离、陈旧占用接管。"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


import _target  # noqa: E402
import wrapt  # noqa: E402

from funcpatch import (  # noqa: E402
    DeprecatedTargetWarning,
    PatchSpec,
    Registry,
    SelectionConfig,
    bootstrap,
    shutdown,
)
from funcpatch import loader as loader_mod  # noqa: E402
from funcpatch._claims import claims_snapshot, clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_requires_blocks_apply(monkeypatch):
    """requires 不满足时 apply 应拒绝，目标不被改动。"""
    import funcpatch._requirements as req

    monkeypatch.setattr(req, "version", lambda name: "1.0.0")
    reg = _reg([PatchSpec("a", "_target", "greet", lambda n: "x", requires=("wrapt>=999",))])
    assert reg.apply("_target:greet") is False
    assert _target.greet("x") == "hello x"
    clear_all()


def test_deprecated_warns_on_apply():
    """deprecated spec 在 apply 时告警但不阻断。"""
    reg = _reg([PatchSpec("a", "_target", "greet", lambda n: f"p-{n}", deprecated="use v2")])
    with pytest.warns(DeprecatedTargetWarning):
        assert reg.apply("_target:greet") is True
    assert _target.greet("x") == "p-x"
    reg.revert("_target:greet")
    clear_all()


def test_strict_hook_exception_isolated(monkeypatch):
    """strict 下 hook 回调抛领域异常应被隔离，不中断业务 import。"""

    clear_all()
    monkeypatch.setattr(loader_mod, "_REGISTRY", None)
    monkeypatch.setattr(loader_mod, "_REPORT", None)
    monkeypatch.setattr(loader_mod, "_HOOKS", {})

    # hash 故意写错 → strict apply 抛错
    spec = PatchSpec("a", "_target", "greet", lambda name: name, expect_hash="deadbeef")
    bootstrap(config=SelectionConfig("a", {}, True), specs=[spec], strict=True)
    try:
        # 触发 post-import-hook（模块尚未导入时）
        monkeypatch.delitem(sys.modules, "_target", raising=False)
        importlib = __import__("importlib")
        imported = importlib.import_module("_target")
        assert imported.build_headers()["X-Source"] == "original"  # import 未中断，补丁被拒绝
        report = loader_mod._REPORT
        assert report is not None and report.rejections
        assert any("hash" in r.get("reason", "") for r in report.rejections)
    finally:
        shutdown()
        clear_all()


def test_stale_claim_auto_takeover_when_patch_gone():
    """Registry 被 GC 且补丁已恢复时，新 Registry 应能接管陈旧占用。"""
    clear_all()
    original = _target.greet

    def impl(name):
        return f"patched-{name}"

    r1 = _reg([PatchSpec("a", "_target", "greet", impl)])
    assert r1.apply("_target:greet") is True
    del r1
    gc.collect()
    assert "_target:greet" in claims_snapshot()  # stale claim 仍在

    # 手工把目标恢复为原函数（不清 claims）
    wrapt.apply_patch(_target, "greet", original)

    r2 = _reg([PatchSpec("b", "_target", "greet", lambda n: "b")])
    r2.config = SelectionConfig("b", {}, True)
    assert r2.apply("_target:greet") is True
    assert claims_snapshot()["_target:greet"]["owner"] == "b"
    r2.revert("_target:greet")
    clear_all()
