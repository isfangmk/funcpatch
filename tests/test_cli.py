"""CLI 诊断工具测试。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from funcpatch._claims import clear_all  # noqa: E402
from funcpatch.cli import main  # noqa: E402


def test_cli_claims_empty(capsys):
    clear_all()
    code = main(["claims"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.strip() == "{}"


def test_cli_plan_no_specs(capsys):
    code = main(["plan", "--package", "no_such_patch_pkg_xyz"])
    out = capsys.readouterr().out
    assert code == 0  # 没有补丁时 plan 为空，全部通过
    assert "[]" in out


def test_cli_validate_no_specs(capsys):
    code = main(["validate", "--package", "no_such_patch_pkg_xyz"])
    assert code == 0
    assert "[]" in capsys.readouterr().out


def test_cli_claims_with_live_claim(capsys):
    clear_all()
    import _target  # noqa: F401  # pyright: ignore[reportUnusedImport]

    from funcpatch import PatchSpec, Registry, SelectionConfig

    def impl(*args, **kwargs):
        return {"X-Source": "x"}

    reg = Registry(
        SelectionConfig("a", {}, True),
        [PatchSpec("a", "_target", "build_headers", impl)],
    )
    reg.apply("_target:build_headers")
    try:
        code = main(["claims"])
        out = capsys.readouterr().out
        assert code == 0
        assert "_target:build_headers" in out
        assert '"owner": "a"' in out
    finally:
        reg.revert("_target:build_headers")
        clear_all()
