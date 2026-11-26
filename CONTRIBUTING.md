# 贡献指南

欢迎贡献。开始前请阅读 [ARCHITECTURE.md](ARCHITECTURE.md) 理解设计原则，
尤其是"单一生效不变式"与"透传 wrapt，不自研"两条。

## 开发环境

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,toml]"
```

## 提交前必须全部通过

```bash
ruff check .
ruff format --check .
basedpyright
pytest -q
```

## 编码约定

- Python >= 3.10；使用内置泛型（`dict` / `list` / `X | None`），不用 `typing.Dict` 等废弃类型。
- 行宽 100；ruff format 统一格式。
- 基于静态检查（basedpyright standard 模式）零错误。
- 注释与文档使用中文或英文均可，但同一文件内保持一致。

## 新增能力的原则

1. wrapt 已提供的能力（签名保留、enabled、诊断、作用域补丁等）→ **透传，不重造**。
2. 仅在 owner 治理层（选择 / 校验 / 审计 / 生命周期）自研。
3. 违反单一生效不变式的提案需先讨论。

## 测试要求

- 每个新能力必须有对应测试；边界场景（async / 描述符 / 并发 / 回滚）单独测试。
- post-import-hook 相关行为需有端到端测试覆盖。

## 提交与 PR

- 提交信息使用 Conventional Commits（如 `feat:` / `fix:` / `docs:` / `test:`）。
- PR 描述说明动机、方案、测试，以及对向后兼容性的影响。
