# funcpatch

**在不修改任何源码的前提下，用插件完整替换函数实现。一个目标函数，一次部署，只有一个 owner 生效。**

funcpatch 面向这样的场景：同一套核心代码要交付给多个客户，每个客户都要**大量修改某些函数的内部逻辑**。你不想改主分支、不想为每个客户 fork、也不想让多个客户的补丁互相污染。funcpatch 让每个客户作为独立补丁包存在，部署时明确指定哪个 owner 生效。

---

## 核心特性

1. **主分支零改动**：不修改目标源码，补丁在模块导入时动态应用。
2. **单一生效不变式**：一个 `(module, attr)` 在整个进程内最多一个 owner 的实现生效，
   不堆叠、不按优先级叠加；由进程级占用表保证，跨 Registry 实例同样成立。
3. **部署层决策**：哪个 owner 生效是部署配置（toml / 环境变量），不写死在代码里。
4. **失败安全**：未指定 owner、版本校验失败时，应用原实现，不猜测。
5. **可观测**：每次应用都明确记录生效者、冲突者与拒绝原因。
6. **完整函数类型支持**：普通函数、async 函数、classmethod / staticmethod / property 描述符。
7. **并发安全**：apply / revert 用 RLock 保护，多线程调用幂等。
8. **透传 wrapt 能力**：透明代理、签名适配（`with_signature`）、enabled 动态开关、作用域/临时补丁、诊断 API，不重造轮子。
9. **双声明方式**：数据式 `PatchSpec` 与装饰式 `@patch(...)` / `@patches(...)`。
10. **部署前校验**：`validate()` / `Registry.plan()` 只读预演，CI 可提前发现配置错误。
11. **批量事务**：`apply_all()` / `transaction()` 在部分失败时自动回滚，不留半成品。
12. **严格模式可选**：`strict=True` 时抛领域异常，默认保持 fail-safe。
13. **wrapt 全量透传**：50 个成熟工具（代理、装饰器、调用约定桥接、链诊断、导入钩子）
    从 `funcpatch` 顶层直接可用，不重造轮子。
14. **成熟项目模式借鉴**：gorilla 的描述符安全自省与批量生成、pluggy 的 owner 阻塞 /
    事件监听 / 签名校验。
15. **依赖闭包校验**：`expect_deps_hash` 覆盖目标调用的同模块 helper，主分支改了 helper
    也会拒绝应用，避免补丁静默跑在旧假设上。
16. **可添加新成员**：`mode="add"` 给目标类添加原本不存在的方法/属性，回滚时删除。

---

## 架构

```
解释器启动
  → .pth / 显式 bootstrap
      → 读取配置（funcpatch.toml + FUNC_PATCH_OWNER）
      → 发现补丁（目录扫描 + entry point 双支持）
      → 为每个目标注册 wrapt post-import-hook（字符串延迟，不提前 import 目标模块）
  → 目标模块首次被 import
      → hook 触发
      → 按三层规则选择唯一 owner
      → 版本校验（expect_hash / expect_deps_hash）
      → 替换函数实现（replace / wrap / add），记录 handle 供回滚
      → 审计日志
```

### 组件

**对外能力实现**

| 模块 | 职责 |
|---|---|
| `spec.py` | `PatchSpec` 补丁数据对象、源码 hash、依赖闭包 hash |
| `config.py` | 三层选择规则（toml targets > toml default > env） |
| `discovery.py` | 双发现：目录扫描 + entry point |
| `registry.py` | 注册表：select → apply → revert → audit → validate/plan/transaction |
| `loader.py` | wrapt post-import-hook 桥接、幂等 bootstrap / shutdown |
| `audit.py` | 冲突、版本、生效日志（增量、可导出 JSON） |
| `validation.py` | 部署前只读校验、签名兼容性检查 |
| `decorators.py` | 装饰式声明 `@patch` / `@patches` |
| `introspection.py` | 描述符安全自省：`get_attribute` / `get_base` / `get_members` |
| `generation.py` | 批量生成补丁：`create_patches` / `find_patches` |
| `bridge.py` | wrapt 能力透传（50 个名称） |
| `exceptions.py` | 领域异常与警告类型 |

**内部支撑**

| 模块 | 职责 |
|---|---|
| `_claims.py` | 进程级目标占用表（单一生效不变式的实现） |
| `_descriptors.py` | 描述符保真（classmethod / staticmethod / property get/set/delete） |
| `_diagnostics.py` | 诊断：标记感知、`get_wrapper` / `unwrap_target` |
| `_enabled.py` | `enabled` 动态开关语义（含 async / async generator 身份保持） |
| `_scoped.py` | 作用域补丁与临时补丁（`scoped_patch` / `transient_patch`） |
| `_suppression.py` | 上下文局部抑制（`suppress_patches`） |
| `_requirements.py` | 部署包版本约束校验（PEP 508 风格） |
| `_diff.py` | 补丁预览：unified diff 生成 |
| `_version_check.py` | wrapt 版本守卫 |

