# 能力差距分析（基于 wrapt 2.6 / gorilla 0.5 源码通读）

核心原则：**wrapt 已成熟实现的能力不重造，funcpatch 只暴露；
funcpatch 自研部分严格限定在 wrapt/gorilla 都不提供的 owner 治理层。**

## 能力矩阵

| 能力 | wrapt | gorilla | funcpatch | 正确决策 |
|---|---|---|---|---|
| **wrapt 已提供 → 应透传，不重造** | | | | |
| 透明代理（100+ 特殊方法转发） | ✅ | ❌ | 借用 wrapt | 已通过 wrapt 获得 |
| 签名保留（__signature__/annotations） | ✅ with_signature/FunctionWrapper | ❌ | 自动获得 | 已具备，补测试与文档 |
| enabled 动态开关 | ✅ FunctionWrapper(enabled=) | ❌ | ❌ 未透传 | **透传 PatchSpec.enabled** |
| __wrapped__ 链 / find_wrapper / is_wrapped_by | ✅ | ❌ | ❌ 未暴露 | **暴露诊断 API** |
| 临时补丁 transient | ✅ transient_function_wrapper | ❌ | ❌ | **透传为 scoped API** |
| 作用域补丁 scoped | ✅ scoped_function_wrapper | ❌ | ❌ | **透传为 scoped API** |
| post-import-hook / 延迟加载 / entry point | ✅ | ❌ | ✅ 借用 | 已覆盖 |
| resolve_path / resolve_owner / unwrap_object | ✅ | ❌ | ✅ 借用 | 已覆盖 |
| 描述符检测（classmethod/staticmethod） | ✅ __init__ 内建 | ❌ | ✅ preserve_descriptor | 已覆盖 |
| 环检测 / 链深度上限 | ✅ wrapper_chain | ❌ | N/A | 单一生效，无链 |
| **gorilla 已提供 → 选择性借鉴** | | | | |
| 装饰式声明 @patch / @patches | ❌ | ✅ | ❌ 数据式 | **补装饰式 API（便利层）** |
| 成员过滤 filter | ❌ | ✅ | ❌ | **补 filter 到 discovery** |
| find_patches 递归扫描 | ❌ | ✅ | ⚠️ 子模块已支持 | 补递归 |
| **funcpatch 自研（wrapt/gorilla 都没有）** | | | | |
| owner 单一生效不变式 | ❌ | ❌ | ✅ | 已覆盖（核心价值） |
| 三层 owner 选择（toml/env） | ❌ | ❌ | ✅ | 已覆盖 |
| 版本校验 expect_hash | ❌ | ❌ | ✅ | 已覆盖 |
| 冲突检测 + 审计 | ❌ | ❌ | ✅ | 已覆盖 |
| **有意不做（不变式决定）** | | | | |
| 多层补丁链 splice | ✅ | ✅ 栈式 | ❌ | 单一生效，明确不做 |
| store_hit 栈 | ❌ | ✅ | ❌ | 只存一层 original |

## 透传 vs 重造：为什么这个区分重要

wrapt 的 FunctionWrapper 构造时做了大量精细工作（见 wrappers.py:1169 起 70 行注释）：
Python 3 没有 unbound method，判断被包装对象是实例方法/类方法/静态方法无法 fool-proof，
wrapt 通过检查原始类型、`__qualname__`、绑定状态等综合判断，并接受"极少数情况可能判断错"。
这种经过千锤百炼的逻辑，funcpatch 自己写必然出错。

同理，签名保留、`enabled` 求值时机（绑定 vs 调用）、代理的 100+ 特殊方法转发——
这些都是 wrapt 的核心价值，funcpatch 的职责是**让用户在 PatchSpec 里声明，然后透传给 wrapt**。

## 实际要补的（按优先级）

### P0 — 透传 wrapt 已有能力
1. `PatchSpec.enabled: bool | Callable[[], bool]` → 透传给 FunctionWrapper(enabled=)。
   replace 模式用轻量壳实现同等语义。
2. 诊断 API：`is_patched(target)` / `get_wrapper(target)` / `unwrap(target)`，
   内部用 wrapt 的 find_wrapper / is_wrapped_by / unwrap_object。
3. `scoped_patch(spec)` context manager + `transient_patch(spec)` 装饰器，
   内部用 wrapt 的 scoped_function_wrapper / transient_function_wrapper。

### P1 — 便利层
4. 装饰式声明 `@patch(owner, module, attr)`，内部构造 PatchSpec（gorilla 风格）。
5. discovery 的 `filter` 回调 + 递归扫描增强。

### P2 — 验证与文档
6. 补测试：签名保留、enabled 动态、scoped/transient、诊断 API。
7. 文档明确：哪些能力来自 wrapt（透传），哪些是 funcpatch 自研。

## 不做（明确记录）
- 多层补丁链 splice / store_hit 栈：违反单一生效不变式。
- 自己实现对象代理：wrapt 已有 100+ 特殊方法转发，重造必然出错。
