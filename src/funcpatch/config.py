"""配置层：三层 owner 选择规则。

优先级（高到低）：
  1. funcpatch.toml [targets] 按目标精确指定
  2. funcpatch.toml [default] owner
  3. 环境变量 FUNC_PATCH_OWNER
  4. 未命中 → 不应用（fail-safe）

Python 3.10 无 tomllib：尝试 tomli，缺失时配置文件层禁用（env 层仍可用）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import tomllib as _toml  # type: ignore[import-not-found]

    _HAS_TOML = True
except ImportError:  # Python 3.10
    try:
        import tomli as _toml  # type: ignore[import-not-found]

        _HAS_TOML = True
    except ImportError:
        _toml = None  # type: ignore[assignment]
        _HAS_TOML = False

DEFAULT_CONFIG_FILE = "funcpatch.toml"


class SelectionConfig:
    """选择规则的不可变快照。"""

    def __init__(
        self,
        default_owner: str,
        target_owners: dict[str, str],
        enabled: bool,
    ) -> None:
        self.default_owner = default_owner
        self.target_owners = target_owners
        self.enabled = enabled

    def owner_for(self, target: str) -> str | None:
        """按三层规则返回 target 应使用的 owner；未命中返回 None。"""
        if target in self.target_owners:
            return self.target_owners[target]
        if self.default_owner:
            return self.default_owner
        return None


def load_config(config_path: str | Path | None = None) -> SelectionConfig:
    """从环境变量 + toml 构建选择配置。"""
    enabled = os.getenv("FUNC_PATCH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    env_owner = os.getenv("FUNC_PATCH_OWNER", "").strip()

    default_owner = env_owner
    target_owners: dict[str, str] = {}

    path = Path(config_path or os.getenv("FUNC_PATCH_CONFIG", DEFAULT_CONFIG_FILE))
    if not path.is_absolute():
        # 相对路径按当前工作目录解析（部署时通常在项目根）
        path = Path.cwd() / path

    if _HAS_TOML and _toml is not None and path.is_file():
        try:
            with path.open("rb") as f:
                data = _toml.load(f)
            section = data.get("funcpatch", data)  # 兼容有无 [funcpatch] 前缀
            default_owner = str(section.get("default", {}).get("owner", default_owner))
            for target, owner in (section.get("targets") or {}).items():
                target_owners[str(target)] = str(owner)
        except Exception as exc:  # 配置错误不致命，回退到 env
            print(f"[funcpatch] 配置文件读取失败（已忽略）：{exc}", file=sys.stderr)

    return SelectionConfig(default_owner, target_owners, enabled)
