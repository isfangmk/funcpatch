"""描述符扩展测试：property setter/deleter、wrap 模式描述符回滚、诊断 API。"""

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
    get_wrapper,
    is_patched,
    unwrap_target,
)


def _reg(specs: list[PatchSpec]) -> Registry:
    return Registry(SelectionConfig("a", {}, True), specs)


# ------------------------------------------------------------------ property part


def test_property_setter_only():
    """property_part='set' 只替换 setter，getter 不变。"""

    def new_setter(self, new):
        self._value = f"patched:{new}"

    spec = PatchSpec("a", "_target", "Mutable.value", new_setter, property_part="set")
    reg = _reg([spec])
    assert reg.apply("_target:Mutable.value") is True

    obj = _target.Mutable()
    obj.value = "x"
    assert obj.value == "patched:x"  # getter 走原逻辑
    reg.revert("_target:Mutable.value")
    obj.value = "y"
    assert obj.value == "y"


def test_property_deleter_only():
    """property_part='delete' 只替换 deleter。"""

    def new_deleter(self):
        self._value = "custom-deleted"

    spec = PatchSpec("a", "_target", "Mutable.value", new_deleter, property_part="delete")
    reg = _reg([spec])
    assert reg.apply("_target:Mutable.value") is True

    obj = _target.Mutable()
    del obj.value
    assert obj.value == "custom-deleted"
    reg.revert("_target:Mutable.value")
    obj = _target.Mutable()
    del obj.value
    assert obj.value == "<deleted>"


def test_invalid_property_part():
    with pytest.raises(ValueError):
        PatchSpec("a", "_target", "x", lambda: None, property_part="bogus")  # type: ignore[arg-type]


# ------------------------------------------------------------------ wrap + 描述符回滚


def test_wrap_classmethod_revert():
    """wrap 模式包裹 classmethod 后必须能干净回滚。"""

    def wrapper(original, instance, args, kwargs):
        return original(*args, **kwargs) + "-wrapped"

    spec = PatchSpec("a", "_target", "Descriptors.who", wrapper, mode="wrap")
    reg = _reg([spec])
    assert reg.apply("_target:Descriptors.who") is True
    assert _target.Descriptors.who() == "class-Descriptors-wrapped"
    assert reg.revert("_target:Descriptors.who") is True
    assert _target.Descriptors.who() == "class-Descriptors"


def test_wrap_property_revert():
    def wrapper(original, instance, args, kwargs):
        return original(*args, **kwargs) + "-wrapped"

    spec = PatchSpec("a", "_target", "Descriptors.prop", wrapper, mode="wrap")
    reg = _reg([spec])
    assert reg.apply("_target:Descriptors.prop") is True
    assert _target.Descriptors().prop == "prop-original-wrapped"
    assert reg.revert("_target:Descriptors.prop") is True
    assert _target.Descriptors().prop == "prop-original"


def test_registry_get_wrapper():
    def impl(*args, **kwargs):
        return {"X-Source": "patched"}

    reg = _reg([PatchSpec("a", "_target", "build_headers", impl)])
    reg.apply("_target:build_headers")
    wrapper = reg.get_wrapper("_target:build_headers")
    assert wrapper is not None and callable(wrapper)
    reg.revert("_target:build_headers")


# ------------------------------------------------------------------ 公开诊断 API


def test_get_wrapper_public():
    def impl(*args, **kwargs):
        return {"X-Source": "patched"}

    reg = _reg([PatchSpec("a", "_target", "build_headers", impl)])
    reg.apply("_target:build_headers")
    assert get_wrapper("_target:build_headers") is not None
    assert is_patched("_target:build_headers") is True
    reg.revert("_target:build_headers")


def test_unwrap_public():
    """unwrap 应拆掉 funcpatch 包装并恢复原函数。"""

    def wrapper(original, instance, args, kwargs):
        result = original(*args, **kwargs)
        return {**result, "X-Wrapped": "yes"}

    spec = PatchSpec("a", "_target", "build_headers", wrapper, mode="wrap")
    reg = _reg([spec])
    reg.apply("_target:build_headers")
    assert _target.build_headers()["X-Wrapped"] == "yes"
    assert _target.build_headers()["X-Source"] == "original"

    # 拆包装：这会让 registry 的 handle 失效，所以之后用直接恢复清理。
    unwrap_target("_target:build_headers")
    assert "X-Wrapped" not in _target.build_headers()
    assert _target.build_headers()["X-Source"] == "original"
    reg._applied.clear()  # 避免 conftest 恢复时重复 revert
