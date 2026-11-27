"""描述符安全自省：属性不存在与只读 property。"""

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
    introspection,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_get_attribute_searches_mro_and_reports_missing():
    """沿 MRO 查找继承属性；类上确实没有时抛带类型名的 AttributeError。"""

    class Base:
        inherited = 1

    class Mid(Base):
        pass

    class Child(Mid):
        pass

    assert introspection.get_attribute(Child, "inherited") == 1
    with pytest.raises(AttributeError, match="Child"):
        introspection.get_attribute(Child, "missing_attr")


def test_get_base_unwraps_bound_method():
    class Holder:
        def method(self):
            return 1

    bound = Holder().method
    base = introspection.get_base(bound)
    assert base is Holder.method


def test_get_attribute_missing_raises_info():
    with pytest.raises(AttributeError, match="no_such"):
        introspection.get_attribute(_target, "no_such_attr")


def test_introspection_get_base_readonly_property():
    class ReadOnly:
        @property
        def value(self):
            return 1

    base = introspection.get_base(ReadOnly.value)
    assert callable(base)


def test_get_wrapper_property_does_not_call_getter():
    calls: list[int] = []

    class Probe:
        @property
        def value(self):
            calls.append(1)
            return "original"

    import sys

    sys.modules["_probe_introspection"] = type(sys)("_probe_introspection")
    sys.modules["_probe_introspection"].Probe = Probe
    spec = PatchSpec("a", "_probe_introspection", "Probe.value", lambda self: "patched")
    reg = _reg([spec])
    reg.apply("_probe_introspection:Probe.value")
    try:
        assert callable(reg.get_wrapper("_probe_introspection:Probe.value"))
        assert calls == []
    finally:
        reg.revert_all()
        clear_all()
        sys.modules.pop("_probe_introspection", None)
