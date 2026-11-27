"""示例：定制方 B 的补丁包，与 A 改同一个目标函数。

entry point 也可以指向返回补丁列表的函数（本例用函数形式），
两种形式 funcpatch 都能发现。

部署时通过 FUNC_PATCH_OWNER=client_a 或 client_b 决定谁生效；
两个包同时安装时也只有一个 owner 生效，另一个记冲突。
"""

from __future__ import annotations

from funcpatch import PatchSpec


def build_headers(self, cookie: str | None = None) -> dict[str, str]:
    """定制方 B 的完整实现：函数体由补丁拥有。"""
    headers = {
        "Content-Type": "application/json",
        "X-Tenant": "client-b",
        "X-Custom-Auth": "enabled",
    }
    if cookie:
        headers["cookie"] = cookie
    return headers


def patches() -> list[PatchSpec]:
    """entry point 指向函数时，调用它并取返回的补丁列表。"""
    return [
        PatchSpec(
            owner="client_b",
            target_module="app.core.config",
            target_attr="Settings.build_headers",
            replacement=build_headers,
            description="定制方 B 自定义请求头",
        )
    ]
