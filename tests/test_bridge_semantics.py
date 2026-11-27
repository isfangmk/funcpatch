"""wrapt 桥接：透传对象的实际行为。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


from funcpatch import (  # noqa: E402
    Registry,
    SelectionConfig,
    mark_as_sync,
    sync_to_async,
)
from funcpatch._claims import clear_all  # noqa: E402


def _reg(specs, config=None, *, strict=False):
    clear_all()
    return Registry(config or SelectionConfig("a", {}, True), specs, strict=strict)


def test_bridge_reexports_behave():
    # 确认透传的是有行为的对象，而非同名占位
    assert callable(mark_as_sync)
    assert callable(sync_to_async)

    @sync_to_async
    def f():
        return 1

    assert asyncio.run(f()) == 1  # pyright: ignore[reportArgumentType]
