"""示例的补丁定义：定制方对 build_headers 的完整替换。

核心服务代码（demo_module.py）零改动；部署时选择 owner=client_a 即生效。
"""

from __future__ import annotations

from funcpatch import PatchSpec

TARGET_MODULE = "examples.fastapi.demo_module"


def build_headers(user: str) -> dict[str, str]:
    """定制方的完整实现：加上租户标识。"""
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
    description="定制方定制请求头",
)
