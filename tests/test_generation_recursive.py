"""批量生成：递归扫描嵌套类与非递归边界。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from funcpatch import (  # noqa: E402
    Registry,
    SelectionConfig,
    create_patches,
    find_patches,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_create_patches_recursive_scans_nested_classes():
    """create_patches(recursive=True) 递归进入嵌套类，目标路径用点号连接。"""

    class Nested:
        def inner(self):
            return 1

    class Root:
        def top(self):
            return 0

        nested = Nested()

    # recursive=False：只有 top，不会进入 nested（nested 是实例，不是类）
    shallow = create_patches("a", "_target", Root, filter_fn=None, recursive=False)
    assert "top" in {s.target_attr for s in shallow}

    # 用类属性形式让 recursive=True 能递归进入
    class Root2:
        def top(self):
            return 0

        class Nested:
            def inner(self):
                return 1

    deep = create_patches("a", "_target", Root2, filter_fn=None, recursive=True)
    attrs = {s.target_attr for s in deep}
    assert "top" in attrs
    assert "Nested.inner" in attrs


def test_find_patches_non_recursive_does_not_enter_nested_class():
    """find_patches(recursive=False) 只扫顶层成员，不递归嵌套类。"""

    from funcpatch import patch

    mod = ModuleType("fake_patch_module")

    @patch("a", "_target", "greet")
    def top_impl(name):
        return name

    setattr(mod, "top_impl", top_impl)  # noqa: B010  # ModuleType 动态属性

    @patch("a", "_target", "build_headers")
    def nested_impl(name):
        return name

    class Nested:
        impl = nested_impl

    setattr(mod, "Nested", Nested)  # noqa: B010  # ModuleType 动态属性

    shallow = find_patches(mod, recursive=False)
    assert any(s.target == "_target:greet" for s in shallow)
    assert not any(s.target == "_target:build_headers" for s in shallow)

    deep = find_patches(mod, recursive=True)
    assert any(s.target == "_target:build_headers" for s in deep)
