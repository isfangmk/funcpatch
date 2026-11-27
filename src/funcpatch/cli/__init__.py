"""funcpatch 命令行工具：部署诊断与校验。

子命令：
  plan      预演所有补丁（只读，不修改目标函数）
  claims    查看进程级目标占用情况
  validate  校验补丁 spec 能否应用（只读）
  hash      计算每条补丁的目标源码 hash 与依赖闭包 hash（批量刷新用）

用法（示例脚本）：
  python -m funcpatch.cli plan --package mypatches
  python -m funcpatch.cli claims
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from funcpatch import claims_snapshot, dependency_hash, discover_all, source_hash, validate
from funcpatch.config import load_config
from funcpatch.registry import Registry


def _cmd_plan(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    specs = discover_all(args.package)
    registry = Registry(cfg, specs)
    plan = registry.plan(include_diff=args.diff)
    if args.diff:
        _print_plan_with_diff(plan)
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if all(p["would_apply"] for p in plan) else 1


def _print_plan_with_diff(plan: list[dict[str, object]]) -> None:
    """按目标打印可读的预演结果，diff 用 unified diff 形式展示。"""
    for entry in plan:
        target = entry.get("target", "")
        status = "会应用" if entry.get("would_apply") else f"不应用（{entry.get('reason', '')}）"
        mode = entry.get("mode", "-")
        print(f"\n=== {target} ===")
        print(f"owner={entry.get('selected') or entry.get('owner') or '-'}  mode={mode}  {status}")
        diff = entry.get("diff")
        if isinstance(diff, str) and diff:
            print(diff.rstrip())
        elif mode == "wrap":
            print("（wrap 模式在运行时包裹原函数、不替换函数体，故无源码差异；")
            print("  其改动逻辑在补丁的 replacement 中）")
        else:
            print("（无可用 diff：目标或替代实现的源码不可取）")


def _cmd_claims(_args: argparse.Namespace) -> int:
    print(json.dumps(claims_snapshot(), ensure_ascii=False, indent=2))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    specs = discover_all(args.package)
    # 传入配置，校验才会检查"配置的 owner 是否命中某条补丁"——
    # 否则部署配置了 owner 却没有任何补丁命中时，校验仍会报通过。
    results = validate(specs, config=cfg)
    print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
    return 0 if all(r.ok for r in results) else 1


def _cmd_hash(args: argparse.Namespace) -> int:
    """批量计算每条补丁的源码 hash 与依赖 hash，输出 JSON 供刷新。"""
    import importlib

    import wrapt.patches as wrapt_patches  # type: ignore[import-untyped]

    from funcpatch._descriptors import unwrap_descriptor
    from funcpatch._targeting import resolve_original

    specs = discover_all(args.package)
    rows = []
    for spec in specs:
        module, _sep, attr_path = spec.target.partition(":")
        try:
            module_obj = importlib.import_module(module)
            _parent, _attr, original = wrapt_patches.resolve_path(module_obj, attr_path)
            raw = unwrap_descriptor(original, spec.property_part)
            if raw is None or not callable(raw):
                raise ValueError("target has no callable")
            # 目标已被某个 Registry 接管时，当前位置上的对象是替代实现；
            # 直接取源码会采到替代实现的 hash，填进 expect_hash 后补丁永远无法应用。
            raw = resolve_original(spec.target, spec.property_part, raw)
            rows.append(
                {
                    "target": spec.target,
                    "owner": spec.owner,
                    "source_hash": source_hash(raw),
                    "dependency_hash": dependency_hash(raw),
                    "current_expect_hash": spec.expect_hash,
                    "current_expect_deps_hash": spec.expect_deps_hash,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "target": spec.target,
                    "owner": spec.owner,
                    "error": str(exc),
                }
            )
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0 if all("error" not in r for r in rows) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="funcpatch", description="funcpatch 部署诊断工具")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="预演补丁（只读）")
    plan.add_argument("--package", default="funcpatch.patches")
    plan.add_argument("--config", default=None)
    plan.add_argument("--diff", action="store_true", help="展示替换前后的源码差异")
    plan.set_defaults(func=_cmd_plan)

    claims = sub.add_parser("claims", help="查看进程目标占用")
    claims.set_defaults(func=_cmd_claims)

    validate_cmd = sub.add_parser("validate", help="校验补丁 spec（只读）")
    validate_cmd.add_argument("--package", default="funcpatch.patches")
    validate_cmd.add_argument("--config", default=None)
    validate_cmd.set_defaults(func=_cmd_validate)

    hash_cmd = sub.add_parser("hash", help="批量计算目标源码/依赖 hash")
    hash_cmd.add_argument("--package", default="funcpatch.patches")
    hash_cmd.set_defaults(func=_cmd_hash)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
