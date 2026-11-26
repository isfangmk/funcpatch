# funcpatch

**在不修改任何源码的前提下，用插件完整替换函数实现。一个目标函数，一次部署，只有一个 owner 生效。**

funcpatch 面向这样的场景：同一套核心代码要交付给多个客户，每个客户都要**大量修改某些函数的内部逻辑**。你不想改主分支、不想为每个客户 fork、也不想让多个客户的补丁互相污染。funcpatch 让每个客户作为独立补丁包存在，部署时明确指定哪个 owner 生效。

---

## 设计原则

1. **主分支零改动**：不修改目标源码，补丁在模块导入时动态应用。
2. **单一生效不变式**：一个 `(module, attr)` 最多一个 owner 的实现生效，不堆叠、不按优先级叠加。
3. **部署层决策**：哪个 owner 生效是部署配置（toml / 环境变量），不写死在代码里。
4. **失败安全**：未指定 owner、版本校验失败时，应用原实现，不猜测。
5. **可观测**：每次应用都明确记录生效者、冲突者与拒绝原因。
6. **完整函数类型支持**：普通函数、async 函数、classmethod / staticmethod / property 描述符。
7. **并发安全**：apply / revert 用 RLock 保护，多线程调用幂等。
8. **透传 wrapt 能力**：签名保留、enabled 动态开关、作用域/临时补丁、诊断 API，不重造轮子。
9. **双声明方式**：数据式 `PatchSpec` 与装饰式 `@patch(...)`。

能力边界与 wrapt / gorilla 的逐项对比见 [docs/GAP_ANALYSIS.md](docs/GAP_ANALYSIS.md)。

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
      → 版本校验（expect_hash）
      → 替换函数实现，记录 handle 供回滚
      → 审计日志
```

### 组件

| 模块 | 职责 |
|---|---|
| `spec.py` | `PatchSpec` 补丁数据对象 + 源码 hash |
| `config.py` | 三层选择规则（toml targets > toml default > env） |
| `discovery.py` | 双发现：目录扫描 + entry point |
| `registry.py` | 注册表：select → apply → revert → audit |
| `loader.py` | wrapt post-import-hook 桥接 |
| `audit.py` | 冲突、版本、生效日志 |

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

```bash
pip install funcpatch
```

定义一个补丁：

```python
# mypatches.py
from funcpatch import PatchSpec


def my_build_headers(self, cookie=None):
    # 完整的替代实现（函数体由你拥有）
    ...


patch = PatchSpec(
    owner="client_a",
    target_module="app.core.config",
    target_attr="Settings.build_headers",
    replacement=my_build_headers,
    expect_hash="a1b2c3d4e5f6",  # 可选：主分支函数被改过则拒绝应用
)
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
"app.core.config.Settings.build_headers" = "client_b"
```

---

## 文档

- [ARCHITECTURE.md](ARCHITECTURE.md)：架构决策与源码依据
- [examples/](examples/)：补丁示例
- [docs/](docs/)：使用指南

## 许可证

BSD-3-Clause
