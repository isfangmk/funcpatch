"""能力演示：按场景展示 funcpatch 的主要用法，可直接运行自检。

    python -m examples.modes.walkthrough

每个场景在独立的 Registry 中进行，结束后回滚，不影响后续场景。
脚本自检通过时打印"全部场景自检通过"，任何断言失败都会以非零退出码结束。
"""

from __future__ import annotations

import asyncio

from funcpatch import (
    AuditReport,
    PatchSpec,
    Registry,
    SelectionConfig,
    dependency_hash,
    scoped_patch,
    suppress_patches,
    validate,
)

TARGET = "examples.modes.demo_module"
OWNER = "demo"


def _reg(specs: list[PatchSpec]) -> Registry:
    return Registry(SelectionConfig(OWNER, {}, True), specs)


def _section(title: str) -> None:
    print(f"\n== {title} ==")


def scenario_replace() -> None:
    """replace：完全替换函数实现，函数体由补丁拥有。"""
    _section("replace：完整替换")
    from . import demo_module

    spec = PatchSpec(OWNER, TARGET, "greet", lambda name: f"custom {name}")
    reg = _reg([spec])
    before = demo_module.greet("a")
    try:
        assert reg.apply(spec.target)
        print("before:", before, "-> after:", demo_module.greet("a"))
        assert demo_module.greet("a") == "custom a"
    finally:
        reg.revert_all()


def scenario_wrap() -> None:
    """wrap：包装原函数，wrapper 内可调用 wrapped 复用核心逻辑。"""
    _section("wrap：复用原实现并增强")
    from . import demo_module

    def wrapper(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs).upper()

    spec = PatchSpec(OWNER, TARGET, "greet", wrapper, mode="wrap")
    reg = _reg([spec])
    try:
        assert reg.apply(spec.target)
        print("greet ->", demo_module.greet("a"))
        assert demo_module.greet("a") == "HELLO A"
    finally:
        reg.revert_all()


def scenario_async() -> None:
    """async：替换异步函数，保持协程身份。"""
    _section("async：替换异步函数")
    from . import demo_module

    async def impl(name: str) -> str:
        return f"patched async {name}"

    spec = PatchSpec(OWNER, TARGET, "async_greet", impl)
    reg = _reg([spec])
    try:
        assert reg.apply(spec.target)
        result = asyncio.run(demo_module.async_greet("a"))
        print("async_greet ->", result)
        assert result == "patched async a"
    finally:
        reg.revert_all()


def scenario_descriptors() -> None:
    """descriptors：classmethod / staticmethod / property 的替换。"""
    _section("descriptors：类方法、静态方法与属性")
    from . import demo_module

    specs = [
        PatchSpec(OWNER, TARGET, "Settings.who", lambda cls: "patched-who"),
        PatchSpec(OWNER, TARGET, "Settings.static", lambda: "patched-static"),
        PatchSpec(OWNER, TARGET, "Settings.theme", lambda self: "patched-theme"),
    ]
    reg = _reg(specs)
    try:
        for spec in specs:
            assert reg.apply(spec.target)
        print("who:", demo_module.Settings.who())
        print("static:", demo_module.Settings.static())
        print("theme:", demo_module.Settings().theme)
        assert demo_module.Settings.who() == "patched-who"
        assert demo_module.Settings.static() == "patched-static"
        assert demo_module.Settings().theme == "patched-theme"
    finally:
        reg.revert_all()


def scenario_property_part() -> None:
    """property_part：只替换 setter，getter 保持原实现。"""
    _section("property_part：只改 setter")
    from . import demo_module

    def set_theme(self, value: str) -> None:
        self._theme = f"custom-{value}"

    spec = PatchSpec(OWNER, TARGET, "Settings.theme", set_theme, property_part="set")
    reg = _reg([spec])
    try:
        assert reg.apply(spec.target)
        instance = demo_module.Settings()
        instance.theme = "dark"
        print("theme after set:", instance.theme)
        assert instance.theme == "custom-dark"
    finally:
        reg.revert_all()


