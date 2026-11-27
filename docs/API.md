# API 参考

本文列出 funcpatch 的全部公开 API。所有名称均从 `funcpatch` 顶层导出。
与成熟项目的逐项功能对比见 [COMPARISON.md](COMPARISON.md)。
使用场景与完整示例见 [USAGE.md](USAGE.md)。

## wrapt 能力桥接（50 个透传名称）

funcpatch 完整透传 wrapt 的成熟工具，**不重造**。以下均从顶层直接可用：

- **代理**：`ObjectProxy`、`BaseObjectProxy`、`FunctionWrapper`、`BoundFunctionWrapper`、
  `CallableObjectProxy`、`LazyObjectProxy`、`AutoObjectProxy`、`WeakFunctionProxy`、
  `AttributeWrapper`、`PartialCallableObjectProxy`、`partial`、`lazy_import`
- **装饰器 / 签名**：`decorator`、`function_wrapper`、`lru_cache`、`with_signature`、
  `with_doc`、`adapter_factory`、`AdapterFactory`、`bind_state_to_wrapper`
- **调用约定**：`async_to_sync`、`sync_to_async`、`mark_as_sync`、`mark_as_async`、`synchronized`
- **补丁 / 链诊断**：`apply_patch`、`unwrap_object`、`wrap_object`、`wrap_object_attribute`、
  `wrap_function_wrapper`、`patch_function_wrapper`、`scoped_function_wrapper`、
  `transient_function_wrapper`、`find_wrapper`、`is_wrapped_by`、`wrapper_chain`、
  `unwrapped`、`resolve_path`、`resolve_owner`、`MISSING`
- **导入钩子**：`register_post_import_hook`、`discover_post_import_hooks`、
  `notify_module_loaded`、`when_imported`
- **wrapt 异常**：`WraptPathResolutionError`、`TargetModuleNotFoundError`、
  `WrapperNotFoundError`、`WrapperNotOutermostError`、`WrapperNotInitializedError`、
  `WrapperChainTooDeepError`

## 描述符安全自省与批量生成（gorilla 模式）

- `get_attribute(obj, name)`：沿 MRO 用 `object.__getattribute__` 查找，绕过描述符协议。
- `get_base(obj)`：递归解包 bound method / classmethod / staticmethod / property 到底层函数。
- `get_members(obj, *, traverse_bases=True, filter_fn=None)`：MRO 遍历去重、按名字排序。
- `default_filter(name, obj)`：排除模块与下划线开头的名字。
- `create_patches(owner, module, root, *, target_prefix="", replacement=None, filter_fn=..., ...)`：
  为类/模块成员批量生成 `PatchSpec`。
- `find_patches(module, *, recursive=True)`：递归扫描装饰式声明（含 classmethod 底层函数）。
- `get_original_attribute(obj, name)`：`get_attribute` 的别名。

## 数据对象

### `PatchSpec(owner, target_module, target_attr, replacement, *, ...)`

冻结的补丁描述。参数：

| 参数 | 类型 | 含义 |
|---|---|---|
| `owner` | `str` | 补丁归属方，部署时选择 |
| `target_module` | `str` | 目标模块点分名，如 `app.core.config` |
| `target_attr` | `str` | 目标属性路径，如 `Settings.build_headers` |
| `replacement` | `Callable` | 替代实现 |
| `expect_hash` | `str` | 目标函数预期源码 hash，空表示不校验 |
| `expect_deps_hash` | `str` | 目标函数 + 同模块依赖的预期联合 hash，空表示不校验 |
| `mode` | `"replace" \| "wrap" \| "add"` | 完全替换 / 包一层 / 添加原本不存在的属性 |
| `enabled` | `bool \| Callable[[], bool]` | 动态开关 |
| `description` | `str` | 说明 |
| `tags` | `tuple[str, ...]` | 标签 |
| `property_part` | `"get" \| "set" \| "delete"` | 目标是 property 时替换哪一部分 |
| `requires` | `tuple[str, ...]` | 部署包版本约束（PEP 508，如 `("app>=2.3,<3")`），不满足则拒绝应用 |
| `deprecated` | `str` | 非空时发 `DeprecatedTargetWarning` |

属性 `.target` 返回目标字符串 `module:attr`。

`mode="add"` 用于给目标类添加主分支里不存在的属性或方法：目标属性必须原本不存在
（存在则拒绝，避免覆盖主分支实现），回滚时删除该属性。

校验：构造时对空字段、非 callable replacement、非法 mode / property_part 抛 `ValueError` / `TypeError`。

