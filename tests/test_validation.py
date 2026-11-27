"""部署前校验：不可调用目标、签名绑定、版本约束、废弃告警。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    DeprecatedTargetWarning,
    FunCPatchWarning,
    PatchSpec,
    Registry,
    SelectionConfig,
    check_requires,
    validate,
    validate_spec,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_validate_target_module_import_failure_is_reported():
    """目标模块导入失败时应报告问题，而不是抛出异常中断整批校验。"""
    spec = PatchSpec("a", "_no_such_module_xyz", "f", lambda: None)
    result = validate_spec(spec)
    assert result.ok is False
    assert any("import failed" in p for p in result.problems)


def test_validate_no_callable_target():
    setattr(_target, "CONSTANT", "just a string")  # noqa: B010
    spec = PatchSpec("a", "_target", "CONSTANT", lambda: None)
    result = validate_spec(spec)
    assert not result.ok
    assert any("no callable" in p for p in result.problems)


def test_validate_builtin_signature_no_crash(monkeypatch):
    """目标签名不可解析时跳过比较，不崩溃也不产生签名警告。"""
    import funcpatch.validation as vmod

    def boom(*args, **kwargs):
        raise ValueError("no signature")

    monkeypatch.setattr(vmod.inspect, "signature", boom)
    spec = PatchSpec("a", "_target", "greet", lambda name: name)
    result = validate_spec(spec, check_signature=True)
    assert result.ok is True
    assert not any("signature" in w for w in result.warnings)


def test_signature_check_var_keyword_target():
    """目标含 **kwargs 时哨兵绑定不崩溃。"""

    def target_fn(a, **kwargs):
        return a

    setattr(_target, "VARKW_FN", target_fn)  # noqa: B010

    def impl(a, **kwargs):
        return a

    spec = PatchSpec("a", "_target", "VARKW_FN", impl)
    result = validate_spec(spec, check_signature=True)
    assert result.warnings == []


def test_signature_check_var_positional_target():
    # 目标含 *args 时哨兵生成与绑定不崩溃
    def target_fn(a, *args):
        return a

    setattr(_target, "VARARG_FN", target_fn)  # noqa: B010

    def impl(a, *args):
        return a

    spec = PatchSpec("a", "_target", "VARARG_FN", impl)
    result = validate_spec(spec, check_signature=True)
    assert result.warnings == []


def test_signature_check_keyword_only_target():
    def target_fn(a, *, b=1):
        return a

    setattr(_target, "KWONLY_FN", target_fn)  # noqa: B010

    def impl(a, *, b=1):
        return a

    spec = PatchSpec("a", "_target", "KWONLY_FN", impl)
    result = validate_spec(spec, check_signature=True)
    assert result.warnings == []


def test_signature_bind_catches_parameter_name_mismatch():
    """位置参数个数相同但名字不同也应告警（旧实现只数个数会漏检）。"""
    import warnings as _warnings

    def impl(wrong_name=None):
        return {}

    spec = PatchSpec("a", "_target", "build_headers", impl)
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        from funcpatch import validate_spec

        result = validate_spec(spec, check_signature=True)
    assert result.ok  # 警告不阻断
    assert any(
        issubclass(w.category, FunCPatchWarning) and "signature mismatch" in str(w.message)
        for w in caught
    )


def test_signature_bind_warns_keyword_only_replacement():
    """replacement 只接受关键字时，目标可位置调用 → 不兼容，应告警。"""
    from funcpatch import validate_spec

    def impl(*, cookie=None):
        return {}

    spec = PatchSpec("a", "_target", "build_headers", impl)
    result = validate_spec(spec, check_signature=True)
    assert any("signature mismatch" in w for w in result.warnings)


def test_signature_check_wrap_zero_arg_replacement_warns():
    """wrap 模式零参数 replacement 违反 wrapt 四参数协议，应告警但不阻断。"""
    spec = PatchSpec("a", "_target", "greet", lambda: None, mode="wrap")
    with pytest.warns(FunCPatchWarning, match="wrap replacement must accept"):
        result = validate_spec(spec, check_signature=True)
    assert result.ok is True
    assert any("wrap replacement must accept" in w for w in result.warnings)


def test_check_requires_various_operators():
    # 用 monkeypatch 替换 version 查询即可，不依赖真实包
    from importlib.metadata import PackageNotFoundError

    import funcpatch._requirements as req

    original = req.version

    def fake_version(name):
        versions = {"wrapt": "2.5.2", "foo": "2.3.0"}
        if name not in versions:
            raise PackageNotFoundError(name)
        return versions[name]

    req.version = fake_version
    try:
        assert check_requires(("wrapt>=2.4", "wrapt<3")) == []
        assert check_requires(("wrapt>=3",))  # 不满足
        assert check_requires(("foo==2.3.0",)) == []
        assert check_requires(("foo!=2.3.0",))
        assert check_requires(("missing-pkg>=1",))
        assert check_requires(("bad requirement",))
    finally:
        req.version = original


def test_requires_blocks_validate_spec():
    spec = PatchSpec("a", "_target", "greet", lambda name: name, requires=("wrapt>=999",))
    result = validate_spec(spec)
    assert not result.ok
    assert any("version conflict" in p for p in result.problems)


def test_deprecated_warns_in_validate():
    spec = PatchSpec("a", "_target", "greet", lambda name: name, deprecated="migrate to greet2")
    with pytest.warns(DeprecatedTargetWarning):
        result = validate_spec(spec)
    assert result.ok
    assert any("deprecated" in w for w in result.warnings)


# ------------------------------------------------------------------ owner 命中检查


def test_validate_with_config_reports_owner_mismatch():
    """配置的 owner 没有该目标的补丁时，校验应报出问题。

    此前 validate() 不做 owner 选择检查，部署配置了 owner 却没有任何补丁命中时
    仍然报通过，直到运行时才发现一条补丁都没生效。
    """
    spec = PatchSpec("client_b", "_target", "greet", lambda name: name)
    cfg = SelectionConfig("client_a", {}, True)
    results = validate([spec], config=cfg)
    assert results[0].ok is False
    assert any("owner mismatch" in p for p in results[0].problems)


def test_validate_with_config_accepts_matching_owner():
    """owner 命中时校验应通过。"""
    spec = PatchSpec("client_a", "_target", "greet", lambda name: name)
    cfg = SelectionConfig("client_a", {}, True)
    results = validate([spec], config=cfg)
    assert results[0].ok is True
    assert results[0].problems == []


def test_validate_with_config_respects_target_specific_owner():
    """[targets] 精确指定的 owner 优先于 [default]。"""
    spec = PatchSpec("client_b", "_target", "greet", lambda name: name)
    cfg = SelectionConfig("client_a", {"_target:greet": "client_b"}, True)
    results = validate([spec], config=cfg)
    assert results[0].ok is True


def test_validate_without_owner_config_is_not_a_problem():
    """未配置 owner 时本就不应用补丁，不应报为问题。"""
    spec = PatchSpec("client_b", "_target", "greet", lambda name: name)
    cfg = SelectionConfig("", {}, True)
    results = validate([spec], config=cfg)
    assert results[0].ok is True


def test_validate_config_agrees_with_plan():
    """校验与预演对同一份配置必须给出相同结论。"""
    spec = PatchSpec("client_b", "_target", "greet", lambda name: name)
    cfg = SelectionConfig("client_a", {}, True)
    results = validate([spec], config=cfg)
    plan = Registry(cfg, [spec]).plan()[0]
    assert results[0].ok is False
    assert plan["would_apply"] is False
    assert plan["reason"] == "no selected owner"
