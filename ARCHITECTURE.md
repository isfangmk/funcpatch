# 架构决策记录（ADR）

本文记录 funcpatch 的关键设计决策及其源码依据。调研基于 wrapt / gorilla / bytecode / LibCST 的源码通读。

## 决策 1：用 wrapt 做底层替换，不自研 import hook

**依据（wrapt 源码）：**

- `wrapt/importer.py:49 register_post_import_hook`：成熟的 post-import-hook，支持字符串延迟加载（`"module:function"`），模块未导入时登记、已导入时立即触发。
- `wrapt/importer.py:207 ImportHookFinder.find_spec`：用 `in_progress` 旗帜防止回调 `find_spec()` 时无限递归——自研极易遗漏。
- `wrapt/importer.py:191 _self_set_loader`：hook 触发后把 `__loader__` 还原为真实 loader，不污染 import 系统。
- `wrapt/patches.py:415 patch_function_wrapper("module?", name)`：`?` 后缀即"延迟到模块首次导入时应用"，正好解决"引导阶段目标模块不在 sys.path"的问题。

**结论**：底层机制完全借用 wrapt，funcpatch 只在其上做 owner 选择与生命周期管理。

## 决策 2：单一生效，不做优先级堆叠

**依据（gorilla 源码）：**

- `gorilla/gorilla.py:135 Settings`：`allow_hit=False`（默认拒绝覆盖）、`store_hit=True`（保存原属性栈）。
- `gorilla/gorilla.py:267 apply`：多层 patch 用栈保存原属性，支持堆叠。
- `wrapt/patches.py:580 wrapper_chain`：wrapper 链有环检测与深度上限（64）。

**结论**：虽然 wrapt/gorilla 都支持多层堆叠，但 funcpatch 的场景是"多选一"，堆叠会掩盖误部署（两个客户的包同时装上）。因此固定不变式：一个目标最多一个实现生效。冲突时告警，不静默选一个。

## 决策 3：回滚用 handle 身份，不用函数比对

**依据（wrapt 源码）：**

- `wrapt/patches.py:695 unwrap_object`：用安装时返回的 handle 对象做**身份匹配**（`is`），而非相等；因为代理对象会把 `__eq__` 委托给被包装对象。
- `wrapt/patches.py:123 resolve_path` vs `:123 resolve_owner`：安装用 resolve_path（可 shadow 继承属性），回滚用 resolve_owner（回到真正定义处，避免留下影子副本）。

**结论**：registry 保存安装返回的 handle 与 resolve_owner 位置，revert 时交给 wrapt 的 `unwrap_object`。

## 决策 4：版本校验是增量价值

**依据：** gorilla 与 wrapt 都没有"目标函数被改过就拒绝 patch"的机制（gorilla 的 `__hash__` 只用于 Patch 对象比较）。

**结论**：`PatchSpec.expect_hash` 由 funcpatch 引入。apply 前比对目标函数源码 hash，不符则拒绝并告警。这避免核心升级后补丁静默失效——这是 monkey patch 类方案最大的隐患。

## 决策 5：双发现机制

**依据：**

- `wrapt/importer.py:97 discover_post_import_hooks(group)`：entry point 发现。
- `gorilla/gorilla.py:643 find_patches(modules)`：包扫描发现。

**结论**：开发期用目录扫描（`funcpatch/patches/`），生产用 entry point 组 `funcpatch.patches`。两者结果合并、按 `(owner, target, replacement)` 去重。

## 决策 6：不用字节码改写

**依据：**

- bytecode README 明确其定位是"generate and modify bytecode"，指令级操作。
- CPython opcode 在每个小版本变化，字节码改写需要按 Python 版本做测试矩阵。

**结论**：funcpatch 的场景是"大量改函数体"——用完整替代实现（正常 Python 源码）可维护；字节码改写适合"改一两条指令"的场景，不是本项目的目标。

## 决策 7：描述符保真、异步与并发安全

这些是裸 `setattr` 会出错、成熟 patch 框架必须处理的边界情况：

- **描述符保真**（`_descriptors.py`）：wrapt 的 `apply_patch` 只是裸 `setattr`。若用普通函数替换一个 `classmethod`，通过类访问时不会绑定 `cls`，语义改变。`preserve_descriptor` 按原属性类型（classmethod/staticmethod/property）包装 replacement，保持访问语义。回滚时 `resolve_owner` 恢复原始描述符对象。
- **异步函数**：wrapt 的 `FunctionWrapper` 根据被包装函数类型自动适配——包装 async 函数后仍是 coroutine function。`replace` 模式直接替换 async def 实现天然可用；`wrap` 模式的 wrapper 需 `await original(...)`。由 wrapt 保证，funcpatch 不加特殊逻辑（见 `tests/test_boundaries.py`）。
- **并发安全**（`registry.py`）：`apply`/`revert` 用 `RLock` 保护幂等检查与状态写入，避免并发重复应用（借鉴 wrapt importer 的 RLock 用法）。

## 选择规则

三层规则现在全部实现，不为"当前用不到"而砍掉：

```
1. toml [targets] 精确匹配     → owner
2. toml [default]              → owner
3. env FUNC_PATCH_OWNER        → owner
4. 未命中                       → 不应用（fail-safe）
```

配置格式在 v0.1 冻结，保持向后兼容。

## 兼容性

- Python >= 3.10
- `tomllib`（3.11+）/ `tomli`（3.10，可选依赖）：配置文件层
- wrapt >= 1.16：底层替换与 post-import-hook
