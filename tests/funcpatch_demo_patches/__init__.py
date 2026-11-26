"""目录扫描发现的示例补丁包（两个 owner 改同一目标）。"""

from funcpatch import PatchSpec


def client_a_headers(cookie=None):
    return {"X-Source": "client_a", "X-Owner": "a"}


def client_b_headers(cookie=None):
    return {"X-Source": "client_b", "X-Owner": "b"}


patch_a = PatchSpec(
    owner="client_a",
    target_module="app.core.config",
    target_attr="Settings.build_headers",
    replacement=client_a_headers,
    description="client A 的 headers 实现",
)

patch_b = PatchSpec(
    owner="client_b",
    target_module="app.core.config",
    target_attr="Settings.build_headers",
    replacement=client_b_headers,
    description="client B 的 headers 实现",
)
