"""关键缺陷回归测试：目标归一化、全局开关、回滚与描述符。"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import _target  # noqa: E402

from funcpatch import (  # noqa: E402
    AuditReport,
    ConflictError,
    FunCPatchError,
    PatchRejectedError,
    PatchSpec,
    PathResolutionError,
    Registry,
    SelectionConfig,
    TargetNotFoundError,
    is_patched,
)
from funcpatch.config import normalize_target, parse_enabled  # noqa: E402

TARGET = "_target:build_headers"


def _config(owner: str, targets: dict | None = None, enabled: bool = True) -> SelectionConfig:
    return SelectionConfig(default_owner=owner, target_owners=targets or {}, enabled=enabled)


def _spec(
    owner: str = "a", attr: str = "build_headers", marker: str = "patched", **kw
) -> PatchSpec:
    def impl(*args, **kwargs):
        return {"X-Source": marker}

    return PatchSpec(owner=owner, target_module="_target", target_attr=attr, replacement=impl, **kw)


# ---- 缺陷 1：目标键格式不符（点号 vs 冒号） ----


def test_normalize_target_both_forms():
    assert normalize_target("app.mod:f1") == normalize_target("app.mod.f1")


def test_dot_form_target_key_matches(monkeypatch, tmp_path):
    """文档里的点号 [targets] 键必须能选中冒号形式的内部目标。"""
    from funcpatch.config import load_config

    cfg_file = tmp_path / "funcpatch.toml"
    cfg_file.write_text(
        '[funcpatch.default]\nowner = "default_a"\n'
        '[funcpatch.targets]\n"_target.build_headers" = "client_b"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FUNC_PATCH_CONFIG", str(cfg_file))
    monkeypatch.setenv("FUNC_PATCH_OWNER", "env_owner")
    cfg = load_config()
    assert cfg.owner_for(TARGET) == "client_b"  # 点号键匹配冒号目标


def test_colon_form_target_key_still_works():
    cfg = _config("default_a", {TARGET: "client_b"})
    assert cfg.owner_for(TARGET) == "client_b"


# ---- 缺陷 2：FUNC_PATCH_ENABLED 是死配置 ----


def test_parse_enabled_variants():
    assert parse_enabled("false") is False
    assert parse_enabled("0") is False
    assert parse_enabled("") is False
    assert parse_enabled("true") is True
    assert parse_enabled("garbage") is True  # 未知值按开启


def test_global_disabled_prevents_apply():
    reg = Registry(_config("a", enabled=False), [_spec()])
    report = AuditReport()
    assert reg.apply(TARGET, report) is False
    assert _target.build_headers()["X-Source"] == "original"
    assert report.rejections[-1]["reason"] == "disabled"


# ---- 缺陷 3：回滚失败丢失记录 ----


def test_failed_revert_keeps_record(monkeypatch):
    reg = Registry(_config("a"), [_spec()])
    assert reg.apply(TARGET) is True

    import funcpatch.registry as regmod

    def broken_resolve_owner(*args, **kwargs):
        raise RuntimeError("simulated revert failure")

    monkeypatch.setattr(regmod, "resolve_owner", broken_resolve_owner)
    assert reg.revert(TARGET) is False
    # 记录必须保留，才能重试
    assert reg.is_applied(TARGET) is True


def test_revert_retry_succeeds_after_restore(monkeypatch):
    reg = Registry(_config("a"), [_spec()])
    reg.apply(TARGET)

    import funcpatch.registry as regmod

    real = regmod.resolve_owner
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("temporary")
        return real(*args, **kwargs)

    monkeypatch.setattr(regmod, "resolve_owner", flaky)
    assert reg.revert(TARGET) is False
    assert reg.revert(TARGET) is True
    assert _target.build_headers()["X-Source"] == "original"


# ---- 缺陷 4：replace + enabled + async 破坏协程身份 ----


def test_async_replace_enabled_preserves_coroutine():
    async def impl(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "async_greet", impl, enabled=lambda: False)
    reg = Registry(_config("a"), [spec])
    assert reg.apply("_target:async_greet") is True
    assert inspect.iscoroutinefunction(_target.async_greet)

    result = asyncio.run(_target.async_greet("x"))
    assert result == "async hello x"  # enabled=False 走原函数
    reg.revert("_target:async_greet")


# ---- 缺陷 5：get_original 对描述符返回 None ----


def test_get_original_for_classmethod():
    def impl(cls):
        return "patched"

    spec = PatchSpec("a", "_target", "Descriptors.who", impl)
    reg = Registry(_config("a"), [spec])
    reg.apply("_target:Descriptors.who")
    original = reg.get_original("_target:Descriptors.who")
    assert original is not None and callable(original)
    assert original(_target.Descriptors) == "class-Descriptors"
    reg.revert("_target:Descriptors.who")


def test_get_original_for_property():
    def impl(self):
        return "patched"

    spec = PatchSpec("a", "_target", "Descriptors.prop", impl)
    reg = Registry(_config("a"), [spec])
    reg.apply("_target:Descriptors.prop")
    original = reg.get_original("_target:Descriptors.prop")
    assert original is not None and callable(original)
    assert original(_target.Descriptors()) == "prop-original"
    reg.revert("_target:Descriptors.prop")


# ---- 缺陷 6：诊断标记对 property 失效 ----


def test_is_patched_detects_property_marker():
    def impl(self):
        return "patched"

    spec = PatchSpec("a", "_target", "Descriptors.prop", impl)
    reg = Registry(_config("a"), [spec])
    reg.apply("_target:Descriptors.prop")
    assert is_patched("_target:Descriptors.prop") is True
    from funcpatch import get_applied_info

    info = get_applied_info("_target:Descriptors.prop")
    assert info is not None and info["owner"] == "a"
    reg.revert("_target:Descriptors.prop")


# ---- 缺陷 7：自定义异常未被抛出 ----


def test_strict_mode_raises_patch_rejected():
    spec = _spec(expect_hash="deadbeef")
    reg = Registry(_config("a"), [spec], strict=True)
    with pytest.raises(PatchRejectedError):
        reg.apply(TARGET)


def test_strict_mode_raises_path_resolution():
    spec = PatchSpec("a", "_target", "no_such_attr", lambda: None)
    reg = Registry(_config("a"), [spec], strict=True)
    with pytest.raises(PathResolutionError):
        reg.apply("_target:no_such_attr")


def test_strict_mode_raises_target_not_found():
    spec = _spec()
    reg = Registry(_config("other_owner"), [spec], strict=True)
    with pytest.raises(TargetNotFoundError):
        reg.apply(TARGET)


def test_exception_hierarchy():
    assert issubclass(PatchRejectedError, FunCPatchError)
    assert issubclass(PathResolutionError, FunCPatchError)
    assert issubclass(TargetNotFoundError, FunCPatchError)
    assert issubclass(ConflictError, FunCPatchError)
