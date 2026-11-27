"""示例代码回归：确保 examples/ 下的示例可导入、可运行且与文档一致。"""

from __future__ import annotations

import importlib
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import pytest

from funcpatch import PatchSpec

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def _run_module(module: str) -> subprocess.CompletedProcess[str]:
    """在独立子进程中运行示例，确保其入口脚本真实可用。"""
    return subprocess.run(
        [sys.executable, "-m", module],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )


def test_basic_example_runs_and_reverts():
    result = _run_module("examples.basic.run")
    assert result.returncode == 0, result.stderr
    assert "补丁前" in result.stdout
    assert "补丁后" in result.stdout
    assert "回滚后" in result.stdout


def test_modes_walkthrough_passes_all_scenarios():
    result = _run_module("examples.modes.walkthrough")
    assert result.returncode == 0, result.stderr
    assert "全部场景自检通过" in result.stdout


def test_basic_example_patch_targets_existing_function():
    from examples.basic import demo_module, patch

    assert patch.patch.target == "examples.basic.demo_module:build_headers"
    assert hasattr(demo_module, "build_headers")


def test_modes_walkthrough_covers_expected_scenarios():
    """能力演示应覆盖 README 列出的全部场景。"""
    from examples.modes import walkthrough

    scenarios = [
        name
        for name in dir(walkthrough)
        if name.startswith("scenario_") and callable(getattr(walkthrough, name))
    ]
    assert len(scenarios) == 11
    # 每个场景都是可调用的零参函数
    for name in scenarios:
        assert callable(getattr(walkthrough, name))


def test_example_packages_declare_entry_points():
    """两个补丁包示例都应声明 funcpatch.patches entry point。"""
    for name in ("client_a", "client_b"):
        pyproject = REPO_ROOT / "examples" / "packages" / name / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        assert '[project.entry-points."funcpatch.patches"]' in content
        assert f'{name} = "patch:patches"' in content


def test_example_package_patches_are_wellformed():
    """补丁包示例声明的补丁结构正确（独立模块分发，不走目录扫描）。"""
    import importlib.util

    for name in ("client_a", "client_b"):
        path = REPO_ROOT / "examples" / "packages" / name / "patch.py"
        spec = importlib.util.spec_from_file_location(f"example_pkg_{name}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        declared = module.patches
        raw = declared() if callable(declared) else declared
        patches = list(cast(Iterable[PatchSpec], raw))
        assert len(patches) == 1
        patch = patches[0]
        assert patch.owner == name
        assert patch.target_module == "app.core.config"
        assert patch.target_attr == "Settings.build_headers"


def test_fastapi_example_module_exposes_app():
    fastapi = pytest.importorskip("fastapi")
    assert fastapi is not None
    module = importlib.import_module("examples.fastapi.demo_module")
    assert hasattr(module, "app")
    assert hasattr(module, "build_headers")
