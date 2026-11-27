# 发布检查清单

发布前按顺序执行，任何一步失败都不得发布。

## 1. 静态检查

```bash
ruff check .
ruff format --check .
basedpyright
```

## 2. 测试与覆盖率

```bash
pytest -q --cov=funcpatch --cov-report=term-missing
```

要求：全部通过；覆盖率 ≥ 90%（`pyproject.toml` 的 `fail_under`）。

安装开发依赖时带上 `web` extra，否则 FastAPI 集成测试会被跳过：

```bash
pip install -e ".[dev,toml,web]"
```

## 3. 多版本运行时

CI 矩阵在 Python 3.10 / 3.11 / 3.12 / 3.13 全部运行完整测试套件，
多版本兼容性由 CI 保证；本地只需在当前版本跑通即可。

## 4. 构建

```bash
python -m build
```

确认 `dist/` 下同时生成 `.whl` 与 `.tar.gz`，并核对 sdist 内容：

```bash
tar -tzf dist/funcpatch-*.tar.gz
```

应包含 `README.md`、`ARCHITECTURE.md`、`CHANGELOG.md`、`docs/`、`examples/`；
不应包含本地工作区 `plan/`。

## 5. 干净环境安装

```bash
python -m venv /tmp/fp-release-check
/tmp/fp-release-check/Scripts/python.exe -m pip install dist/funcpatch-*.whl
/tmp/fp-release-check/Scripts/python.exe -c "import funcpatch; print(funcpatch.__version__)"
```

## 6. 版本号与文档一致性

- `pyproject.toml` 的 `version` 与 `__init__.py` 的 `__version__` 一致。
- `CHANGELOG.md` 含该版本条目。
- `README.md` 与 `docs/API.md` 反映所有公开 API。
- `docs/` 内的文档链接无失效（相对路径可解析）。

## 7. 元数据

- `pyproject.toml` 的 `[project.urls]` 指向正确仓库。
- `license = "BSD-3-Clause"`（SPDX）。
- `python -m twine check dist/*` 无警告。
- 本地工作区 `plan/` 已被 `.gitignore` 排除，不随仓库发布，也不进源码包。

## 8. 发布

发布由 GitHub Actions 完成：推送 tag 触发 `.github/workflows/release.yml`，
该工作流会校验 tag 与包版本一致、重跑完整质量门、发布到 PyPI 并创建 GitHub Release。

```bash
git tag v0.1.0
git push origin main --tags
```

前置条件：仓库已配置 secret `PYPI_API_TOKEN`（PyPI 的 API token，
在仓库 Settings → Secrets and variables → Actions 中添加）。

推送 tag 后关注 Actions 运行结果：<https://github.com/isfangmk/funcpatch/actions>

也可以手动触发该工作流（workflow_dispatch 输入 tag）。

若改用本机直接发布：

```bash
python -m twine upload dist/*
gh release create v0.1.0 --generate-notes
```
