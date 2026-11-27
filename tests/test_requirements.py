"""版本约束与依赖守卫：逗号子句、比较算子、预发布版本、wrapt 版本检查。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from funcpatch import (  # noqa: E402
    _version_check,
    check_requires,
)


@pytest.fixture
def installed(monkeypatch):
    """用固定版本表替换 importlib.metadata.version，避免依赖真实环境。"""
    import funcpatch._requirements as req

    versions = {"app": "2.5.0", "wrapt": "2.5.2", "pre": "2.5rc1"}
    monkeypatch.setattr(req, "version", lambda name: versions[name])
    return req


def test_comparison_operators(installed):
    assert check_requires(("app==2.5.0",)) == []
    assert check_requires(("app!=2.4.0",)) == []
    assert check_requires(("app>=2.3",)) == []
    assert check_requires(("app<=2.5.2",)) == []
    assert check_requires(("app>2.4",)) == []
    assert check_requires(("app<2.6",)) == []
    assert check_requires(("app>2.5.2",))
    assert check_requires(("app==2.4.0",))


def test_comma_separated_clauses(installed):
    """文档主用法：逗号分隔多个约束，子句可省略包名。"""
    assert check_requires(("app>=2.3,<3",)) == []
    assert check_requires(("app>=2.3,<2.4",))
    assert check_requires(("app>=2.5,!=2.5.0",))
    assert check_requires(("app>=2.3,app<3",)) == []


def test_package_only_requirement(installed):
    """纯包名约束只检查是否安装，不比较版本。"""
    assert check_requires(("app",)) == []
    assert check_requires(("app,>=2.3,<3",)) == []
    assert check_requires(("app,<2.3",))


def test_requirement_without_package_name_is_invalid(installed):
    """省略包名的子句必须有前置包名，否则非法。"""
    problems = check_requires((">=2.3",))
    assert problems and problems[0].startswith("invalid requirement:")


def test_unknown_version_segment_gets_stable_code(installed):
    """dev/local 等未知文本段按字符序生成稳定的 kind=2 编码。"""
    import funcpatch._requirements as req

    k1 = req._version_key("2.5dev1")
    k2 = req._version_key("2.5dev2")
    assert k1 == req._version_key("2.5dev1")
    assert any(kind == 2 for kind, _ in k1)
    assert k1 != k2


def test_compatible_release_operator(installed):
    assert check_requires(("app~=2.5",)) == []
    assert check_requires(("app~=2.6",))
    assert check_requires(("app~=2",)) == []


def test_compatible_release_single_segment_rejects_next_major(monkeypatch):
    import funcpatch._requirements as req

    monkeypatch.setattr(req, "version", lambda name: "3.0.0")
    assert check_requires(("app~=2",))


def test_prerelease_orders_before_final(installed):
    """预发布排在同版本正式版之前。"""
    assert check_requires(("pre>=2.5rc1",)) == []
    assert check_requires(("pre>=2.5.0",))
    assert check_requires(("pre<2.5.0",)) == []


def test_prerelease_does_not_reorder_across_minor_versions(monkeypatch):
    """预发布标签不得改变主/次版本的大小关系。"""
    import funcpatch._requirements as req

    assert req._compare("2.6rc1", "<", "2.5") is False
    assert req._compare("2.10rc1", "<", "2.9") is False
    assert req._compare("2.5rc1", "<", "2.6") is True
    assert req._compare("2.5rc1", "<", "2.5rc2") is True
    assert req._compare("2.5a1", "<", "2.5rc1") is True
    assert req._compare("2.5rc1", ">=", "2.5") is False


def test_invalid_requirement(installed):
    problems = check_requires(("app=>2.3",))
    assert problems and problems[0].startswith("invalid requirement:")


def test_package_not_installed(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    import funcpatch._requirements as req

    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(req, "version", missing)
    problems = check_requires(("ghost>=1",))
    assert problems and problems[0] == "package not installed: ghost"


def test_version_check_too_old(monkeypatch):
    monkeypatch.setattr(_version_check, "version", lambda name: "2.4.0")
    with pytest.raises(ImportError, match="wrapt>=2.5"):
        _version_check.check_wrapt_version()


def test_version_check_not_installed(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    def boom(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(_version_check, "version", boom)
    with pytest.raises(ImportError, match="wrapt>=2.5"):
        _version_check.check_wrapt_version()


def test_version_check_nonstandard_version(monkeypatch):
    monkeypatch.setattr(_version_check, "version", lambda name: "unknown")
    _version_check.check_wrapt_version()  # 未知版本不阻断
