# 开发指南

面向要修改 funcpatch 代码的贡献者。使用方式见 [USAGE.md](USAGE.md)，
API 参考见 [API.md](API.md)，架构决策见根目录
[ARCHITECTURE.md](../ARCHITECTURE.md)。

## 开发环境

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,toml,web]"
```

`web` extra 用于 FastAPI 集成测试；不装则该测试自动跳过。

## 提交前必须全部通过

```bash
ruff check .
ruff format --check .
basedpyright
pytest -q --cov=funcpatch --cov-report=term-missing
```

要求：静态检查零错误；测试全部通过；覆盖率 ≥ 90%（`pyproject.toml` 中 `fail_under = 90`）。

## 编码约定

- Python >= 3.10；使用内置泛型（`dict` / `list` / `X | None`），不用 `typing.Dict` 等废弃类型。
- 行宽 100；ruff format 统一格式。
- basedpyright standard 模式零错误。
- 注释与文档同一文件内语言保持一致。

## 新增能力的原则

1. wrapt 已提供的能力（签名保留、enabled、诊断、作用域补丁等）→ **透传，不重造**。
2. 仅在 owner 治理层（选择 / 校验 / 审计 / 生命周期）自研。
3. 违反单一生效不变式的提案需先讨论。

逐项对比与已有决策见 [COMPARISON.md](COMPARISON.md)。

## 测试要求

- 每个新能力必须有对应测试；边界场景（async / 描述符 / 并发 / 回滚）单独测试。
- post-import-hook 相关行为需有端到端测试覆盖。
- 测试按功能域分文件，不混放不同类别的用例。
- **新增测试要验证真实行为**，不能只断言"不抛异常"或恒真条件。

### 验证测试本身是否有效

新增或修改关键逻辑后，用变异测试确认新测试抓得住问题：临时改坏源码，
确认对应测试失败，然后恢复源码。

例：把 `registry.py` 里 `expect_deps_hash` 的校验分支改成 `if False:`，
若对应测试仍通过，说明该测试没有真正覆盖这条路径。

## 文档

- 公开 API 变更需同步 `docs/API.md`。
- 行为变更需同步 `docs/USAGE.md` 与 `CHANGELOG.md`。
- 架构决策变更需在 `ARCHITECTURE.md` 补一条决策记录（说明依据与取舍）。