### `source_hash(func) -> str`

计算函数源码 SHA-256（截断 16 位）；无法取源码时回退到字节码/repr。用于填 `expect_hash`。

### `dependency_hash(func) -> str`

计算目标函数**与其同模块依赖**的联合 hash：除函数源码外，还包含它通过全局名引用、
且定义在同一模块的函数/类。用于填 `expect_deps_hash`，主分支改动了被调用的 helper 时
也能发现并拒绝应用，避免补丁静默跑在旧假设上。

不递归追踪跨模块依赖（会把第三方库变动算进来，噪声过大）。

CLI 批量获取当前值：

```bash
funcpatch hash --package mypatches
```

### `ApplyResult`

`Registry.apply_all()` 的返回：`.applied`（本次新应用）、`.failed`、`.rolled_back`、
`.preexisting`（批次前已应用、不受回滚影响）、`.ok`。

### `ValidationResult`

`validate()` 的返回项：`.spec`、`.ok`、`.problems`，`.to_dict()` 可导出。

## 配置

### `SelectionConfig(default_owner, target_owners, enabled)`

三层选择规则快照。`.owner_for(target)` 按 `[targets]` > `[default]` > None 返回 owner。

### `load_config(config_path=None) -> SelectionConfig`

从 `FUNC_PATCH_ENABLED`、`FUNC_PATCH_OWNER`、`FUNC_PATCH_CONFIG` / `funcpatch.toml` 加载。
目标键支持点号与冒号两种写法。

### `normalize_target(target) -> str`

把目标键归一为可比较形式（分隔符统一为点号）。

### `parse_enabled(value) -> bool`

解析 `FUNC_PATCH_ENABLED`；缺省开启，`false/0/off/no/空` 关闭。

## 注册表

### `Registry(config, specs, *, strict=False)`

- `select(target) -> (spec | None, skipped_owners)`：按三层规则选唯一 spec。
- `apply(target, report=None) -> bool`：应用；已应用幂等；strict 失败抛异常。
  `mode="add"` 的补丁安装原本不存在的属性，回滚时删除该属性。
- `apply_module(module_name, report=None) -> int`：应用某模块全部目标。
- `apply_all(targets, report=None) -> ApplyResult`：批量应用，失败只回滚本次新应用项，
  批次前已应用的补丁不受影响。
- `transaction()`：上下文管理器，用 undo log 记录改动前状态，异常时恢复到进入时状态；
  支持块内 revert→reapply 与嵌套。
- `revert(target, *, missing_ok=True) -> bool`：回滚；失败保留记录可重试。
- `revert_all() -> int`：回滚全部。
- `revert_where(*, owner=None, tags=(), module=None) -> list[str]`：按条件批量回滚，
  多个条件取交集；都不给等价于 `revert_all()`。
- `get_original(target) -> Callable | None`：原始底层函数（描述符返回其 `__func__`/`fget` 等）。
- `get_wrapper(target)`：当前生效的包装器/替代函数。
- `is_applied(target) -> bool`、`targets() -> list[str]`、`specs_for_module()`、`specs_for_target()`。
  `is_applied` 反映补丁**当前是否真的生效**：除查内部记录外，还核对目标属性上
  是否仍带补丁标记——目标模块被 `importlib.reload` 重建后旧补丁已失效，
  此时返回 `False`。
  目标模块被 reload 后补丁不会自动恢复（wrapt 的后导入钩子只在模块**首次**
  导入时触发），再次调用 `apply(target)` 会重新安装补丁。
- `plan(*, include_diff=False) -> list[dict]`：预演每个目标（含占用冲突检查）。注意：hash 校验可能需要
  import 目标模块，该 import 可能触发已注册的后导入钩子。
  `include_diff=True` 时，额外为 `replace` 模式的补丁生成 unified diff（键 `diff`），
  展示目标实现与替代实现的源码差异；`wrap` 模式与源码不可取时不生成。
- `block_owner(owner)` / `unblock_owner(owner) -> bool` / `is_blocked(owner) -> bool`：
  owner 阻塞状态（pluggy `set_blocked` 模式），被阻塞的 owner 不参与选择。
- `add_listener(listener) -> Callable[[], None]`：注册事件监听器，返回取消函数。
  事件：`apply` / `revert` / `reject`，detail 含 target/owner/mode/reason。

`strict=False`（默认）保持 fail-safe，失败只记录不抛错；`strict=True` 时拒绝点抛领域异常。

## 生命周期

