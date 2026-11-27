"""依赖闭包 hash：目标 helper 改动时能被发现并拒绝应用。"""

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
    dependency_hash,
    source_hash,
    validate_spec,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs)


def test_dependency_hash_stable_and_differs_from_source_hash():
    h = dependency_hash(_target.with_dependency)
    assert h == dependency_hash(_target.with_dependency)
    assert h != source_hash(_target.with_dependency)
    assert len(h) == 16


def test_dependency_hash_changes_when_helper_changes(monkeypatch):
    before = dependency_hash(_target.with_dependency)
    original = _target._dep_prefix

    def changed():
        return "changed"

    monkeypatch.setattr(_target, "_dep_prefix", changed)
    assert dependency_hash(_target.with_dependency) != before
    monkeypatch.setattr(_target, "_dep_prefix", original)


def test_expect_deps_hash_rejects_when_helper_changed(monkeypatch):
    expected = dependency_hash(_target.with_dependency)
    spec = PatchSpec(
        "a", "_target", "with_dependency", lambda name: "patched", expect_deps_hash=expected
    )
    reg = _reg([spec])

    def changed():
        return "changed"

    monkeypatch.setattr(_target, "_dep_prefix", changed)
    try:
        assert reg.apply(spec.target) is False
        assert _target.with_dependency("x") == "changed-x"
    finally:
        reg.revert_all()
        clear_all()


def test_expect_deps_hash_matching_allows_apply():
    expected = dependency_hash(_target.with_dependency)
    spec = PatchSpec(
        "a", "_target", "with_dependency", lambda name: "patched", expect_deps_hash=expected
    )
    reg = _reg([spec])
    try:
        assert reg.apply(spec.target) is True
        assert _target.with_dependency("x") == "patched"
    finally:
        reg.revert_all()
        clear_all()


def test_validate_reports_dependency_hash_mismatch(monkeypatch):
    expected = dependency_hash(_target.with_dependency)
    spec = PatchSpec(
        "a", "_target", "with_dependency", lambda name: "patched", expect_deps_hash=expected
    )

    def changed():
        return "changed"

    monkeypatch.setattr(_target, "_dep_prefix", changed)
    result = validate_spec(spec)
    assert result.ok is False
    assert any("dependency hash mismatch" in p for p in result.problems)
