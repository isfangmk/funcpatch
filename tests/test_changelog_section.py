"""发布说明生成工具：从 CHANGELOG 提取指定版本的条目。

发布流程依赖这个脚本，提取出错会生成错误的 Release 说明，
因此对边界情况（版本不存在、截断位置）单独覆盖。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from changelog_section import extract  # noqa: E402

CHANGELOG_TEXT = """# Changelog

## [0.2.0] - 2026-02-02

### 新增

- 0.2.0 的新增项

### 修复

- 0.2.0 的修复项

## [0.1.0] - 2026-01-01

> 首次发布。

### 新增

- 0.1.0 的新增项

### 修复

- 0.1.0 的修复项
"""


def test_extract_default_is_summary():
    """默认是摘要模式：标题 + 引言 + 第一个小节。"""
    section = extract("0.1.0", CHANGELOG_TEXT)
    assert "## [0.1.0] - 2026-01-01" in section
    assert "0.1.0 的新增项" in section
    # 摘要不含第二个小节，也不含下个版本
    assert "0.1.0 的修复项" not in section
    assert "0.2.0" not in section


def test_extract_summary_stops_at_second_section():
    """摘要模式只取第一个小节。"""
    section = extract("0.1.0", CHANGELOG_TEXT)
    assert "## [0.1.0] - 2026-01-01" in section
    assert "> 首次发布。" in section
    assert "0.1.0 的新增项" in section
    assert "0.1.0 的修复项" not in section


def test_extract_full_keeps_all_sections():
    section = extract("0.1.0", CHANGELOG_TEXT, full=True)
    assert "0.1.0 的新增项" in section
    assert "0.1.0 的修复项" in section


def test_extract_unknown_version_raises():
    try:
        extract("9.9.9", CHANGELOG_TEXT)
    except KeyError:
        return
    raise AssertionError("版本不存在时应抛 KeyError")


def test_extract_real_changelog_has_current_version():
    """真实 CHANGELOG 里应能提取到当前发布版本。"""
    from funcpatch import __version__

    repo = Path(__file__).resolve().parent.parent
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    section = extract(__version__, text)
    assert f"## [{__version__}]" in section
    # 摘要含版本标题与至少一个小节（不硬编码小节名——改名也不该让测试失效）
    assert "### " in section
    assert section.startswith(f"## [{__version__}]")


def test_extract_excludes_link_definitions():
    """文末的版本链接定义不应进入提取结果。

    那是 CHANGELOG 自己的引用语法，放进 Release 说明里只会显示成裸链接。
    """
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    section = extract("0.1.0", text, full=True)
    assert "[0.1.0]: https://" not in section
    # 但正文里对 CHANGELOG 的引用不受影响
    assert "CHANGELOG" in section or "变更" in section


def test_script_cli_outputs_section(capsys):
    """命令行入口应输出提取到的条目。"""
    from changelog_section import main

    assert main(["changelog_section.py", "0.1.0"]) == 0
    out = capsys.readouterr().out
    assert "## [0.1.0]" in out


def test_script_cli_rejects_unknown_version(capsys):
    from changelog_section import main

    assert main(["changelog_section.py", "9.9.9"]) == 1
    assert "没有版本" in capsys.readouterr().err


def test_script_cli_requires_version_argument(capsys):
    from changelog_section import main

    assert main(["changelog_section.py"]) == 2
