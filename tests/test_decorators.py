"""装饰式声明：多次叠加、预构造 spec 直通、property_part。"""

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
    decorators,
    patches,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_decorator_stacks_two_specs():
    @decorators.patch("a", "_target", "greet")
    @decorators.patch("b", "_target", "build_headers")
    def impl(*a, **k):
        pass

    specs = vars(impl)["__funcpatch_patches__"]
    assert len(specs) == 2
    assert {s.target for s in specs} == {
        "_target:greet",
        "_target:build_headers",
    }


def test_patches_with_prebuilt_spec():
    prebuilt = PatchSpec("x", "_target", "greet", lambda n: n)

    @decorators.patches([prebuilt])
    def impl(*a, **k):
        pass

    specs = vars(impl)["__funcpatch_patches__"]
    assert specs[0] is prebuilt


def test_patches_decorator_property_part():
    @patches(
        [("a", "_target", "Mutable.value")],
        property_part="set",
    )
    def setter(self, value):
        self._value = f"decorated:{value}"

    specs = vars(setter)["__funcpatch_patches__"]
    assert len(specs) == 1
    assert specs[0].property_part == "set"


def test_decorators_forward_expect_deps_hash():
    """装饰式声明与批量生成都能透传 expect_deps_hash。"""
    from funcpatch.generation import create_patches

    @decorators.patch("a", "_target", "greet", expect_deps_hash="deps-hash")
    def impl(name):
        return name

    specs = vars(impl)["__funcpatch_patches__"]
    assert specs[0].expect_deps_hash == "deps-hash"

    @patches([("a", "_target", "greet")], expect_deps_hash="deps-hash")
    def impl2(name):
        return name

    assert vars(impl2)["__funcpatch_patches__"][0].expect_deps_hash == "deps-hash"

    generated = create_patches("a", "_target", _target.Descriptors, expect_deps_hash="deps-hash")
    assert generated and all(s.expect_deps_hash == "deps-hash" for s in generated)
