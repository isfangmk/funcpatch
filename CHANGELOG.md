# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- `Registry.plan(include_diff=True)`：为 `replace` 模式的补丁生成 unified diff，展示
  目标实现与替代实现的源码差异，便于发布前确认"这个函数会被改成什么样"。
  `wrap` 模式是运行时拦截而非替换函数体，不生成 diff 以免误导；实现写成 lambda
  或源码不可取时同样不生成。
- CLI 新增 `funcpatch plan --diff`：按目标打印可读的预演结果与源码差异。
- `PatchSpec.expect_deps_hash`：目标函数 + 其**同模块依赖**（通过全局名引用的函数/类）的
  联合 hash。主分支改动了被调用的 helper 时同样拒绝应用，避免补丁静默跑在旧假设上；
  `apply` / `validate` 均校验。
- `dependency_hash(func)`：计算依赖闭包 hash。除目标函数源码外，还纳入它引用且定义在
  同一模块的函数/类；不递归追踪跨模块依赖，避免第三方库变动带来的噪声。
- `mode="add"`：给目标类添加主分支里原本不存在的方法或属性。目标属性必须原本不存在
  （存在则拒绝，避免覆盖主分支实现），回滚时删除该属性，事务回滚同样正确还原。
- CLI 新增 `funcpatch hash` 子命令：批量输出每条补丁的目标源码 hash 与依赖闭包 hash，
  供刷新 `expect_hash` / `expect_deps_hash`。

### 修复

- 目标模块导入失败时，部署前校验不再抛出异常中断整批检查，改为报告
  `target module import failed: <原因>`（此前只有 `resolve_path` 失败被捕获，
  模块本身的导入异常会直接冒泡）。
- `plan` 条目增加 `mode` 字段；`plan --diff` 在无 diff 时按模式分别说明原因
  （wrap 模式是运行时包裹、不替换函数体），不再笼统提示"源码不可取"。
- `bootstrap()` 注册加载钩子前先发布注册表状态：目标模块若在引导前已被导入，
  wrapt 会同步触发钩子，此前钩子读到的注册表为空，补丁被静默丢弃且不再重试。
- 版本约束支持逗号分隔的多个子句（如 `("app>=2.3,<3")`）与省略包名的链式写法；
  此前这类约束会被判为非法，导致补丁被拒。
- 版本比较区分预发布：`2.6rc1` 不再被判定为小于 `2.5`，`2.5rc1` 不再被判定为满足 `>=2.5`。
- 上下文局部抑制同样作用于作用域补丁与临时补丁，此前只对已注册的补丁生效。
- `Registry.get_wrapper()` 改用静态属性读取，不再触发 property getter（避免副作用与异常）。
- 异步生成器目标遇到调用约定不同的替代实现（协程）时不再抛 `TypeError`。
- 目录发现对补丁模块的失败隔离扩大到全部异常，语法错误与运行时异常不再中断整个发现过程。
- `discover_all()` 的过滤条件同样作用于 entry point 来源的补丁。
- `mode="add"` 的事务回滚：异常回退时正确删除已添加的属性（此前 undo 点记录于 apply 之前，
  无法定位宿主对象，导致属性残留）。

### 测试

- 共 313 个测试；覆盖率 94%。
- 补充桥接层 50 个透传名称的身份绑定测试，替代原先仅做存在性检查的弱断言。
- 补充依赖闭包 hash、add 模式、diff 预览、示例可运行性等新能力的测试。
- 修正若干恒真断言与只验证"不抛异常"的弱断言。
- 消除线程测试中的 `sleep` 同步，改为事件驱动，避免慢环境下的偶发失败。

### 工具链

- CI 拆分为 lint / test / package 三个作业，lint 作业独立于 Python 版本矩阵；
  新增示例可运行性校验（`examples.basic.run`、`examples.modes.walkthrough`）。
- package 作业新增已安装包的冒烟测试（应用补丁 → 生效 → 回滚 → 恢复原实现）。
- 新增 tag 触发的发布工作流：校验 tag 与包版本一致，跑完整质量门后发布到 PyPI
  并创建 GitHub Release。
- pytest 固定 `--basetemp` 到仓库内目录，避免系统临时目录不可写时
  `tmp_path` fixture 抛 PermissionError 而掩盖真实测试结果。

## [0.3.0] - 2026-11-26

### 修复

- property 部分回滚不再清掉其他 owner 打在其余部分上的补丁，也不会让旧补丁“复活”；
  以首次打补丁前的 property 为基线，只恢复目标部分。
- `transient_patch` 支持递归/重入调用同一被装饰函数，不再误报“目标已被占用”；
  按线程记录重入深度，只有最外层持有与释放占用。
