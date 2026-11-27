"""配置层边界：异常 TOML 结构、目标归一化、环境变量关闭。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from funcpatch import (  # noqa: E402
    PatchSpec,
    Registry,
    SelectionConfig,
    bootstrap,
    shutdown,
)
from funcpatch import config as config_mod  # noqa: E402
from funcpatch import loader as loader_mod  # noqa: E402
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_load_config_tolerates_malformed_toml(monkeypatch, tmp_path):
    cfg = tmp_path / "bad.toml"
    cfg.write_text('[funcpatch]\ndefault = "oops"\ntargets = "oops"\n', encoding="utf-8")
    monkeypatch.setenv("FUNC_PATCH_OWNER", "env-owner")
    monkeypatch.delenv("FUNC_PATCH_CONFIG", raising=False)
    result = config_mod.load_config(str(cfg))
    assert result.default_owner == "env-owner"
    assert result.target_owners == {}


def test_normalize_target_strips_spaces():
    assert config_mod.normalize_target("  app.mod:f  ") == "app.mod.f"


def test_env_disabled_prevents_hook_registration(monkeypatch):

    clear_all()
    monkeypatch.setattr(loader_mod, "_REGISTRY", None)
    monkeypatch.setattr(loader_mod, "_REPORT", None)
    monkeypatch.setattr(loader_mod, "_HOOKS", {})
    monkeypatch.setenv("FUNC_PATCH_ENABLED", "false")

    bootstrap(specs=[PatchSpec("a", "_target", "greet", lambda n: n)])
    try:
        assert loader_mod._HOOKS == {}
        reg = loader_mod._REGISTRY
        assert reg is not None
        assert "_target:greet" in {s.target for s in reg.specs}
        assert reg.is_applied("_target:greet") is False
    finally:
        shutdown()
        clear_all()
