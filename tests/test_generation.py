"""批量补丁生成测试（gorilla.create_patches / find_patches 模式）。"""

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
    create_patches,
    find_patches,
    get_original_attribute,
    patch,
)


def test_create_patches_bulk():
    specs = create_patches("a", "_target", _target.Descriptors, filter_fn=None)
    attrs = {s.target_attr for s in specs}
    assert {"who", "static", "prop"} <= attrs
    assert all(s.owner == "a" for s in specs)
    assert all(s.target_module == "_target" for s in specs)


def test_create_patches_with_filter():
    specs = create_patches("a", "_target", _target.Descriptors, filter_fn=lambda n, v: n == "who")
    assert [s.target_attr for s in specs] == ["who"]


def test_create_patches_shared_replacement():
    def impl(*args, **kwargs):
        return "patched"

    specs = create_patches(
        "a",
        "_target",
        _target.Descriptors,
        replacement=impl,
        filter_fn=lambda n, v: n in ("who", "static"),
    )
    assert len(specs) == 2
    assert all(s.replacement is not None for s in specs)


def test_created_patches_can_be_applied():
    def impl(cls):
        return f"patched-{cls.__name__}"

    specs = create_patches(
        "a",
        "_target",
        _target.Descriptors,
        target_prefix="Descriptors",
        replacement=impl,
        filter_fn=lambda n, v: n == "who",
    )
    reg = Registry(SelectionConfig("a", {}, True), specs)
    assert reg.apply("_target:Descriptors.who") is True
    assert _target.Descriptors.who() == "patched-Descriptors"
    reg.revert("_target:Descriptors.who")


def test_create_patches_bases_traversal():
    class Base:
        def base_method(self): ...

    class Child(Base):
        def child_method(self): ...

    specs = create_patches("a", "_target", Child)
    attrs = {s.target_attr for s in specs}
    assert "base_method" in attrs and "child_method" in attrs


def test_create_patches_traverse_bases_false():
    class Base:
        def base_method(self): ...

    class Child(Base):
        def child_method(self): ...

    specs = create_patches("a", "_target", Child, traverse_bases=False)
    attrs = {s.target_attr for s in specs}
    assert "child_method" in attrs
    assert "base_method" not in attrs


def test_find_patches_from_module():
    @patch("a", "_target", "greet")
    def declared(name):
        return f"patched-{name}"

    import types

    mod = types.ModuleType("fake_mod")
    mod.declared = declared  # type: ignore[attr-defined]
    found = find_patches(mod)
    assert any(s.owner == "a" and s.target_attr == "greet" for s in found)


def test_get_original_attribute_descriptor_safe():
    raw = get_original_attribute(_target.Descriptors, "who")
    assert isinstance(raw, classmethod)


def test_signature_of_created_patch():
    specs = create_patches("a", "_target", _target.Descriptors, filter_fn=None)
    assert all(isinstance(s, PatchSpec) for s in specs)
    assert all(s.mode == "replace" for s in specs)
