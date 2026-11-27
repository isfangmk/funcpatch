# 架构决策记录（ADR）

本文记录 funcpatch 的关键设计决策及其源码依据。调研基于 wrapt / gorilla / bytecode / LibCST 的源码通读。

与成熟项目的逐项功能对比与采纳决策见 [docs/COMPARISON.md](docs/COMPARISON.md)；
使用方式见 [docs/USAGE.md](docs/USAGE.md)。

## 决策 1：用 wrapt 做底层替换，不自研 import hook

**依据（wrapt 源码）：**

- `wrapt.importer.register_post_import_hook`：成熟的 post-import-hook，支持字符串延迟加载（`"module:function"`），模块未导入时登记、已导入时立即触发。
- `wrapt.importer.ImportHookFinder.find_spec`：用 `in_progress` 旗帜防止回调 `find_spec()` 时无限递归——自研极易遗漏。
- `wrapt.importer.ImportHookFinder._self_set_loader`：hook 触发后把 `__loader__` 还原为真实 loader，不污染 import 系统。
- `wrapt.patches.patch_function_wrapper("module?", name)`：`?` 后缀即"延迟到模块首次导入时应用"，正好解决"引导阶段目标模块不在 sys.path"的问题。

（依据 wrapt 2.5.2 源码；此处只引函数名不引行号，以免依赖升级后失效。）

**结论**：底层机制完全借用 wrapt，funcpatch 只在其上做 owner 选择与生命周期管理。

## 决策 2：单一生效，不做优先级堆叠

**依据（gorilla 源码）：**

- `gorilla.Settings`：`allow_hit=False`（默认拒绝覆盖）、`store_hit=True`（保存原属性栈）。
- `gorilla.apply`：多层 patch 用栈保存原属性，支持堆叠。
- `wrapt.patches.wrapper_chain`：wrapper 链有环检测与深度上限（64）。

**结论**：虽然 wrapt/gorilla 都支持多层堆叠，但 funcpatch 的场景是"多选一"，堆叠会掩盖误部署（两个客户的包同时装上）。因此固定不变式：一个目标最多一个实现生效。冲突时告警，不静默选一个。

## 决策 3：回滚用 handle 身份，不用函数比对

**依据（wrapt 源码）：**

- `wrapt.patches.unwrap_object`：用安装时返回的 handle 对象做**身份匹配**（`is`），而非相等；因为代理对象会把 `__eq__` 委托给被包装对象。
- `wrapt.patches.resolve_path` 与 `resolve_owner`：安装用 resolve_path（可 shadow 继承属性），回滚用 resolve_owner（回到真正定义处，避免留下影子副本）。

**结论**：registry 保存安装返回的 handle 与 resolve_owner 位置，revert 时交给 wrapt 的 `unwrap_object`。

## 决策 4：版本校验是增量价值

**依据：** gorilla 与 wrapt 都没有"目标函数被改过就拒绝 patch"的机制（gorilla 的 `__hash__` 只用于 Patch 对象比较）。

**结论**：`PatchSpec.expect_hash` 由 funcpatch 引入。apply 前比对目标函数源码 hash，不符则拒绝并告警。这避免核心升级后补丁静默失效——这是 monkey patch 类方案最大的隐患。

## 决策 5：双发现机制

**依据：**

- `wrapt.importer.discover_post_import_hooks(group)`：entry point 发现。
- `gorilla.find_patches(modules)`：包扫描发现。

**结论**：开发期用目录扫描（`funcpatch/patches/`），生产用 entry point 组 `funcpatch.patches`。两者结果合并、按 `(owner, target, replacement)` 去重。

## 决策 6：不用字节码改写

**依据：**

- bytecode README 明确其定位是"generate and modify bytecode"，指令级操作。
- CPython opcode 在每个小版本变化，字节码改写需要按 Python 版本做测试矩阵。

**结论**：funcpatch 的场景是"大量改函数体"——用完整替代实现（正常 Python 源码）可维护；字节码改写适合"改一两条指令"的场景，不是本项目的目标。

## 决策 7：描述符保真、异步与并发安全

这些是裸 `setattr` 会出错、成熟 patch 框架必须处理的边界情况：

- **描述符保真**（`_descriptors.py`）：wrapt 的 `apply_patch` 只是裸 `setattr`。若用普通函数替换一个 `classmethod`，通过类访问时不会绑定 `cls`，语义改变。`preserve_descriptor` 按原属性类型（classmethod/staticmethod/property）包装 replacement，保持访问语义。回滚时 `resolve_owner` 恢复原始描述符对象。
- **异步函数**：`replace` 模式直接替换 async def 实现天然保持协程身份；`wrap` 模式由 wrapt 的 `FunctionWrapper` 适配。`enabled` 动态开关下 dispatcher 需按目标函数类型生成：`_enabled.py` 对 async / async generator 分别产出 `async def` 实现，保证 `inspect.iscoroutinefunction` / `isasyncgenfunction` 的判定不被破坏。
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

## 决策 8：不做行级改写

**问题**：改函数**内部**的某几行（如把 `if result is None` 改成别的判断），
当前模型只能把整个函数体复制到补丁包里，即"补丁 = 该函数的另一套完整实现"。

**评估过程**（实测结论，非推测）：

- **stdlib `ast` 改写**：可定位到函数体内的任意节点并替换。但 `ast.unparse`
  不是保真 round-trip —— 实测**行内注释全部丢失**、引号风格与格式被改写、
  空白被重排。docstring 能保留。对"主分支代码要保持可读"是真实代价。
- **LibCST 等保真解析器**：能保留注释与格式，但引入一个新的重依赖
  （且需支持 3.10–3.13 的语法演进），与"底层用 wrapt、不重造轮子"的定位不符。
- **字节码改写**：CPython opcode 在小版本间变化，需按版本做测试矩阵，复杂度最高。
- **运行时拦截（不改源码）**：可替换函数**内部引用的全局名**来改变行为，
  实测有效且零源码改动。但它只能改变被调用者的语义，无法表达"改某个判断条件"。

**结论**：不做。理由是能力与代价不匹配 —— 需要覆盖的场景用"复制函数体"能表达，
而表达不了的场景（改长函数内部的判断）恰好是复制成本最高、注释损失最痛的地方，
为此引入重依赖或格式破坏性改写不划算。

**替代路径**：把"改内部逻辑"重构为"改前后处理"（`mode="wrap"`），
或把被改的判断提取成独立函数后再用 `wrap` 替换该函数。
后者能表达"改判断"且完全不改源码。

若未来确有必须行级改写的场景，建议独立立项并优先评估 LibCST 路线，
而不是在 funcpatch 内引入第二套解析体系。

## 兼容性

- Python >= 3.10
- `tomllib`（3.11+）/ `tomli`（3.10，可选依赖）：配置文件层
- wrapt >= 2.5：底层替换与 post-import-hook（桥接层透传的 `with_doc` 自 2.5 引入）
