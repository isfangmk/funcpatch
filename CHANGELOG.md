# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-11-27

首次公开发布。

### 核心能力

- **主分支零改动**：补丁在目标模块导入时动态应用，不修改任何目标源码。
- **单一生效不变式**：一个目标在整个进程内最多一个 owner 的实现生效，
  由进程级占用表保证，跨 Registry 实例同样成立。
- **部署层决策**：生效的 owner 由 `funcpatch.toml` 或环境变量决定，不写死在代码里。
  `FUNC_PATCH_ENABLED=false` 可全局关闭补丁。
- **失败安全**：未命中 owner、版本校验失败时走原实现，不猜测、不静默失效。
- **三种替换模式**：`replace` 完整替换函数体、`wrap` 包装并复用原逻辑、
  `add` 添加主分支中原本不存在的方法或属性。
- **完整函数类型支持**：普通函数、async 函数、async 生成器、
  classmethod / staticmethod / property（含 getter / setter / deleter 分部分替换）。
- **版本校验**：`expect_hash` 校验目标源码，`expect_deps_hash` 额外覆盖目标调用的
  同模块 helper；主分支改动后拒绝应用并告警。
- **部署约束与告警**：`requires` 支持 PEP 508 风格的版本约束，
  `deprecated` 标记废弃目标并发出警告。
- **部署前校验**：`validate()` / `Registry.plan()` 只读预演，
  检查目标可解析、hash 匹配、owner 命中，不修改任何状态。
  `validate(..., check_signature=True)` 可额外检查替代实现与目标的参数兼容性。
- **批量事务**：`apply_all()` / `transaction()` 在部分失败时自动回滚，不留半成品。
  `revert_where()` 可按 owner / 标签 / 模块批量回滚。
- **owner 阻塞与事件监听**：`block_owner()` / `unblock_owner()` / `is_blocked()`
  可让指定 owner 永不参与选择；`add_listener()` 监听 apply / revert / reject 事件。
- **严格模式**：`strict=True` 时在拒绝点抛出领域异常，默认保持 fail-safe。
- **上下文抑制**：`suppress_patches()` 基于 ContextVar，异步任务间互不干扰。
- **作用域补丁**：`scoped_patch` / `transient_patch` 仅在特定范围生效，退出自动回滚。
- **来源追溯**：`get_spec_origin()` 可查出补丁来自哪个发行包与 entry point。
- **可观测**：`AuditReport` 记录每次应用的生效者、冲突者与拒绝原因，
  支持 `to_dict()` 导出与增量打印。

### 公开 API

- 数据与配置：`PatchSpec`、`SelectionConfig`、`load_config()`、`normalize_target()`、
  `parse_enabled()`。
- 注册表：`Registry`（apply / revert / apply_all / transaction / plan / 诊断 /
  owner 阻塞 / 事件监听）、`ApplyResult`。
- 生命周期：`bootstrap()` / `shutdown()` / `get_registry()` / `get_report()`。
- 校验：`validate()` / `validate_spec()` / `ValidationResult` / `check_requires()`。
- 诊断：`is_patched()` / `get_applied_info()` / `get_wrapper()` / `unwrap_target()` /
  `claims_snapshot()` / `clear_claim()` / `claim_key()`。
- 审计：`AuditReport`（`entries` / `conflicts` / `rejections`、`to_dict()`、
  `clear()`、增量 `log()`）。
- 版本校验辅助：`source_hash()` / `dependency_hash()`。
- 发现：`discover_all()` / `discover_from_directory()` /
  `discover_from_entry_points()` / `get_spec_origin()`。
- 声明式：`@patch(...)` / `@patches(...)` / `collect_patched()`。
- 上下文抑制：`suppress_patches()` / `is_suppressed()`。
- 作用域补丁：`scoped_patch()` / `transient_patch()`。
- 描述符安全自省：`get_attribute()` / `get_base()` / `get_members()` /
  `default_filter()` / `get_original_attribute()`。
- 批量生成：`create_patches()` / `find_patches()`。
- 异常与警告：`FunCPatchError` / `PathResolutionError` / `TargetNotFoundError` /
  `PatchRejectedError` / `ConflictError` / `FunCPatchWarning` /
  `DeprecatedTargetWarning`。
- 桥接层透传 wrapt 的 50 个公开能力，从 `funcpatch` 顶层直接可用。

### CLI

