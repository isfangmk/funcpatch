"""FastAPI 端到端集成测试：验证主分支零改动的完整链路。

用 TestClient 发起 HTTP 请求：
  1. 未加载补丁 → 返回核心实现
  2. bootstrap 加载 client_a 补丁 → 返回定制实现（服务代码零改动）
  3. revert → 恢复核心实现
  4. 跨 Registry 冲突 → 第二个 owner 被拒绝

需要 fastapi / httpx；缺失时自动跳过（示例依赖，非 funcpatch 核心依赖）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "src"))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from funcpatch import (  # noqa: E402
    PatchSpec,
    Registry,
    SelectionConfig,
    claims_snapshot,
    shutdown,
)
from funcpatch._claims import clear_all  # noqa: E402

service = importlib.import_module("examples.fastapi.demo_module")
client_a = importlib.import_module("examples.fastapi.patch")

client = TestClient(service.app)


@pytest.fixture(autouse=True)
def isolation():
    original = service.build_headers
    clear_all()
    shutdown()
    yield
    shutdown()
    clear_all()
    attr_name = "build_headers"
    setattr(service, attr_name, original)


def test_without_patch_uses_core():
    resp = client.get("/headers", params={"user": "alice"})
    assert resp.status_code == 200
    assert resp.json() == {"X-Source": "core", "X-User": "alice"}


def test_with_patch_customizes_without_source_change():
    cfg = SelectionConfig("client_a", {}, True)
    reg = Registry(cfg, [client_a.patch])
    assert reg.apply(client_a.patch.target) is True

    resp = client.get("/headers", params={"user": "alice"})
    assert resp.status_code == 200
    assert resp.json() == {
        "X-Source": "client_a",
        "X-Tenant": "alpha",
        "X-User": "ALICE",
    }

    reg.revert(client_a.patch.target)
    assert client.get("/headers", params={"user": "alice"}).json()["X-Source"] == "core"


def test_cross_owner_conflict_via_http():
    reg_a = Registry(SelectionConfig("client_a", {}, True), [client_a.patch])
    assert reg_a.apply(client_a.patch.target) is True

    other = PatchSpec(
        "client_b",
        client_a.patch.target_module,
        client_a.patch.target_attr,
        lambda user: {"X-Source": "client_b"},
    )
    reg_b = Registry(SelectionConfig("client_b", {}, True), [other])
    assert reg_b.apply(other.target) is False  # 被进程级占用表拒绝

    # HTTP 仍返回 client_a 的结果
    assert client.get("/headers").json()["X-Source"] == "client_a"
    reg_a.revert(client_a.patch.target)


def test_claims_snapshot_reflects_live_patch():
    reg = Registry(SelectionConfig("client_a", {}, True), [client_a.patch])
    reg.apply(client_a.patch.target)
    target = client_a.patch.target
    assert target in claims_snapshot()
    assert claims_snapshot()[target]["owner"] == "client_a"
    reg.revert(target)
    assert target not in claims_snapshot()
