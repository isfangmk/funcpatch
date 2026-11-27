"""命令行工具：退出码与参数组合。"""

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
)
from funcpatch import cli as cli_mod  # noqa: E402
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_cli_plan_returns_one_on_bad_spec(monkeypatch, capsys):
    bad = PatchSpec("a", "_target", "greet", lambda n: n, expect_hash="deadbeef")
    monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [bad])
    assert cli_mod.main(["plan"]) == 1
    capsys.readouterr()


def test_cli_validate_returns_one_on_bad_spec(monkeypatch, capsys):
    bad = PatchSpec("a", "_target", "greet", lambda n: n, expect_hash="deadbeef")
    monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [bad])
    assert cli_mod.main(["validate"]) == 1
    capsys.readouterr()


def test_cli_claims_returns_zero(capsys):
    assert cli_mod.main(["claims"]) == 0
    capsys.readouterr()


def test_cli_missing_subcommand_exits_two():
    with pytest.raises(SystemExit) as exc:
        cli_mod.main([])
    assert exc.value.code == 2


def test_cli_plan_config_passthrough(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "fp.toml"
    cfg.write_text('[funcpatch.default]\nowner = "a"\n', encoding="utf-8")
    seen: dict = {}

    def fake_load_config(path=None):
        seen["path"] = path
        return SelectionConfig("a", {}, True)

    monkeypatch.setattr(cli_mod, "load_config", fake_load_config)
    monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [])
    assert cli_mod.main(["plan", "--config", str(cfg)]) == 0
    assert seen["path"] == str(cfg)
    capsys.readouterr()


def test_cli_plan_diff_prints_unified_diff(monkeypatch, capsys):
    """plan --diff 以可读形式打印替换前后的差异。"""

    def replacement(name):
        return f"patched-{name}"

    spec = PatchSpec("a", "_target", "greet", replacement)
    monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [spec])
    monkeypatch.setattr(cli_mod, "load_config", lambda path=None: SelectionConfig("a", {}, True))
    assert cli_mod.main(["plan", "--diff"]) == 0
    out = capsys.readouterr().out
    assert "_target:greet" in out
    assert "--- a/_target:greet" in out
    assert "+++ b/_target:greet" in out


def test_cli_plan_diff_explains_wrap_mode(monkeypatch, capsys):
    """wrap 模式无 diff 时应说明原因，而不是笼统提示。"""

    def wrapper(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    spec = PatchSpec("a", "_target", "greet", wrapper, mode="wrap")
    monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [spec])
    monkeypatch.setattr(cli_mod, "load_config", lambda path=None: SelectionConfig("a", {}, True))
    assert cli_mod.main(["plan", "--diff"]) == 0
    out = capsys.readouterr().out
    assert "mode=wrap" in out
    assert "wrap 模式在运行时包裹原函数" in out


def test_cli_plan_diff_prints_json_without_flag(monkeypatch, capsys):
    """不加 --diff 时保持原有 JSON 输出。"""
    spec = PatchSpec("a", "_target", "greet", lambda name: f"patched-{name}")
    monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [spec])
    assert cli_mod.main(["plan"]) == 1  # 未配置 owner，不会有补丁可应用
    out = capsys.readouterr().out
    assert out.strip().startswith("[")
    assert "--- a/" not in out


def test_cli_hash_reports_hashes(monkeypatch, capsys):
    """hash 子命令输出每条补丁的源码/依赖 hash。"""

    from funcpatch import dependency_hash, source_hash

    spec = PatchSpec("a", "_target", "with_dependency", lambda name: "patched")
    monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [spec])
    assert cli_mod.main(["hash"]) == 0
    out = capsys.readouterr().out
    assert '"source_hash"' in out and '"dependency_hash"' in out
    assert source_hash(_target.with_dependency) in out
    assert dependency_hash(_target.with_dependency) in out


def test_cli_hash_reports_resolution_error(monkeypatch, capsys):
    """目标不可解析时 hash 子命令输出 error 并返回非零。"""
    spec = PatchSpec("a", "_target", "no_such_attr", lambda: None)
    monkeypatch.setattr(cli_mod, "discover_all", lambda *a, **k: [spec])
    assert cli_mod.main(["hash"]) == 1
    out = capsys.readouterr().out
    assert '"error"' in out
