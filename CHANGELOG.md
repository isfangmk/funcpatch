# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-11-26

### 新增

- `PatchSpec` 补丁数据对象：owner / target / replacement / expect_hash / enabled / mode。
- 单一生效不变式：一个目标函数在部署中最多一个 owner 生效，冲突时告警。
- 三层 owner 选择：`funcpatch.toml [targets]` > `[default]` > 环境变量 `FUNC_PATCH_OWNER`。
- 双发现机制：目录扫描（支持 filter 与装饰式声明）+ entry point 组 `funcpatch.patches`。
- 基于 wrapt 的 post-import-hook 加载器：目标模块首次导入时延迟应用补丁。
- Registry：apply / revert / apply_module / revert_all / 诊断，RLock 线程安全。
- 版本校验 `expect_hash`：目标函数源码 hash 变化时拒绝应用并告警。
- 审计日志：生效、冲突、拒绝原因。
- 完整函数类型支持：普通函数、async、classmethod / staticmethod / property。
- 透传 wrapt 能力：签名保留、`enabled` 动态开关、`scoped_patch` / `transient_patch`、
  `is_patched` / `get_applied_info` 诊断。
- 装饰式声明 `@patch(...)` 与 `collect_patched`。
- 自定义异常类型。
- CI：Python 3.10-3.13 矩阵，ruff + basedpyright + pytest。
- 28 个测试，含 post-import-hook 端到端与边界场景。

[0.1.0]: https://github.com/isfangmk/funcpatch/releases/tag/v0.1.0
