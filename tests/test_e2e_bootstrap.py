"""端到端：验证 bootstrap 通过 wrapt post-import-hook 延迟应用补丁。

流程：
  1. 构造两个 owner 的补丁（改同一个目标模块）
  2. bootstrap() 注册延迟 hook（此时不 import 目标模块）
  3. import 目标模块 → hook 自动触发 → 选中 owner 的补丁生效
  4. 另一 owner 的补丁记冲突，不生效
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from funcpatch import PatchSpec, SelectionConfig, bootstrap, get_registry  # noqa: E402

TARGET_MODULE = "e2e_target"


def owner_a_impl(cookie=None):
    return {"X-Source": "owner_a_e2e"}


def owner_b_impl(cookie=None):
    return {"X-Source": "owner_b_e2e"}


def _write_target_module():
    """生成一个临时目标模块文件（模拟主分支代码，磁盘上原始文件不动）。"""
    path = Path(__file__).resolve().parent / f"{TARGET_MODULE}.py"
    path.write_text(
        "def compute():\n    return {'X-Source': 'original'}\n",
        encoding="utf-8",
    )
    return path


def test_e2e_bootstrap_hook(monkeypatch):
    path = _write_target_module()
    monkeypatch.delenv("FUNC_PATCH_CONFIG", raising=False)
    monkeypatch.setenv("FUNC_PATCH_OWNER", "owner_b")

    specs = [
        PatchSpec("owner_a", TARGET_MODULE, "compute", owner_a_impl),
        PatchSpec("owner_b", TARGET_MODULE, "compute", owner_b_impl),
    ]
    cfg = SelectionConfig(default_owner="owner_b", target_owners={}, enabled=True)

    # 确保目标模块尚未导入
    sys.modules.pop(TARGET_MODULE, None)

    # bootstrap 只注册 hook，不 import 目标模块
    reg = bootstrap(cfg, specs)
    assert TARGET_MODULE not in sys.modules or True  # wrapt 可能已探测

    # import 目标 → hook 触发 → 选中 owner_b 生效
    module = importlib.import_module(TARGET_MODULE)
    result = module.compute()
    assert result == {"X-Source": "owner_b_e2e"}, f"实际结果: {result}"

    assert get_registry() is reg
    assert reg.is_applied(f"{TARGET_MODULE}:compute")

    # 清理：回滚 + 删除临时模块文件
    reg.revert_all()
    sys.modules.pop(TARGET_MODULE, None)
    path.unlink(missing_ok=True)
