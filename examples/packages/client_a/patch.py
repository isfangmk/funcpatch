"""示例：定制方 A 的补丁包（作为独立 pip 包分发）。

补丁包由定制方维护、与主分支代码分离，通过 entry point 暴露给 funcpatch：

    [project.entry-points."funcpatch.patches"]
    client_a = "patch:patches"

安装后 funcpatch 会自动发现本包；部署时用 FUNC_PATCH_OWNER=client_a 决定是否生效。
"""

from __future__ import annotations

from funcpatch import PatchSpec


def build_headers(self, cookie: str | None = None) -> dict[str, str]:
    """定制方 A 的完整实现：函数体由补丁拥有。"""
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
        description="定制方 A 自定义请求头",
    )
]
