"""plan 预览：替换前后的 unified diff，以及 wrap 模式不生成 diff。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    PatchSpec,
    Registry,
    SelectionConfig,
)
from funcpatch._claims import clear_all  # noqa: E402
from funcpatch._diff import render_diff, source_of  # noqa: E402


def _reg(specs, config=None):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs)


def test_plan_without_diff_has_no_diff_field():
    spec = PatchSpec("a", "_target", "greet", lambda name: f"patched-{name}")
    reg = _reg([spec])
    plan = reg.plan()
    assert "diff" not in plan[0]


def test_plan_entry_reports_mode():
    """plan 条目带 mode，调用方据此说明为何没有 diff。"""
    replace_spec = PatchSpec("a", "_target", "greet", lambda name: f"patched-{name}")

    def wrapper(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    wrap_spec = PatchSpec("a", "_target", "build_headers", wrapper, mode="wrap")
    reg = _reg([replace_spec, wrap_spec])
    plan = {entry["target"]: entry for entry in reg.plan(include_diff=True)}
    assert plan["_target:greet"]["mode"] == "replace"
    assert plan["_target:build_headers"]["mode"] == "wrap"


def test_plan_diff_shows_replacement():
    def replacement(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", replacement)
    reg = _reg([spec])
    plan = reg.plan(include_diff=True)
    diff = plan[0]["diff"]
    assert diff.startswith("--- a/_target:greet")
    assert "+++ b/_target:greet" in diff
    assert "-def greet(name: str) -> str:" in diff
    assert "def replacement(name):" in diff
    assert "patched-" in diff


def test_plan_diff_empty_for_lambda_replacement():
    """lambda 没有有意义的多行源码，diff 为空串而不是报错。"""
    spec = PatchSpec("a", "_target", "greet", lambda name: f"patched-{name}")
    reg = _reg([spec])
    plan = reg.plan(include_diff=True)
    assert plan[0]["diff"] == ""


def test_plan_diff_absent_for_wrap_mode():
    """wrap 是运行时拦截而非替换函数体，不生成 diff 以免误导。"""

    def wrapper(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    spec = PatchSpec("a", "_target", "greet", wrapper, mode="wrap")
    reg = _reg([spec])
    plan = reg.plan(include_diff=True)
    assert "diff" not in plan[0]


def test_plan_diff_empty_when_source_unavailable():
    """目标源码不可取时 diff 为空串，不报错。"""
    spec = PatchSpec("a", "builtins", "len", lambda *a, **k: 0)
    reg = _reg([spec])
    plan = reg.plan(include_diff=True)
    assert plan[0]["diff"] == ""


def test_source_of_returns_none_for_unavailable():
    assert source_of(len) is None
    assert source_of(_target.greet) is not None


def test_render_diff_handles_missing_side():
    assert render_diff(None, "x\n", "t") == ""
    assert render_diff("x\n", None, "t") == ""
    assert "---" in render_diff("a\n", "b\n", "t")
