"""描述符的 wrap 模式：staticmethod 与 property deleter。"""

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


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_wrap_staticmethod_reverts_cleanly():
    def wrapper(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs) + "-wrapped"

    reg = _reg([PatchSpec("a", "_target", "Descriptors.static", wrapper, mode="wrap")])
    assert reg.apply("_target:Descriptors.static") is True
    try:
        assert _target.Descriptors.static() == "static-original-wrapped"
    finally:
        reg.revert("_target:Descriptors.static")
        clear_all()
    assert _target.Descriptors.static() == "static-original"


def test_wrap_property_delete():
    def deleter(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    reg = _reg(
        [
            PatchSpec(
                "a",
                "_target",
                "Mutable.value",
                deleter,
                mode="wrap",
                property_part="delete",
            )
        ]
    )
    assert reg.apply("_target:Mutable.value") is True
    obj = _target.Mutable()
    del obj.value
    assert obj._value == "<deleted>"
    reg.revert("_target:Mutable.value")
    clear_all()
