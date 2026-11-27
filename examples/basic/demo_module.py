"""最小示例的主分支代码：被补丁的目标函数。"""

from __future__ import annotations


def build_headers(user: str) -> dict[str, str]:
    """核心函数：定制方要替换的内部逻辑。"""
    return {"X-Source": "core", "X-User": user}