- `bootstrap(config=None, specs=None, *, strict=False) -> Registry`：发现补丁并注册 wrapt post-import-hook。幂等。
- `shutdown() -> int`：回滚全部 + 清空全局状态 + 释放占用。
- `get_registry() -> Registry | None`、`get_report() -> AuditReport | None`。

## 发现

- `discover_all(package, group, filter_fn=None, *, recursive=False) -> list[PatchSpec]`
- `discover_from_directory(package, filter_fn=None, *, recursive=False)`
- `discover_from_entry_points(group)`
- `get_spec_origin(spec) -> dict | None`：entry point 来源（distribution / version / ep_name），
  非 entry point 发现的 spec 返回 `None`；命中时写入审计条目。

## 版本约束与抑制

- `check_requires(requires) -> list[str]`：校验 PEP 508 风格版本约束，返回不满足原因（空表示满足）。
  支持 `==` / `!=` / `>=` / `<=` / `>` / `<` / `~=`，逗号分隔多个条件，无需第三方依赖。
- `suppress_patches()`：上下文管理器，在当前上下文临时旁路所有补丁（嵌套安全）。
- `is_suppressed() -> bool`：当前上下文是否处于抑制状态。

## 声明

- `patch(owner, module, attr, *, ...)`：装饰函数为一条 spec，支持 `property_part`。
- `patches(declarations, *, ...)`：一个函数声明多条 spec。
- `collect_patched(module_or_class)`：收集装饰式声明（用 `vars()`，不触发 property 副作用）。

## 作用域补丁

- `scoped_patch(module, attr, spec)`：with 块内生效；校验 hash、检查占用。
- `transient_patch(module, attr, spec)`：被装饰函数调用期间生效；同样校验。
  装饰时即完成校验，配置错误在装饰处直接暴露。

## 诊断

- `is_patched(target, registry=None) -> bool`：目标是否已打补丁；给出 `registry` 时以其状态为准
  （该状态反映补丁当前是否真的生效）。
- `get_applied_info(target) -> dict | None`：补丁标记信息，含 `owner` / `target` / `targets`
  （共用同一 replacement 的全部目标）；未打补丁返回 `None`。
- `get_wrapper(target)`：当前生效的包装器/替代函数。
- `unwrap_target(target)`：拆掉包装链，恢复被包装的原函数。
  **有副作用**：调用后补丁标记随之消失，`is_patched()` 转为 `False`；
  仅用于诊断时优先用 `get_wrapper()`。
- `claims_snapshot() -> dict`：当前每个目标被哪个 owner 占用。
- `clear_claim(target, *, property_part="get") -> bool`：显式释放占用（陈旧占用恢复）。
- `claim_key(target, property_part="get") -> str`：占用键（property 各部分独立）。

## 校验

- `validate(specs, owner=None, *, check_signature=False, config=None) -> list[ValidationResult]`
- `validate_spec(spec, owner=None, *, check_signature=False) -> ValidationResult`
  - `check_signature=True` 时检查替代实现参数个数，不匹配记录 warning 并发
    `FunCPatchWarning`，不影响 `ok`（借鉴 pluggy `_verify_hook`）。
  - `config` 给出时，按目标解析实际生效的 owner（`[targets]` 精确指定优先于 `[default]`）
    并检查它是否命中某条 spec：部署配置了 owner 却没有任何补丁命中时会报出
    `owner mismatch`，与 `plan()` 的结论一致。未配置 owner 时不作为问题。
  - `ValidationResult.warnings` / `.to_dict()["warnings"]` 承载警告信息。

## 审计

`AuditReport`：`.entries` / `.conflicts` / `.rejections`、`.clear()`、`.to_dict()`、
`.log()`（只打印增量）、`.new_since_last_log()`。

## 异常

异常：`FunCPatchError`（基类）、`PathResolutionError`、`TargetNotFoundError`、
`PatchRejectedError`、`ConflictError`（均继承 `FunCPatchError`）。
wrapt 异常以 `Wrapt*` 前缀透传，见"wrapt 能力桥接"一节。

警告：`FunCPatchWarning(UserWarning)`（基类）、`DeprecatedTargetWarning`。

## CLI

```bash
funcpatch plan --package mypatches      # 预演
funcpatch plan --package mypatches --diff  # 预演并展示源码差异
funcpatch claims                        # 查看进程占用
funcpatch validate --package mypatches  # 校验
funcpatch validate --config funcpatch.toml  # 校验并检查 owner 命中
funcpatch hash --package mypatches      # 批量计算源码/依赖 hash
```
