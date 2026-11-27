"""供 reload 测试使用的目标模块（可安全地 importlib.reload）。

与 _target 分开，避免 reload 影响其它测试。
"""

from __future__ import annotations


def build_headers(cookie: str | None = None) -> dict[str, str]:
    """reload 后应恢复为这个原始实现。"""
    return {"X-Source": "original", "cookie": cookie or ""}
