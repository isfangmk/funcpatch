"""两个 bug 的回归测试。

bug B：目录扫描认不出模块级 ``list[PatchSpec]``，而 entry point 认得出 ——
       两种发现机制对同一份声明给出不一致的结果。
bug C：``create_patches`` 在目标已被补丁接管后崩溃 ——
       目标位置上装的是 wrapt 代理，代理不可 ``copy.copy``。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import types  # noqa: E402

from funcpatch import PatchSpec, SelectionConfig  # noqa: E402
from funcpatch.discovery import discover_from_directory  # noqa: E402
from funcpatch.generation import create_patches  # noqa: E402
from funcpatch.introspection import get_base  # noqa: E402
from funcpatch.registry import Registry  # noqa: E402

# ---------------------------------------------------------------- bug B


def test_directory_scan_finds_spec_list(tmp_path, monkeypatch):
    """模块级 ``SPECS = [PatchSpec(...)]`` 应被目录扫描发现。"""
    pkg_dir = tmp_path / "container_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "patches.py").write_text(
        "from funcpatch import PatchSpec\n"
        "def repl(original, instance, args, kwargs):\n"
        "    return original(*args, **kwargs)\n"
        "SPECS = [\n"
        "    PatchSpec(owner='c1', target_module='m', target_attr='a', replacement=repl, mode='wrap'),\n"
        "    PatchSpec(owner='c2', target_module='m', target_attr='b', replacement=repl, mode='wrap'),\n"
        "]\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("container_pkg", "container_pkg.patches"):
        sys.modules.pop(name, None)
    try:
        specs = discover_from_directory("container_pkg")
        assert {s.owner for s in specs} == {"c1", "c2"}
    finally:
        for name in ("container_pkg", "container_pkg.patches"):
            sys.modules.pop(name, None)


def test_directory_scan_finds_tuple_of_specs(tmp_path, monkeypatch):
    """元组容器同样应被识别。"""
    pkg_dir = tmp_path / "tuple_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "patches.py").write_text(
        "from funcpatch import PatchSpec\n"
        "def repl(original, instance, args, kwargs):\n"
        "    return original(*args, **kwargs)\n"
        "SPECS = (\n"
        "    PatchSpec(owner='t1', target_module='m', target_attr='a', replacement=repl, mode='wrap'),\n"
        ")\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("tuple_pkg", "tuple_pkg.patches"):
        sys.modules.pop(name, None)
    try:
        specs = discover_from_directory("tuple_pkg")
        assert [s.owner for s in specs] == ["t1"]
    finally:
        for name in ("tuple_pkg", "tuple_pkg.patches"):
            sys.modules.pop(name, None)


def test_entry_point_accepts_generator(monkeypatch):
    """entry point 返回生成器时应被识别（一次性可迭代对象也要支持）。"""
    import importlib.metadata as metadata

    from funcpatch.discovery import discover_from_entry_points

    def gen():
        yield PatchSpec("gen_owner", "m", "a", lambda: None)

    class FakeEP:
        name = "gen"

        def load(self):
            return gen()

        dist = None

    monkeypatch.setattr(metadata, "entry_points", lambda group=None: [FakeEP()])
    specs = discover_from_entry_points("funcpatch.patches")
    assert [s.owner for s in specs] == ["gen_owner"]


def test_directory_scan_ignores_non_spec_container(tmp_path, monkeypatch):
    """容器里若不是 PatchSpec，不应被当成补丁（且不应抛异常）。"""
    pkg_dir = tmp_path / "junk_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "patches.py").write_text(
        "NOT_SPECS = [1, 2, 3]\nDICT = {'a': 1}\nTEXT = 'not a spec'\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("junk_pkg", "junk_pkg.patches"):
        sys.modules.pop(name, None)
    try:
        assert discover_from_directory("junk_pkg") == []
    finally:
        for name in ("junk_pkg", "junk_pkg.patches"):
            sys.modules.pop(name, None)


def test_directory_scan_and_entry_point_agree(tmp_path, monkeypatch):
    """两种发现机制对同一份「容器式声明」必须给出一致结果。"""
    import importlib.metadata as metadata

    from funcpatch.discovery import discover_from_entry_points

    spec = PatchSpec("agree_owner", "m", "a", lambda: None)

    pkg_dir = tmp_path / "agree_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "patches.py").write_text(
        "from funcpatch import PatchSpec\n"
        "def repl(original, instance, args, kwargs):\n"
        "    return original(*args, **kwargs)\n"
        "SPECS = [PatchSpec('agree_owner', 'm', 'a', repl, mode='wrap')]\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("agree_pkg", "agree_pkg.patches"):
        sys.modules.pop(name, None)

    class FakeEP:
        name = "agree"

        def load(self):
            return [spec]

        dist = None

    try:
        dir_specs = discover_from_directory("agree_pkg")
        monkeypatch.setattr(metadata, "entry_points", lambda group=None: [FakeEP()])
        ep_specs = discover_from_entry_points("funcpatch.patches")
        assert len(dir_specs) == 1
        assert len(ep_specs) == 1
        assert dir_specs[0].target == ep_specs[0].target
    finally:
        for name in ("agree_pkg", "agree_pkg.patches"):
            sys.modules.pop(name, None)


# ---------------------------------------------------------------- bug C


def _make_module(name: str = "patched_target_mod") -> types.ModuleType:
    module = types.ModuleType(name)
    # 走 __dict__ 而不是 setattr/属性赋值：
    # 属性赋值被类型检查器判为「不可给 ModuleType 动态加属性」，
    # 而 setattr 又被 lint 判为 B010（常量属性名不必用 setattr）。
    module.__dict__["target_fn"] = lambda a, b: a + b
    module.__dict__["Holder"] = type("Holder", (), {"method": lambda self, x: x})
    return module


def test_create_patches_on_patched_target():
    """目标已被补丁接管后，create_patches 不应崩溃。"""
    module = _make_module()
    sys.modules[module.__name__] = module
    try:
        spec = PatchSpec(
            owner="cust",
            target_module=module.__name__,
            target_attr="target_fn",
            replacement=(lambda orig: lambda *a, **k: orig(*a, **k) + 1)(module.target_fn),
            mode="wrap",
        )
        registry = Registry(SelectionConfig("cust", {}, True), [spec])
        registry.apply_module(module.__name__, None)

        # 目标位置上现在是 wrapt 代理
        assert type(module.target_fn).__name__ == "FunctionWrapper"

        generated = create_patches("cust", module.__name__, module)
        assert generated
        assert all(callable(s.replacement) for s in generated)
    finally:
        sys.modules.pop(module.__name__, None)


def test_get_base_unwraps_wrapt_proxy():
    """get_base 应把 wrapt 代理解到最底层的原始实现。"""
    import wrapt

    def original(a, b):
        return a + b

    def wrapper_fn(wrapped, instance, args, kwargs):
        return wrapped(*args, **kwargs)

    wrapper = wrapt.FunctionWrapper(original, wrapper_fn)
    assert get_base(wrapper) is original


def test_get_base_keeps_plain_function():
    """普通函数原样返回，不被误解包。"""

    def plain(a, b):
        return a + b

    assert get_base(plain) is plain


def test_get_base_unwraps_bound_method():
    """bound method 仍解到 __func__（原有行为不变）。"""

    class Holder:
        def method(self, x):
            return x

    assert get_base(Holder().method) is Holder.method


def test_get_base_unwraps_property_getter():
    """property 仍解到 fget（原有行为不变）。"""

    class Holder:
        @property
        def value(self):
            return 1

    assert get_base(Holder.value) is Holder.value.fget
