# 与成熟项目的功能对比

本项目通读并审计了三个成熟开源项目的完整公开功能面（wrapt 2.5.2 / gorilla 0.5.0 / pluggy 1.7.0），
逐项决定每一项能力是"**透传**"、"**借鉴**"还是"**明确不做**"。

结论不是抄功能，而是围绕 funcpatch 的核心不变式——**一个目标在一次部署中最多一个 owner 生效**。

## 为什么区分"透传"与"重造"

wrapt 的 `FunctionWrapper` 构造时做了大量精细工作（源码中 70 余行注释）：Python 3 没有 unbound method，
判断被包装对象是实例方法、类方法还是静态方法无法 fool-proof，wrapt 通过检查原始类型、`__qualname__`、
绑定状态等综合判断，并接受"极少数情况可能判断错"。

这种经过千锤百炼的逻辑，自己重写必然出错。签名保留、`enabled` 的求值时机（绑定 vs 调用）、
代理的 100+ 特殊方法转发，都是 wrapt 的核心价值。funcpatch 的职责是**让用户在 `PatchSpec` 里声明，
然后透传**。

同理，`resolve_owner` 的 MRO 归属语义、`unwrap_object` 的槽位记录等深度耦合 wrapt 内部的能力，
也只透传、不重新实现。

## wrapt 2.5.2（50 个公开名称）

完整清单见 wrapt 的 `__init__.py`。funcpatch 的采纳情况：

| 类别 | 代表能力 | 决策 |
|---|---|---|
| 透明代理 | `ObjectProxy` / `FunctionWrapper` / `LazyObjectProxy` / `WeakFunctionProxy` | **全量透传**（`funcpatch.bridge`） |
| 装饰器 | `decorator` / `function_wrapper` / `lru_cache` / `with_signature` / `with_doc` | **全量透传** |
| 调用约定桥接 | `async_to_sync` / `sync_to_async` / `mark_as_sync` / `mark_as_async` / `synchronized` | **全量透传** |
| 补丁应用 / 链诊断 | `apply_patch` / `unwrap_object` / `wrap_object` / `find_wrapper` / `wrapper_chain` / `unwrapped` | **全量透传** |
| 导入钩子 | `register_post_import_hook` / `when_imported` / `discover_post_import_hooks` | **全量透传** |
| 哨兵 / 异常 | `MISSING` 与 6 个异常类 | **全量透传**（与 funcpatch 自身冲突的加 `Wrapt` 前缀，如 `WraptPathResolutionError`） |

**不重造**：以上全部是 `from wrapt import X` 的直接 re-export，不含任何自研代理逻辑。
用户只需 `from funcpatch import ObjectProxy, decorator, ...`，无需依赖 wrapt 私有路径。

## gorilla 0.5.0

| 能力 | 决策 |
|---|---|
| `Patch` / `Settings` 数据模型 | funcpatch 已有更强的 `PatchSpec`（owner / hash / mode / enabled），不重复 |
| `@patch` / `@patches` 装饰式声明 | funcpatch 已有，且增加 `tags` / `property_part` |
| `get_attribute`（描述符安全访问） | **借鉴**：`funcpatch.get_attribute` 用 `object.__getattribute__` 沿 MRO 查找 |
| `get_base`（解包 bound method / property） | **借鉴**：`funcpatch.get_base` |
| `_get_members`（MRO 遍历、去重、排序） | **借鉴**：`funcpatch.get_members` |
| `create_patches`（批量生成 Patch） | **借鉴**：`funcpatch.create_patches`，支持 `target_prefix` / filter / MRO |
| `find_patches`（递归扫描装饰式声明） | **借鉴**：`funcpatch.find_patches`，能发现 classmethod 底层函数上的声明 |
| `allow_hit` / `store_hit` 命中栈 | **明确不做**：违反单一生效不变式（funcpatch 用进程级占用表保证唯一） |
| id-based 多层 revert | **明确不做**：同上，单一生效无多层栈 |

## pluggy 1.7.0

pluggy 的价值是 **1:N 回调分发**；funcpatch 是 **1:1 实现替换**。
因此多回调相关能力全部明确不做：

| 能力 | 决策 |
|---|---|
| `firstresult` / `historic` / `call_extra` / `subset_hook_caller` | **不做**：单 owner 无意义 |
| `tryfirst` / `trylast` / `hookwrapper` / `optionalhook` / `specname` | **不做**：排序与多回调堆叠相关 |
| hookspec / hookimpl 标记体系 | **不做**：funcpatch 的 `PatchSpec` + `@patch` 已是等价声明层 |
| 注册前校验（no-partial-mutation） | funcpatch 已有 `apply_all` / `transaction` 原子回滚 |
| 重复注册检测 / 冲突检测 | funcpatch 已有 `ConflictError` + 进程级占用表 |
| `set_blocked` / `is_blocked` / `unblock` | **借鉴**：`Registry.block_owner` / `unblock_owner` / `is_blocked` |
| 事件监控（before / after） | **借鉴**：`Registry.add_listener`（apply / revert / reject 事件） |
| 警告分类（`PluggyWarning`） | **借鉴**：`FunCPatchWarning` / `DeprecatedTargetWarning` |
| 部署期签名校验（`_verify_hook`） | **借鉴**：`validate(..., check_signature=True)` |
| `load_setuptools_entrypoints` | funcpatch 已有 `discover_from_entry_points` |

## funcpatch 自研（三个项目都不提供）

| 能力 | 说明 |
|---|---|
| **owner 单一生效不变式** | 进程级占用表保证唯一，跨 Registry 实例同样成立 |
| **三层 owner 选择** | toml `[targets]` > toml `[default]` > 环境变量 |
| **版本校验** | `expect_hash` 校验目标函数；`expect_deps_hash` 额外校验其同模块依赖 |
| **冲突检测 + 审计** | 冲突、拒绝原因结构化记录，`AuditReport.to_dict()` 可导出 |
| **添加新成员** | `mode="add"` 为主分支不存在的属性/方法提供安装与回滚 |
| **部署前预演** | `validate()` / `Registry.plan()` 只读检查，不改任何状态 |
| **批量事务** | `apply_all()` / `transaction()` 在部分失败时自动回滚 |

## 有意不做

| 能力 | 原因 |
|---|---|
| 多层补丁链 splice | 违反单一生效不变式，会掩盖误部署（两个客户的包同时装上） |
| `store_hit` 栈式命中 | 同上，funcpatch 只存一层 original |
| 自研对象代理 | wrapt 已有 100+ 特殊方法转发，重造必然出错 |
| 自研 import hook | wrapt 的 post-import-hook 已处理递归防护与 loader 还原 |
| 行级改写（改函数体内部的某几行） | 能力与代价不匹配，见根目录 `ARCHITECTURE.md` 的决策 8 |

## 结论

funcpatch 的自研范围严格限定在 wrapt / gorilla / pluggy 都不提供的 **owner 治理层**：
单一生效不变式、三层 owner 选择、版本校验、审计、进程级占用、批量事务。
其余成熟能力要么直接透传（wrapt 50 项），要么借鉴算法模式（gorilla / pluggy），
要么因违反不变式而明确不做，并记录在案。