- `transaction()` 回滚 property 补丁时按具体部分释放占用，不再泄漏 `#set`/`#delete` 键。
- `plan()` 与 `apply()` 结论一致：已应用目标预演为幂等成功；陈旧占用（实例已回收但补丁仍在）
  预演为冲突，不再给出错误的“可以应用”。
- 上下文局部抑制（ContextVar）接入补丁执行，异步任务间互不干扰，嵌套安全。
- strict 模式下 post-import-hook 内的异常被隔离并记录，不再中断无关业务模块的 import。
- 共享同一 replacement 函数打多个目标时，诊断信息按查询目标校准，不再互相覆盖。
- 诊断按目标字符串解析函数时改用静态属性读取，不再执行 property getter（避免副作用/异常）。
- 依赖要求提升至 wrapt>=2.5：桥接层透传的 `with_doc` 自 2.5 引入，2.4 环境下导入会失败。

### 新增

- `PatchSpec.requires`：PEP 508 风格部署包版本约束（如 `("app>=2.3,<3")`），
  `validate`/`plan`/`apply` 均校验，不满足则拒绝；`check_requires()` 可独立调用。
- `PatchSpec.deprecated`：目标废弃标记，命中时发 `DeprecatedTargetWarning` 并写入校验警告。
- `@patch` / `@patches` 支持 `property_part`，可用装饰式语法声明 property 部分补丁。
- `suppress_patches()` / `is_suppressed()`：上下文局部旁路补丁，适合补丁内部复用原函数
  或在单请求内临时关闭定制逻辑。
- `Registry.revert_where(owner=..., tags=..., module=...)`：按条件批量回滚。
- `get_spec_origin(spec)`：entry point 来源追溯（发行包名/版本/ep 名），写入审计条目。

### 签名与审计修正

- 签名校验改用 `signature.bind` 做真实实参绑定，覆盖参数名、默认值、keyword-only 与
  positional-only；此前只数位置参数个数，参数名不匹配会漏检。wrap 模式按 wrapt 协议单独校验。
- `apply_all()` 失败原因取本次新增的 rejection，不再误报批次前遗留的原因。
- `AuditReport.log()` 用 `.get()` 容忍缺字段条目，且游标在打印成功后才推进，
  不再静默吞掉打印异常的目标；并发下游标推进不重复。
- `find_patches(recursive=True)` 修复递归被跳过的问题：函数 base 与对象扫描改用独立 seen 集合。

### 测试

- 共 240 个测试（+1 可选依赖跳过）；覆盖率 95%。
- 补齐此前的覆盖盲区：unwrap/replace 与描述符 get_wrapper、generation 递归、
  transaction 的 BaseException、source_hash 回退稳定性、签名绑定校验。
- 第二轮覆盖审计补充：strict hook 异常隔离、陈旧占用接管与 plan 判定、
  apply 失败释放占用、第三方包装保留、apply 期护栏（requires/deprecated）、
  多线程 transient 占用、CLI 退出码、TOML 异常结构、env kill switch、
  版本算子、entry point 来源与异常、模式组合（wrap×staticmethod/delete/suppress）、
  scoped 错误分支、apply_all strict、异步抑制隔离、版本守卫、自省回退、
  声明式叠加、审计 rejection 日志、桥接语义、查询去重。
- 同步修复审计中暴露的问题：transient_patch 多线程占用提前释放、
  `find_patches(recursive=True)` 递归被跳过、签名绑定对 `*args` 的误报。
- ruff / basedpyright 全部通过。

## [0.2.0] - 2026-11-26

### 修复

- `funcpatch.toml [targets]` 的键同时接受点号（`app.mod.f`）与冒号（`app.mod:f`）形式，
  与文档示例一致；此前点号写法静默失配。
- `FUNC_PATCH_ENABLED=false` 现在真正全局关闭补丁：注册表拒绝应用、loader 不注册加载钩子；
  配置缺省为开启。
- 回滚失败时保留已应用记录，允许重试，原始实现不再永久失联。
- `replace` 模式与 `enabled` 组合下的 async 目标保持 coroutine function 身份。
- `get_original()` 对 classmethod / staticmethod / property 返回底层函数，不再返回 `None`。
- 诊断标记识别改为描述符感知，property 目标的 `is_patched()` / `get_applied_info()` 正确工作。
- `revert()` 对"未应用目标"统一返回 `False`（strict 模式下按 `missing_ok` 抛错）。

### 新增

- 自定义异常真正可用：`Registry(..., strict=True)` 在拒绝点抛
  `PatchRejectedError` / `PathResolutionError` / `TargetNotFoundError`，
  默认仍保持 fail-safe 不抛错；新增 `FunCPatchError` 基类导出。
