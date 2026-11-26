"""示例：客户 A 的补丁包（可作为独立 pip 包分发）。

演示如何用 entry point 暴露补丁：
    [project.entry-points."funcpatch.patches"]
    client_a = "client_a_patch:patches"
"""

from funcpatch import PatchSpec


def build_headers(self, cookie=None):
    """客户 A 的 build_headers 完整实现（函数体由补丁拥有）。"""
    headers = {
        "Content-Type": "application/json",
        "X-Parse-Application-Id": getattr(self, "parse_app_id", "Bonree"),
        "X-Tenant": "client-a",
    }
    if cookie:
        headers["cookie"] = cookie if "PRE-GW-SESSION=" in cookie else f"PRE-GW-SESSION={cookie}"
    return headers


patches = [
    PatchSpec(
        owner="client_a",
        target_module="app.core.config",
        target_attr="Settings.build_headers",
        replacement=build_headers,
        description="客户 A 自定义请求头",
    )
]