- `funcpatch plan`：预演所有补丁（只读），含 `--diff` 展示替换前后的源码差异。
- `funcpatch validate`：校验补丁 spec（只读），含 `--config` 检查 owner 命中。
- `funcpatch hash`：批量输出目标源码 hash 与依赖闭包 hash，供刷新版本校验值。
- `funcpatch claims`：查看当前进程的目标占用情况。

### 修复

- 目标模块导入失败时，部署前校验不再抛出异常中断整批检查，改为报告
  `target module import failed: <原因>`。
- 已打补丁目标的版本校验不再被替代实现污染：补丁生效后目标位置上的对象已是
  替代实现，直接取源码得到的是替代实现的 hash，导致版本校验误报 "hash mismatch"
  （原实现其实没变过），且 `funcpatch hash` 采集到替代实现的 hash，
  填进 `expect_hash` 后补丁永远无法应用。现从占用该目标的 Registry 取出原实现再比对。
- 目标已被其它 owner 占用时，拒绝原因由真实的占用冲突给出，不再被
  "hash mismatch" 掩盖而误导排查；`plan` 与 `apply` 对同一次冲突给出相同原因。
- 模块被 `importlib.reload` 重建后，补丁随旧模块对象一并失效，但诊断与占用状态
  仍按旧状态报告。现核对目标属性上是否仍带补丁标记来判断是否真的生效；
  占用方补丁已失效时，其占用视为陈旧，新实例可接管。
- 目标模块 reload 后再次 `apply(target)` 会谎报成功却不实际生效（幂等判断只看
  内部记录）。现幂等判断同样以"补丁当前确实生效"为准，会真正重新安装补丁。
- `mode="add"` 不再绕过部署护栏：此前 add 模式在解析目标后直接安装属性，
  跳过了其它模式都会执行的版本约束、`enabled` 开关与废弃告警。
- 作用域补丁同样受版本约束、依赖闭包校验与废弃告警约束，
  避免 CI 校验通过而运行时行为不一致。
- `bootstrap()` 注册加载钩子前先发布注册表状态：目标模块若在引导前已被导入，
  wrapt 会同步触发钩子，此前钩子读到的注册表为空，补丁被静默丢弃且不再重试。
- 版本约束支持逗号分隔的多个子句与省略包名的链式写法；
  版本比较区分预发布，`2.6rc1` 不再被判定为小于 `2.5`。
- property 部分回滚不再清掉其他 owner 打在其余部分上的补丁，也不会让旧补丁"复活"；
  以首次打补丁前的 property 为基线，只恢复目标部分。
- `transient_patch` 支持递归/重入调用同一被装饰函数，不再误报"目标已被占用"；
  按线程记录重入深度，只有最外层持有与释放占用。
- `transaction()` 改用真正的 undo log，支持块内 revert→reapply 与嵌套事务，
  异常时恢复到进入时状态；回滚失败如实报告，不再谎报成功。
- `plan()` 与 `apply()` 结论一致：已应用目标预演为幂等成功，
  陈旧占用预演为冲突，不再给出错误的"可以应用"。
- 上下文局部抑制接入补丁执行，异步任务间互不干扰，嵌套安全。
- strict 模式下 post-import-hook 内的异常被隔离并记录，
  不再中断无关业务模块的 import。
- `Registry.get_wrapper()` 与诊断解析改用静态属性读取，不再触发 property getter。
- 异步生成器目标遇到调用约定不同的替代实现时不再抛 `TypeError`。
- 目录发现对补丁模块的失败隔离扩大到全部异常，语法错误与运行时异常
  不再中断整个发现过程。

### 测试

- 349 个测试，覆盖率 95%。
- 桥接层 50 个透传名称全部有身份绑定测试，替代仅做存在性检查的弱断言。
- 覆盖描述符保真、async / async 生成器、并发幂等、事务回滚、版本校验、
  部署护栏、模块 reload 后状态等边界场景。
- 修正恒真断言与只验证"不抛异常"的弱断言；线程测试改用事件驱动同步。

### 文档

- README、使用指南、API 参考、功能对比、架构决策记录与开发指南齐备。
- 示例分 basic / modes / packages / fastapi 四组，均可直接运行自检。

### 工具链

- CI 拆分为 lint / test / package 三个作业，覆盖 Python 3.10–3.13。
- lint 作业额外校验示例可运行；package 作业校验已安装包的冒烟测试。
- 发布由 tag 触发的 GitHub Actions 完成：校验版本一致性、重跑质量门、
  发布到 PyPI 并创建 GitHub Release，发布说明从 CHANGELOG 自动生成。

[0.1.0]: https://github.com/isfangmk/funcpatch/releases/tag/v0.1.0
