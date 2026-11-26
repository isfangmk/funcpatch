"""配置层测试：三层 owner 选择、toml 加载、环境变量、异常回退。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from funcpatch.config import SelectionConfig, load_config  # noqa: E402


def test_owner_for_priority():
    cfg = SelectionConfig(
        default_owner="default_owner",
        target_owners={"app.mod:f1": "target_owner"},
        enabled=True,
    )
    assert cfg.owner_for("app.mod:f1") == "target_owner"  # [targets] 优先
    assert cfg.owner_for("app.mod:f2") == "default_owner"  # default 次之


def test_owner_for_none():
    cfg = SelectionConfig(default_owner="", target_owners={}, enabled=True)
    assert cfg.owner_for("app.mod:f1") is None  # 未命中 → fail-safe


def test_load_config_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FUNC_PATCH_OWNER", "env_owner")
    monkeypatch.setenv("FUNC_PATCH_ENABLED", "true")
    monkeypatch.setenv("FUNC_PATCH_CONFIG", str(tmp_path / "nonexistent.toml"))

    cfg = load_config()
    assert cfg.enabled is True
    assert cfg.default_owner == "env_owner"
    assert cfg.target_owners == {}


def test_load_config_enabled_false_variants(monkeypatch, tmp_path):
    monkeypatch.setenv("FUNC_PATCH_CONFIG", str(tmp_path / "missing.toml"))
    for value in ("", "false", "0", "off", "no"):
        monkeypatch.setenv("FUNC_PATCH_ENABLED", value)
        assert load_config().enabled is False
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("FUNC_PATCH_ENABLED", value)
        assert load_config().enabled is True


def test_load_config_from_toml(monkeypatch, tmp_path):
    toml_path = tmp_path / "funcpatch.toml"
    toml_path.write_text(
        "[funcpatch.default]\n"
        'owner = "toml_default"\n'
        "\n"
        "[funcpatch.targets]\n"
        '"app.mod:f1" = "toml_target"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FUNC_PATCH_OWNER", "env_owner")
    monkeypatch.setenv("FUNC_PATCH_CONFIG", str(toml_path))

    cfg = load_config()
    assert cfg.default_owner == "toml_default"  # toml default 覆盖 env
    assert cfg.target_owners == {"app.mod:f1": "toml_target"}


def test_load_config_toml_without_prefix(monkeypatch, tmp_path):
    toml_path = tmp_path / "funcpatch.toml"
    toml_path.write_text(
        '[default]\nowner = "no_prefix"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FUNC_PATCH_CONFIG", str(toml_path))
    cfg = load_config()
    assert cfg.default_owner == "no_prefix"


def test_load_config_malformed_toml_falls_back(monkeypatch, tmp_path, capsys):
    toml_path = tmp_path / "funcpatch.toml"
    toml_path.write_text("this is not valid toml [[[", encoding="utf-8")
    monkeypatch.setenv("FUNC_PATCH_OWNER", "env_owner")
    monkeypatch.setenv("FUNC_PATCH_CONFIG", str(toml_path))

    cfg = load_config()
    assert cfg.default_owner == "env_owner"  # 回退到 env
    assert "配置文件读取失败" in capsys.readouterr().err


def test_load_config_explicit_path_wins(monkeypatch, tmp_path):
    toml_path = tmp_path / "explicit.toml"
    toml_path.write_text('[default]\nowner = "explicit"\n', encoding="utf-8")
    monkeypatch.setenv("FUNC_PATCH_OWNER", "env_owner")
    monkeypatch.setenv("FUNC_PATCH_CONFIG", str(tmp_path / "ignored.toml"))

    cfg = load_config(toml_path)  # 显式路径优先于环境变量
    assert cfg.default_owner == "explicit"
