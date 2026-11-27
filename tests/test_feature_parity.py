"""能力对齐测试：wrapt 桥接、描述符自省、owner 阻塞与事件监听。"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

import funcpatch  # noqa: E402
from funcpatch import (  # noqa: E402
    PatchSpec,
    Registry,
    SelectionConfig,
    decorator,
    default_filter,
    get_attribute,
    get_base,
    get_members,
    lru_cache,
    synchronized,
    unwrapped,
    with_signature,
    wrapper_chain,
)

# ------------------------------------------------------------------ 桥接层完整性


def test_no_export_collisions():
    assert len(funcpatch.__all__) == len(set(funcpatch.__all__))


def test_decorator_passthrough_preserves_signature():
    @decorator
    def my_dec(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs) + "!"

    @my_dec
    def f(x: int) -> str:
        return str(x)

    assert f(3) == "3!"
    # 本文件启用 from __future__ annotations，注解呈字符串形式；只断言参数名保留。
    assert "x" in str(inspect.signature(f))


def test_lru_cache_passthrough():
    calls = []

    @lru_cache()
    def f(x):
        calls.append(x)
        return x * 2

    assert f(3) == 6 and f(3) == 6
    assert len(calls) == 1
    assert hasattr(f, "cache_info") and hasattr(f, "cache_clear")


def test_with_signature_passthrough():
    def impl(*args, **kwargs):
        return sum(args)

    @with_signature(prototype=lambda a, b=2: None)
    def wrapped(*args, **kwargs):
        return impl(*args, **kwargs)

    assert str(inspect.signature(wrapped)) == "(a, b=2)"


def test_wrapper_chain_and_unwrapped():
    @decorator
    def d(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    @d
    def f():
        return 1

    chain = list(wrapper_chain(f))
    assert len(chain) >= 2
    assert unwrapped(f)() == 1


def test_synchronized_passthrough_thread_safe():
    @synchronized
    def add(a, b):
        return a + b

    assert add(1, 2) == 3


# ------------------------------------------------------------------ 描述符安全自省（gorilla 模式）


def test_get_attribute_classmethod_raw():
    raw = get_attribute(_target.Descriptors, "who")
    assert isinstance(raw, classmethod)
    assert callable(raw.__func__)


def test_get_attribute_property_raw():
    raw = get_attribute(_target.Descriptors, "prop")
    assert isinstance(raw, property)


def test_get_base_unwraps_classmethod():
    raw = get_base(_target.Descriptors.__dict__["who"])
    assert callable(raw) and not isinstance(raw, classmethod)


def test_get_members_mro_dedup_sorted():
    class Base:
        def a(self): ...

        def base_only(self): ...

    class Child(Base):
        def a(self): ...  # 覆盖基类

        def z(self): ...

    members = get_members(Child)
    names = [n for n, _ in members]
    assert names == sorted(names)
    assert "a" in names and "base_only" in names and "z" in names
    assert names.count("a") == 1


def test_default_filter():
    assert default_filter("public", 1) is True
    assert default_filter("_private", 1) is False

    import types

    assert default_filter("mod", types.ModuleType("m")) is False


# ------------------------------------------------------------------ owner 阻塞（pluggy 模式）


def _spec(owner="a", attr="build_headers", tag="patched", **kwargs):
    def impl(*args, **kwargs):
        return {"X-Source": tag}

    return PatchSpec(owner, "_target", attr, impl, **kwargs)


def test_block_owner_prevents_apply():
    reg = Registry(SelectionConfig("a", {}, True), [_spec()])
    reg.block_owner(owner="a")
    assert reg.is_blocked("a") is True
    assert reg.apply("_target:build_headers") is False
    assert _target.build_headers()["X-Source"] == "original"


def test_unblock_owner_allows_apply():
    reg = Registry(SelectionConfig("a", {}, True), [_spec()])
    reg.block_owner("a")
    assert reg.unblock_owner("a") is True
    assert reg.unblock_owner("a") is False  # 幂等
    assert reg.apply("_target:build_headers") is True
    reg.revert("_target:build_headers")


def test_blocked_owner_reports_conflict():
    reg = Registry(SelectionConfig("a", {}, True), [_spec("a"), _spec("b", tag="B")])
    reg.block_owner("a")
    chosen, skipped = reg.select("_target:build_headers")
    assert chosen is None
    assert "b" in skipped  # 所有候选都算被跳过


# ------------------------------------------------------------------ 事件监听（pluggy 模式）


def test_listener_receives_apply_and_revert():
    reg = Registry(SelectionConfig("a", {}, True), [_spec()])
    events = []
    reg.add_listener(lambda event, detail: events.append((event, detail)))

    reg.apply("_target:build_headers")
    reg.revert("_target:build_headers")
    assert [e for e, _ in events] == ["apply", "revert"]
    assert events[0][1]["owner"] == "a"


def test_listener_receives_reject():
    reg = Registry(SelectionConfig("a", {}, True), [_spec(expect_hash="bad")])
    events = []
    reg.add_listener(lambda event, detail: events.append(event))
    reg.apply("_target:build_headers")
    assert "reject" in events


def test_listener_removal():
    reg = Registry(SelectionConfig("a", {}, True), [_spec()])
    events = []
    remove = reg.add_listener(lambda event, detail: events.append(event))
    remove()
    reg.apply("_target:build_headers")
    assert events == []
    reg.revert("_target:build_headers")


def test_listener_exception_does_not_break_apply():
    reg = Registry(SelectionConfig("a", {}, True), [_spec()])

    def bad_listener(event, detail):
        raise RuntimeError("listener boom")

    reg.add_listener(bad_listener)
    assert reg.apply("_target:build_headers") is True
    assert _target.build_headers()["X-Source"] == "patched"
    reg.revert("_target:build_headers")


# ------------------------------------------------------------------ 签名校验警告（pluggy 模式）


def test_signature_check_warns_on_mismatch():
    from funcpatch import FunCPatchWarning, validate_spec

    # build_headers(cookie=None) 有 1 个位置参数；replacement 无参数 → 不匹配
    spec = PatchSpec("a", "_target", "build_headers", lambda: None)
    with pytest.warns(FunCPatchWarning, match="signature mismatch"):
        result = validate_spec(spec, check_signature=True)
    assert result.ok  # 警告不阻断
    assert any("signature mismatch" in w for w in result.warnings)


def test_signature_check_off_by_default():
    from funcpatch import validate_spec

    spec = PatchSpec("a", "_target", "build_headers", lambda: None)
    result = validate_spec(spec)  # 不传 check_signature
    assert result.warnings == []


def test_signature_check_wrap_expects_extra_arg():
    from funcpatch import validate_spec

    def good_wrapper(original, cookie=None):
        return original(cookie)

    spec = PatchSpec("a", "_target", "build_headers", good_wrapper, mode="wrap")
    result = validate_spec(spec, check_signature=True)
    assert result.warnings == []


def test_warning_hierarchy():
    from funcpatch import DeprecatedTargetWarning, FunCPatchWarning

    assert issubclass(FunCPatchWarning, UserWarning)
    assert issubclass(DeprecatedTargetWarning, FunCPatchWarning)
