"""最小示例的补丁定义。

一条 PatchSpec 描述"谁(owner)、改哪里(target)、改成什么(replacement)"。
主分支的 demo_module.py 不需要任何改动。
"""

from __future__ import annotations

from funcpatch import PatchSpec

TARGET_MODULE = "examples.basic.demo_module"


def build_headers(user: str) -> dict[str, str]:
    """定制方的完整实现：函数体由补丁拥有。"""
    return {
        "X-Source": "client_a",
        "X-Tenant": "alpha",
        "X-User": user.upper(),
    }


patch = PatchSpec(
    owner="client_a",
    target_module=TARGET_MODULE,
    target_attr="build_headers",
    replacement=build_headers,
    description="client_a 定制请求头",
)
