"""补丁预览：生成目标实现与替代实现的 unified diff。

只用于部署前查看"这个函数会被改成什么样"，不参与 apply 流程。
"""

from __future__ import annotations

import difflib
import inspect
from typing import Any


def source_of(obj: Any) -> str | None:
    """取对象的源码；不可用时（内置函数等）返回 None。

    lambda 这类单行表达式取到的源码会是它所在的整行（含赋值语句上下文），
    生成的 diff 会误导，故直接跳过。
    """
    try:
        lines, _start = inspect.getsourcelines(obj)
    except (OSError, TypeError):
        return None
    if not lines:
        return None
    text = "".join(lines)
    # 单行且不是完整 def：多半是 lambda，源码含上下文，不适合做 diff
    stripped = text.strip()
    if "\n" not in stripped and not stripped.startswith(("def ", "async def ", "class ")):
        return None
    return text


def render_diff(original: str | None, replacement: str | None, target: str) -> str:
    """生成 unified diff；任一侧源码不可用时返回空串。"""
    if not original or not replacement:
        return ""
    lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        replacement.splitlines(keepends=True),
        fromfile=f"a/{target}",
        tofile=f"b/{target}",
    )
    return "".join(lines)