底层依赖 [wrapt](https://github.com/GrahamDumpleton/wrapt)，复用其成熟的 post-import-hook、延迟加载与回滚机制；不重复造轮子。

### 生效选择规则（三层，全部实现）

```
1. funcpatch.toml [targets] 精确匹配目标   → owner
2. funcpatch.toml [default]               → owner
3. 环境变量 FUNC_PATCH_OWNER               → owner
4. 未命中                                  → 不应用（走原始实现）
```

同一目标若有多个 owner 注册补丁，只应用选中者，其余记冲突告警。

---

## 快速开始

从 GitHub 安装（尚未发布到 PyPI）：

```bash
pip install "funcpatch @ git+https://github.com/isfangmk/funcpatch.git"
```

或在仓库内开发安装：

```bash
pip install -e ".[dev]"
```

定义一个补丁：

```python
# mypatches.py
from funcpatch import PatchSpec, dependency_hash, get_base, source_hash

from app.core.config import Settings


def my_build_headers(self, cookie=None):
    # 完整的替代实现（函数体由你拥有）
    ...


# get_base 描述符安全：普通方法、classmethod、staticmethod 都能取到底层函数。
# 直接写 Settings.build_headers 对 classmethod 会取到绑定方法，取不到源码。
_target = get_base(Settings.build_headers)

patch = PatchSpec(
    owner="client_a",
    target_module="app.core.config",
    target_attr="Settings.build_headers",
    replacement=my_build_headers,
    # 可选：主分支函数被改过则拒绝应用。用 source_hash 取当前实现的 16 位 hash。
    expect_hash=source_hash(_target),
    # 可选：连同被调用的同模块 helper 一起校验，主分支改 helper 也拒绝应用。
    expect_deps_hash=dependency_hash(_target),
)

# 添加主分支里原本不存在的方法
extra = PatchSpec(
    owner="client_a",
    target_module="app.core.config",
    target_attr="Settings.client_only_helper",
    replacement=lambda self, x: f"client-{x}",
    mode="add",
)
```

批量查看/刷新 hash：

```bash
funcpatch hash --package mypatches
```

部署选择：

```bash
export FUNC_PATCH_OWNER=client_a
```

或 `funcpatch.toml`（支持一个部署内不同函数用不同 owner）：

```toml
[funcpatch.default]
owner = "client_a"

[funcpatch.targets]
# 点号与冒号两种写法都支持
"app.core.config.Settings.build_headers" = "client_b"
```

全局关闭补丁（不修改任何代码）：

```bash
export FUNC_PATCH_ENABLED=false
```

部署前只读校验（可在 CI 中运行，不应用补丁）：

```python
from funcpatch import discover_all, validate
from funcpatch.config import load_config

specs = discover_all()
# 传入 config 才会检查 owner 命中：部署配置了 owner 却没有任何补丁命中时，
# 这里会报出 owner mismatch，而不是等到运行时才发现一条补丁都没生效。
results = validate(specs, config=load_config())
assert all(r.ok for r in results), [r.to_dict() for r in results if not r.ok]
```

`validate()` 会导入目标模块以核对源码 hash，因此适合部署前校验；进程启动时单独调用 `bootstrap()` 应用补丁。

```python
from funcpatch import bootstrap

bootstrap()
```

CLI 部署诊断（只读）：

```bash
funcpatch plan                # 预演补丁，检查目标/hash/owner 是否可应用
funcpatch plan --diff         # 同上，并展示每个函数替换前后的源码差异
funcpatch claims              # 查看当前进程的目标占用
funcpatch validate            # 校验所有补丁 spec（含 owner 命中检查）
funcpatch hash                # 批量计算目标源码/依赖 hash，供刷新 expect_hash
```

`plan --diff` 输出示例：

```
=== app.core.config:Settings.build_headers ===
owner=client_a  会应用
--- a/app.core.config:Settings.build_headers
+++ b/app.core.config:Settings.build_headers
@@ -1,3 +1,7 @@
 def build_headers(self, cookie=None):
-    return {"X-Source": "core"}
+    return {
+        "X-Source": "client_a",
+        "X-Tenant": "alpha",
+    }
```

diff 只对 `replace` 模式生成（`wrap` 是运行时拦截而非替换函数体）；实现写成 lambda
或源码不可取时不生成。

---

## 文档

- [docs/](docs/)：完整文档
  - [USAGE.md](docs/USAGE.md)：使用指南
  - [API.md](docs/API.md)：完整 API 参考
  - [COMPARISON.md](docs/COMPARISON.md)：与 wrapt / gorilla / pluggy 的逐项功能对比
  - [CONTRIBUTING.md](docs/CONTRIBUTING.md)：开发指南
  - [RELEASING.md](docs/RELEASING.md)：发布检查清单
- [ARCHITECTURE.md](ARCHITECTURE.md)：架构决策与源码依据
- [examples/](examples/)：可运行示例
  - [basic/](examples/basic/)：最小示例（应用→效果→回滚）
  - [modes/](examples/modes/)：各能力模式演示（replace / wrap / async / 描述符 / add / 事务 / 作用域 / 校验 / 依赖 hash / diff 预览）
  - [packages/](examples/packages/)：作为独立 pip 包分发的补丁（entry point 发现）
  - [fastapi/](examples/fastapi/)：FastAPI 端到端集成，服务代码零改动
- [CHANGELOG.md](CHANGELOG.md)：版本记录

## 许可证

BSD-3-Clause
