"""示例：客户 B 的补丁包，改同一个目标函数。

部署时通过 FUNC_PATCH_OWNER=client_a 或 client_b 决定谁生效。
"""

from funcpatch import PatchSpec


def build_headers(self, cookie=None):
    """客户 B 的 build_headers 完整实现。"""
    headers = {
        "Content-Type": "application/json",
        "X-Tenant": "client-b",
        "X-Custom-Auth": "enabled",
    }
    if cookie:
        headers["cookie"] = cookie
    return headers


def patches():
    """entry point 也可以指向返回补丁列表的函数。"""
    return [
        PatchSpec(
            owner="client_b",
            target_module="app.core.config",
            target_attr="Settings.build_headers",
            replacement=build_headers,
            description="客户 B 自定义请求头",
        )
    ]
