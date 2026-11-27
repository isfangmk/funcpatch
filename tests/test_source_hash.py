"""源码 hash：回退路径的稳定性与区分度。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


import functools  # noqa: F401

from funcpatch import (  # noqa: E402
    Registry,
    SelectionConfig,
    source_hash,  # noqa: F401
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_source_hash_fallback_stable_for_partial():
    """functools.partial 走回退路径时，同一对象多次计算 hash 应稳定。"""

    def base(a, b):
        return a + b

    p = functools.partial(base, 1)
    assert source_hash(p) == source_hash(p)


def test_source_hash_fallback_differs_by_wrapped_function():
    """回退 hash 应能区分不同底层函数（不是恒定 repr）。"""

    def add(a, b):
        return a + b

    def sub(a, b):
        return a - b

    p1 = functools.partial(add, 1)
    p2 = functools.partial(sub, 1)
    assert source_hash(p1) != source_hash(p2)
