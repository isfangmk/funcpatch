"""诊断 API：标记累积、共享实现归属、property 安全解析、包装器查询。"""

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
    get_wrapper,
    unwrap_target,
)
from funcpatch._claims import clear_all  # noqa: E402
from funcpatch._diagnostics import (  # noqa: E402
    PATCH_MARK,
    _resolve_func,  # noqa: F401
    mark_replacement,
)


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_mark_replacement_accumulates_targets():
    def fn():
        pass

    mark_replacement(fn, "a", "t1")
    mark_replacement(fn, "b", "t2")
    mark = getattr(fn, PATCH_MARK)
    assert mark["targets"] == ["t1", "t2"]
    assert mark["owner"] == "a"  # 首个 owner 保留


def test_shared_replacement_info_is_per_target():
    from funcpatch import get_applied_info

    def impl(*args, **kwargs):
        return "shared"

    s1 = PatchSpec("a", "_target", "greet", impl)
    s2 = PatchSpec("a", "_target", "build_headers", impl)
    reg = _reg([s1, s2])
    assert reg.apply("_target:greet") is True
    assert reg.apply("_target:build_headers") is True
    try:
        i1 = get_applied_info("_target:greet")
        i2 = get_applied_info("_target:build_headers")
        assert i1 is not None and i1["target"] == "_target:greet"
        assert i2 is not None and i2["target"] == "_target:build_headers"
    finally:
        reg.revert_all()
        clear_all()


def test_diagnostics_does_not_call_property_getter():
    getter_called = {"n": 0}

    class Probe:
        @property
        def dangerous(self):
            getter_called["n"] += 1
            raise RuntimeError("getter must not run")

    _target.Probe = Probe  # pyright: ignore[reportAttributeAccessIssue]
    assert _resolve_func("_target:Probe.dangerous") is not None
    assert getter_called["n"] == 0


def test_unwrap_replace_mode_returns_current_implementation():
    """replace 模式没有 wrapt 包装链，unwrap 返回当前实现（非 None）。"""

    def impl(name):
        return f"patched-{name}"

    reg = _reg([PatchSpec("a", "_target", "greet", impl)])
    assert reg.apply("_target:greet") is True
    try:
        # replace 模式没有 wrapt 包装链，unwrap/get_wrapper 返回当前生效实现
        # （经 @wraps/dispatcher 处理后可能是副本，故按行为而非身份断言）
        current = unwrap_target("_target:greet")
        assert current is not None
        assert current("x") == "patched-x"
        wrapper = get_wrapper("_target:greet")
        assert wrapper is not None
        assert wrapper("y") == "patched-y"
    finally:
        reg.revert("_target:greet")
        clear_all()


def test_get_wrapper_property_descriptor():
    """描述符目标的 get_wrapper 应返回底层替代函数。"""

    def getter(self):
        return "patched-get"

    reg = _reg(
        [PatchSpec("a", "_target", "Mutable.value", getter, property_part="get", mode="replace")]
    )
    assert reg.apply("_target:Mutable.value") is True
    try:
        wrapper = reg.get_wrapper("_target:Mutable.value")
        assert wrapper is not None

        # 描述符目标的 get_wrapper 返回底层替代函数，按行为断言
        class Obj:
            pass

        assert wrapper(Obj()) == "patched-get"
    finally:
        reg.revert("_target:Mutable.value")
        clear_all()