- 部署前校验 API：`validate(specs)` / `validate_spec(spec)` / `Registry.plan()`，
  只读检查目标可解析、hash 匹配、owner 命中，不修改任何状态。
- 批量事务：`Registry.apply_all()`（失败自动回滚本次已应用项）与
  `Registry.transaction()` 上下文管理器（异常时自动回滚块内新增补丁）。
- 公开诊断 API：`get_wrapper(target)` / `unwrap_target(target)`。
- `property_part="get"|"set"|"delete"`：property 可只替换 getter / setter / deleter，
  其余部分保持不变。
- `bootstrap()` 幂等；新增 `shutdown()` 回滚全部并清空全局状态。
- `discover_from_directory(..., recursive=True)` 递归扫描子包；entry point 支持任意可迭代。
- 装饰式 `@patches([...])` 多声明与 `@patch(..., tags=...)`；
  `collect_patched` 改用 `vars()` 遍历，不触发 property 副作用。
- `AuditReport` 增加 `clear()` / `to_dict()` / 时间戳 / 增量日志（不再每次 import 重复打印）。

### 进程级不变式

- 进程级占用表：把"一个目标只有一个 owner 生效"从单个 Registry 提升到整个进程。
  两个 Registry 实例对同一目标 apply 时，后者被拒绝并记冲突，不再静默覆盖；
  回滚释放占用，陈旧占用（实例已回收但补丁仍在）也会阻止新实例接管。
- `scoped_patch` / `transient_patch` 不再绕过安全约束：同样校验 `expect_hash`、
  检查进程占用，且占用只在作用域/调用期间持有，退出即释放。
- 新增 `claims_snapshot()` 诊断当前目标占用情况。

### 函数类型与集成

- async generator 的 `enabled` 路径保持 `isasyncgenfunction` 身份（FastAPI 等 introspection 框架依赖）。
- 新增 property setter/deleter 的 wrap 模式支持与回滚测试。
- Python 3.11 / 3.12 / 3.13 全部运行完整测试套件。
- 新增 FastAPI 端到端集成示例（`examples/fastapi_integration/`）与测试：
  服务代码零改动，HTTP 请求验证补丁生效/回滚/跨 owner 冲突。
- 新增 CLI 诊断工具：`funcpatch plan` / `claims` / `validate`，
  并注册 `funcpatch` console script。
- 新增完整 API 参考与发布检查清单。

### 功能对齐成熟项目（系统对比 wrapt / gorilla / pluggy 后）

- 穷举对比三个项目的完整公开功能面，逐项决策有记录。
- wrapt 50 个公开能力全量透传：`funcpatch.bridge` 直接 re-export 代理、装饰器、
  调用约定桥接、补丁链诊断、导入钩子与异常；用户无需依赖 wrapt 私有模块路径。
- 借鉴 gorilla：`get_attribute` / `get_base` / `get_members` 描述符安全自省，
  `create_patches` / `find_patches` 批量生成与递归扫描。
- 借鉴 pluggy：`Registry.block_owner` / `unblock_owner` / `is_blocked` owner 阻塞状态，
  `add_listener` 事件监听（apply/revert/reject），`FunCPatchWarning` 警告分类，
  `validate(..., check_signature=True)` 可选签名兼容性校验。

### 事务与并发修正

- `apply_all()` 失败时不再回滚批次前已应用的补丁；`ApplyResult.preexisting` 区分既有项；
  回滚失败如实报告，不再谎报成功。
- `transaction()` 改用真正的 undo log（记录改动前的实际对象），支持块内
  revert→reapply 与嵌套事务，异常时恢复到进入时状态。
- `shutdown()` 不再全局清除其它 Registry 的占用；`bootstrap()` 加锁且 hook 稳定化，
  重新引导不会重复注册，并发引导只产生一个 Registry。
- 占用表增加 `clear_claim()` 公共恢复 API；`property` 的 get/set/delete 使用不同占用键；
  stale 检查移到锁外，避免锁顺序反转。
- `plan()` 检查进程占用表，不再对必然冲突的目标报告 would_apply=True；
  修正"完全只读"表述（hash 校验可能需要 import 目标模块）。
- `check_signature` 修正对 wrapt 包装协议与 classmethod 的误报。
- `AuditReport` 的游标与日志改为锁保护，并发下不丢条目。
- 新增 wrapt 版本守卫：低于 2.4 时给出明确安装提示而非晦涩的 ImportError。
- 修正文档中"两种模式都保留原函数签名"的错误表述。

### 测试

- 共 171 个测试（+1 个可选依赖跳过）；覆盖率 93%。
- 新增 `tests/test_audit_fixes.py` 覆盖上述每个缺陷。
- 构建、干净 venv 安装、CLI 冒烟、`twine check` 全部通过。

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
