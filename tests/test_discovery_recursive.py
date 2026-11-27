"""递归发现与装饰式便利层测试。"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from funcpatch import PatchSpec, collect_patched, discover_from_directory, patch, patches  # noqa: E402
from funcpatch.decorators import PATCH_ATTR  # noqa: E402


def _make_package(name: str) -> types.ModuleType:
    pkg = types.ModuleType(name)
    pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = pkg
    return pkg


def _make_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def test_recursive_discovery_finds_nested(monkeypatch):
    """recursive=True 应发现子包里的补丁。"""
    root = _make_package("recpkg")
    sub = _make_package("recpkg.sub")
    root.__path__ = ["/fake"]  # type: ignore[attr-defined]
    sub.__path__ = []  # type: ignore[attr-defined]

    spec = PatchSpec("r", "m", "a", lambda: None)
    _make_module("recpkg.sub.patches", patch_spec=spec)

    import pkgutil

    monkeypatch.setattr(
        pkgutil,
        "walk_packages",
        lambda paths, prefix="": [types.SimpleNamespace(name="recpkg.sub.patches")],
    )
    monkeypatch.setattr(
        pkgutil,
        "iter_modules",
        lambda paths: [types.SimpleNamespace(name="sub", ispkg=True)],
    )

    found = discover_from_directory("recpkg", recursive=True)
    assert any(s.owner == "r" for s in found)


def test_non_recursive_skips_packages(monkeypatch):
    root = _make_package("flatpkg")
    root.__path__ = ["/fake"]  # type: ignore[attr-defined]

    import pkgutil

    monkeypatch.setattr(
        pkgutil,
        "iter_modules",
        lambda paths: [types.SimpleNamespace(name="sub", ispkg=True)],
    )
    found = discover_from_directory("flatpkg", recursive=False)
    # 只有包自身（无补丁），子包被跳过
    assert found == []


def test_patch_decorator_with_tags():
    @patch("a", "m", "f", tags=("urgent",))
    def impl():
        return 1

    specs = getattr(impl, PATCH_ATTR)
    assert len(specs) == 1
    assert specs[0].tags == ("urgent",)


def test_patches_multi_declaration():
    @patches([("a", "m", "f1"), ("b", "m", "f2")])
    def impl():
        return 1

    specs = getattr(impl, PATCH_ATTR)
    assert len(specs) == 2
    assert {s.target_attr for s in specs} == {"f1", "f2"}


def test_collect_patched_avoids_descriptor_side_effects():
    """collect_patched 用 vars 遍历，不触发 property getter。"""
    calls = []

    class Obj:
        @property
        def dangerous(self):
            calls.append(1)
            return None

    mod = types.ModuleType("mod")
    mod.Obj = Obj  # type: ignore[attr-defined]
    collect_patched(mod)
    assert calls == []  # 没有触发 property
