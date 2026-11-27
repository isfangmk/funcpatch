"""entry point 发现：来源追溯、异常隔离、非 spec 项过滤。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from funcpatch import (  # noqa: E402
    AuditReport,
    PatchSpec,
    Registry,
    SelectionConfig,
)
from funcpatch import discovery as discovery_mod  # noqa: F401
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_entry_point_origin_recorded(monkeypatch):
    class FakeDist:
        name = "client-pkg"
        version = "1.2.3"

    class FakeEP:
        name = "patches"
        dist = FakeDist()

        def load(self):
            return PatchSpec("a", "_target", "greet", lambda n: n)

    monkeypatch.setattr(discovery_mod.importlib.metadata, "entry_points", lambda group: [FakeEP()])
    specs = discovery_mod.discover_from_entry_points("test.group")
    assert len(specs) == 1
    origin = discovery_mod.get_spec_origin(specs[0])
    assert origin == {
        "distribution": "client-pkg",
        "version": "1.2.3",
        "ep_name": "patches",
    }


def test_audit_entry_includes_origin(monkeypatch):

    spec = PatchSpec("a", "_target", "greet", lambda n: f"p-{n}")
    key = id(spec)
    discovery_mod._SPEC_ORIGINS[key] = {
        "distribution": "pkg",
        "version": "1.0",
        "ep_name": "ep",
    }
    clear_all()
    try:
        reg = Registry(SelectionConfig("a", {}, True), [spec])
        report = AuditReport()
        assert reg.apply("_target:greet", report) is True
        assert report.entries[0]["origin"]["distribution"] == "pkg"
        reg.revert("_target:greet")
    finally:
        discovery_mod._SPEC_ORIGINS.pop(key, None)
        clear_all()


def test_entry_point_callable_failure_isolated(monkeypatch):
    class BadEP:
        name = "bad"
        dist = None

        def load(self):
            def factory():
                raise RuntimeError("boom")

            return factory

    monkeypatch.setattr(discovery_mod.importlib.metadata, "entry_points", lambda group: [BadEP()])
    specs = discovery_mod.discover_from_entry_points("test")
    assert specs == []


def test_entry_point_non_spec_item_ignored(monkeypatch):
    class MixedEP:
        name = "mixed"
        dist = None

        def load(self):
            return [PatchSpec("a", "_target", "greet", lambda n: n), "bad"]

    monkeypatch.setattr(discovery_mod.importlib.metadata, "entry_points", lambda group: [MixedEP()])
    specs = discovery_mod.discover_from_entry_points("test")
    assert len(specs) == 1
