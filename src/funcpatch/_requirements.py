"""部署包版本约束的轻量校验：避免引入 packaging 硬依赖。

支持逗号分隔的版本子句（如 "app>=2.3,<3"），子句可省略包名（沿用前一个）：
  ==, !=, >=, <=, >, <, ~=

版本比较区分预发布：rc / alpha / beta 排在同版本正式版之前。
仅用于 funcpatch 补丁的 requires 字段；不做完整 PEP 508 解析（URL / marker 不支持）。
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version

_CLAUSE_RE = re.compile(
    r"^\s*(?:([A-Za-z0-9_.-]+)\s*)?(==|!=|>=|<=|~=|>|<)?\s*"
    r"([0-9][0-9A-Za-z.*+!_-]*)\s*$"
)
_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*$")

_PRERELEASE_ORDER = {
    "a": 0,
    "alpha": 0,
    "b": 1,
    "beta": 1,
    "rc": 2,
    "c": 2,
    "pre": 2,
    "preview": 2,
}


def _version_key(version_str: str) -> tuple[tuple[int, int], ...]:
    """把版本串归一为可比较的段键。

    每段是 (kind, value)，均为 int，避免跨类型比较：
      kind=1 正式数字段，value=数字；
      kind=0 预发布段，value=序号（a<b<rc）或预发布编号；
      kind=2 未知文本段，value=按字符序映射的稳定编码。
    预发布排在正式之前，因此 2.6rc1 < 2.5、2.10rc1 < 2.9 这类错误不再出现。
    """
    key: list[tuple[int, int]] = []
    for seg in re.split(r"[.\-+_]", version_str.strip().lower()):
        if not seg or seg == "final":
            continue
        # 把 "5rc1" 拆成 "5","rc1"，使数字段与预发布段各自独立。
        for token in re.findall(r"\d+|[a-z]+\d*", seg):
            if token.isdigit():
                key.append((1, int(token)))
                continue
            match = re.match(r"^(a|alpha|b|beta|rc|c|pre|preview)(\d*)$", token)
            if match:
                order = _PRERELEASE_ORDER[match.group(1)]
                seq = int(match.group(2) or 0)
                # 用 (0, order*1000+seq) 表达预发布顺序；正式段 kind=1 恒在其后。
                key.append((0, order * 1000 + seq))
            else:
                code = 0
                for ch in token:
                    code = code * 31 + ord(ch)
                key.append((2, code))
    return tuple(key)


def _compare(actual: str, op: str, expected: str) -> bool:
    a, e = _version_key(actual), _version_key(expected)
    n = max(len(a), len(e))
    a_pad = a + ((1, 0),) * (n - len(a))
    e_pad = e + ((1, 0),) * (n - len(e))
    if op == "==":
        return a_pad == e_pad
    if op == "!=":
        return a_pad != e_pad
    if op == ">=":
        return a_pad >= e_pad
    if op == "<=":
        return a_pad <= e_pad
    if op == ">":
        return a_pad > e_pad
    if op == "<":
        return a_pad < e_pad
    if op == "~=":
        # 兼容版本：>= expected 且落在同一前缀段内。单段约束按 major 上限处理。
        e_parts = [p for p in re.split(r"[.\-+_]", expected) if p]
        if len(e_parts) < 2:
            head = e_parts[0] if e_parts else "0"
            upper = str(int(head) + 1) if head.isdigit() else None
            return a_pad >= e_pad and (upper is None or a_pad < _version_key(upper))
        prefix = e_parts[:-1]
        a_parts = [p for p in re.split(r"[.\-+_]", actual) if p]
        return a_pad >= e_pad and a_parts[: len(prefix)] == prefix
    return False


def _parse_requirement(req: str) -> list[tuple[str, str | None, str | None]] | None:
    """解析单条 requires，返回 (包名, 算子, 版本) 列表；非法返回 None。"""
    clauses: list[tuple[str, str | None, str | None]] = []
    current_name: str | None = None
    for segment in req.split(","):
        name_match = _NAME_RE.match(segment)
        if name_match and not _CLAUSE_RE.match(segment):
            name = name_match.group(1)
            assert name is not None
            current_name = name
            clauses.append((name, None, None))
            continue
        match = _CLAUSE_RE.match(segment)
        if match is None:
            return None
        name, op, expected = match.group(1), match.group(2), match.group(3)
        if name:
            current_name = name
        if current_name is None:
            return None
        clauses.append((current_name, op or "==", expected))
    return clauses or None


def check_requires(requires: tuple[str, ...]) -> list[str]:
    """校验全部约束，返回不满足的原因列表（空表示全部满足）。"""
    problems: list[str] = []
    for req in requires:
        clauses = _parse_requirement(req)
        if clauses is None:
            problems.append(f"invalid requirement: {req}")
            continue
        for name, op, expected in clauses:
            try:
                installed = version(name)
            except PackageNotFoundError:
                problems.append(f"package not installed: {name}")
                continue
            if op is None or expected is None:
                continue
            if not _compare(installed, op, expected):
                problems.append(f"version conflict: {name}{op}{expected} but installed {installed}")
    return problems