def scenario_add() -> None:
    """add：添加主分支里原本不存在的方法。"""
    _section("add：添加新方法")
    from . import demo_module

    spec = PatchSpec(
        OWNER, TARGET, "Settings.client_only", lambda self, x: f"client-{x}", mode="add"
    )
    reg = _reg([spec])
    try:
        assert reg.apply(spec.target)
        print("client_only ->", demo_module.Settings().client_only("a"))
        assert demo_module.Settings().client_only("a") == "client-a"
    finally:
        reg.revert_all()
    # 回滚后属性被删除
    assert not hasattr(demo_module.Settings, "client_only")


def scenario_transaction() -> None:
    """transaction：批量应用，任一失败自动回滚。"""
    _section("transaction：批量应用与失败回滚")
    from . import demo_module

    good = PatchSpec(OWNER, TARGET, "greet", lambda name: f"tx {name}")
    bad = PatchSpec(OWNER, TARGET, "async_greet", lambda name: name, expect_hash="bad")
    reg = _reg([good, bad])
    report = AuditReport()
    result = reg.apply_all([good.target, bad.target], report)
    print("applied:", result.applied, "failed:", result.failed, "rolled_back:", result.rolled_back)
    assert not result.ok
    assert demo_module.greet("a") == "hello a"  # 批次失败，已回滚


def scenario_scoped_and_suppress() -> None:
    """scoped / suppress：临时补丁与上下文旁路。"""
    _section("scoped / suppress：临时补丁与旁路")
    from . import demo_module

    spec = PatchSpec(OWNER, TARGET, "greet", lambda name: f"scoped {name}")
    with scoped_patch(TARGET, "greet", spec):
        print("in scope:", demo_module.greet("a"))
        assert demo_module.greet("a") == "scoped a"
        with suppress_patches():
            print("suppressed:", demo_module.greet("a"))
            assert demo_module.greet("a") == "hello a"
    print("after scope:", demo_module.greet("a"))
    assert demo_module.greet("a") == "hello a"


def scenario_validate() -> None:
    """validate：部署前只读校验。"""
    _section("validate：部署前校验")

    good = PatchSpec(OWNER, TARGET, "greet", lambda name: f"v {name}")
    bad = PatchSpec(OWNER, TARGET, "greet", lambda name: name, expect_hash="bad")
    results = validate([good, bad])
    for result in results:
        print(result.to_dict())
    assert results[0].ok is True
    assert results[1].ok is False


def scenario_dependency_hash() -> None:
    """dependency hash：目标连同同模块依赖一起校验。"""
    _section("dependency hash：依赖闭包校验")
    from . import demo_module

    expected = dependency_hash(demo_module.greet)
    spec = PatchSpec(OWNER, TARGET, "greet", lambda name: "patched", expect_deps_hash=expected)
    reg = _reg([spec])
    try:
        assert reg.apply(spec.target)
        print("applied with expect_deps_hash:", expected)
    finally:
        reg.revert_all()

    # hash 不匹配时拒绝应用
    wrong = PatchSpec(
        OWNER, TARGET, "greet", lambda name: "patched", expect_deps_hash="0000000000000000"
    )
    reg2 = _reg([wrong])
    try:
        assert reg2.apply(wrong.target) is False
        print("mismatched expect_deps_hash -> rejected")
    finally:
        reg2.revert_all()


def scenario_plan_diff() -> None:
    """plan --diff：发布前预览函数会被改成什么样。"""
    _section("plan --diff：替换差异预览")

    def replacement(name: str) -> str:
        return f"preview {name}"

    spec = PatchSpec(OWNER, TARGET, "greet", replacement)
    reg = _reg([spec])
    try:
        entry = reg.plan(include_diff=True)[0]
        print(entry["diff"].rstrip())
        assert "--- a/" in entry["diff"]
        assert "+++ b/" in entry["diff"]
    finally:
        reg.revert_all()


def main() -> None:
    scenario_replace()
    scenario_wrap()
    scenario_async()
    scenario_descriptors()
    scenario_property_part()
    scenario_add()
    scenario_transaction()
    scenario_scoped_and_suppress()
    scenario_validate()
    scenario_dependency_hash()
    scenario_plan_diff()
    print("\n全部场景自检通过。")


if __name__ == "__main__":
    main()
