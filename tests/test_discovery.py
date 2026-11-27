"""发现机制测试：目录扫描、filter、entry point、去重。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.metadata as metadata  # noqa: E402

from funcpatch import PatchSpec  # noqa: E402
from funcpatch.discovery import (  # noqa: E402
    discover_all,
    discover_from_directory,
    discover_from_entry_points,
)


def test_discover_from_directory_init():
    specs = discover_from_directory("funcpatch_demo_patches")
    assert any(s.owner == "client_a" for s in specs)
    assert any(s.owner == "client_b" for s in specs)


def test_discover_missing_package():
    specs = discover_from_directory("definitely_not_a_real_patch_package_xyz")
    assert specs == []


def test_discover_filter():
    specs = discover_from_directory(
        "funcpatch_demo_patches", filter_fn=lambda s: s.owner == "client_a"
    )
    assert specs and all(s.owner == "client_a" for s in specs)


def test_discover_from_entry_points(monkeypatch):
    spec = PatchSpec("ep_owner", "m", "a", lambda: None)

    class FakeEP:
        name = "fake"

        @staticmethod
        def load():
            return spec

    monkeypatch.setattr(metadata, "entry_points", lambda group=None: [FakeEP()])
    specs = discover_from_entry_points("any_group")
    assert len(specs) == 1 and specs[0].owner == "ep_owner"


def test_discover_entry_point_callable(monkeypatch):
    spec = PatchSpec("callable_owner", "m", "a", lambda: None)

    class FakeEP:
        name = "fake"

        @staticmethod
        def load():
            return lambda: [spec]

    monkeypatch.setattr(metadata, "entry_points", lambda group=None: [FakeEP()])
    specs = discover_from_entry_points("any_group")
    assert len(specs) == 1 and specs[0].owner == "callable_owner"


def test_discover_entry_point_bad_payload(monkeypatch):
    class FakeEP:
        name = "bad"

        @staticmethod
        def load():
            return "not a patch spec"

    monkeypatch.setattr(metadata, "entry_points", lambda group=None: [FakeEP()])
    assert discover_from_entry_points("any_group") == []


def test_discover_entry_point_load_error(monkeypatch):
    class FakeEP:
        name = "broken"

        @staticmethod
        def load():
            raise RuntimeError("boom")

    monkeypatch.setattr(metadata, "entry_points", lambda group=None: [FakeEP()])
    assert discover_from_entry_points("any_group") == []


def test_discover_all_filter_applies_to_entry_points(monkeypatch):
    """discover_all 的 filter_fn 同样过滤 entry point 来源的 spec。"""
    spec = PatchSpec("ep_owner", "m", "a", lambda: None)

    class FakeEP:
        name = "fake"

        @staticmethod
        def load():
            return spec

    monkeypatch.setattr(metadata, "entry_points", lambda group=None: [FakeEP()])
    assert any(s.owner == "ep_owner" for s in discover_all("no_such_pkg_xyz", "any_group"))
    filtered = discover_all(
        "no_such_pkg_xyz", "any_group", filter_fn=lambda s: s.owner != "ep_owner"
    )
    assert all(s.owner != "ep_owner" for s in filtered)


def test_discover_from_directory_default_scans_plain_submodule(tmp_path, monkeypatch):
    """默认（非递归）扫描应发现包下的普通子模块。"""
    import sys

    pkg_dir = tmp_path / "scan_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "mod.py").write_text(
        "from funcpatch import PatchSpec\np = PatchSpec('scan_owner', 'm', 'f', lambda: None)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("scan_pkg", "scan_pkg.mod"):
        sys.modules.pop(name, None)
    try:
        specs = discover_from_directory("scan_pkg")
        assert any(s.owner == "scan_owner" for s in specs)
    finally:
        for name in ("scan_pkg", "scan_pkg.mod"):
            sys.modules.pop(name, None)


def test_discover_all_dedup(monkeypatch):
    # 目录扫描与 entry point 返回同一个 spec → 只保留一个
    import importlib

    from funcpatch.discovery import _collect_specs

    pkg = importlib.import_module("funcpatch_demo_patches")
    shared = _collect_specs(pkg)[0]

    class FakeEP:
        name = "dup"

        @staticmethod
        def load():
            return shared

    monkeypatch.setattr(metadata, "entry_points", lambda group=None: [FakeEP()])
    specs = discover_all("funcpatch_demo_patches", "any_group")
    assert len([s for s in specs if s.owner == shared.owner and s.target == shared.target]) == 1
