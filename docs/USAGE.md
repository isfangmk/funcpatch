# 使用指南

## 安装

```bash
pip install funcpatch
```

## 三种使用方式

### 方式 1：目录扫描（开发期最简单）

在 `funcpatch/patches/` 目录（或任意包）下放补丁模块，模块里定义 `PatchSpec` 实例：

```python
# mypatches.py
from funcpatch import PatchSpec


def my_impl(self, cookie=None):
    return {"X-Tenant": "client-a"}


patch = PatchSpec(
    owner="client_a",
    target_module="app.core.config",
    target_attr="Settings.build_headers",
    replacement=my_impl,
)
```

引导（进程启动早期调用）：

```python
from funcpatch import bootstrap

bootstrap()  # 自动发现 + 注册延迟 hook
```

### 方式 2：entry point（生产分发）

每个 owner 做成独立 pip 包：

```toml
# client-a-plugin/pyproject.toml
[project.entry-points."funcpatch.patches"]
client_a = "client_a_patch:patches"
```

`patches` 可以是：单个 `PatchSpec`、`PatchSpec` 列表、或返回它们的函数。

### 方式 3：代码显式注册

```python
from funcpatch import PatchSpec, bootstrap

bootstrap(
    specs=[
        PatchSpec(owner="client_a", target_module="...", target_attr="...", replacement=fn),
    ]
)
```

## 选择 owner

### 环境变量（全局默认）

```bash
export FUNC_PATCH_OWNER=client_a
```

### 配置文件（细粒度，一个部署混合多个 owner）

`funcpatch.toml`：

```toml
[funcpatch.default]
owner = "client_a"

[funcpatch.targets]
"app.core.config.Settings.build_headers" = "client_b"
"app.services.work.run_work_task" = "client_a"
```

选择优先级：`[targets]` 精确匹配 > `[default]` > `FUNC_PATCH_OWNER` > 不应用。

## 版本校验

`expect_hash` 是目标函数的源码 hash。核心函数被改过后 hash 变化，补丁会被**拒绝并告警**，而不是静默产生错误行为。

```python
from funcpatch import source_hash
from app.core.config import Settings

print(source_hash(Settings.build_headers))  # 填入 expect_hash
```

## 两种替换模式

- `mode="replace"`（默认）：完全替换函数实现，函数体由补丁拥有。适合大量修改。
- `mode="wrap"`：包一层，可调用原函数（wrapt.FunctionWrapper 语义）。

```python
def wrapper(original, instance, args, kwargs):
    result = original(*args, **kwargs)
    ...
    return result


PatchSpec(..., replacement=wrapper, mode="wrap")
```

两种模式都保留原函数签名（`inspect.signature` 返回原签名）。

## enabled 动态开关

`enabled` 为 `False` 时调用原函数；为 callable 时每次调用时求值（透传 wrapt）：

```python
PatchSpec(..., enabled=lambda: feature_flag_is_on())
```

## 作用域与临时补丁

不经过 Registry，仅在特定范围生效并自动回滚：

```python
from funcpatch import scoped_patch, transient_patch

with scoped_patch("app.core.config", "Settings.build_headers", spec):
    ...  # with 块内生效，退出自动回滚


@transient_patch("app.core.config", "Settings.build_headers", spec)
def do_something(): ...  # 仅该函数执行期间生效
```

## 装饰式声明

除数据式 `PatchSpec` 外，也支持装饰式声明：

```python
from funcpatch import patch


@patch("client_a", "app.core.config", "Settings.build_headers")
def my_impl(self, cookie=None): ...
```

装饰只收集补丁，应用仍由 `bootstrap()` / Registry 完成。可用 `filter_fn` 在发现时过滤。

## 诊断

```python
from funcpatch import is_patched, get_applied_info

is_patched("app.core.config:Settings.build_headers")  # 是否被打补丁
get_applied_info("app.core.config:Settings.build_headers")  # {'owner': ..., 'target': ...}
```

## 特殊函数类型

### 异步函数

`replace` 模式直接替换 async def 实现即可，替换后仍是 coroutine function。
`wrap` 模式的 wrapper 需要 `await original(...)`：

```python
async def wrapper(original, instance, args, kwargs):
    result = await original(*args, **kwargs)
    return result
```

### 描述符（classmethod / staticmethod / property）

funcpatch 会按原属性的描述符类型自动包装 replacement，保持访问语义：

- 替换 `classmethod` 时，实现函数签名带 `cls`
- 替换 `staticmethod` 时，实现函数签名不带 self/cls
- 替换 `property` 时，实现函数带 `self`（替换 getter）

```python
def impl(cls):
    return f"patched-{cls.__name__}"


PatchSpec(..., target_attr="Settings.build_headers", replacement=impl)
```

## 并发安全

`Registry.apply()` / `revert()` 内部用 `RLock` 保护，可被多个线程安全调用，
重复 apply 同一目标只会应用一次（幂等）。

## 回滚与查询

```python
from funcpatch import get_registry

reg = get_registry()
reg.get_original("app.core.config:Settings.build_headers")  # 原始函数
reg.is_applied("app.core.config:Settings.build_headers")
reg.revert("app.core.config:Settings.build_headers")
reg.revert_all()
```

## 审计

补丁生效、冲突、版本拒绝都会通过 `funcpatch.audit` 打日志。可在应用启动时配置日志级别查看。

## 与 .pth 自启动结合

如果项目用 `.pth` 在解释器启动时引导：

```python
# 某个 .pth 文件
/path/to/funcpatch/src
import funcpatch; funcpatch.bootstrap()
```

`bootstrap()` 只注册 wrapt post-import-hook，**不 import 目标模块**，因此不依赖 sys.path 是否完整。目标模块首次被 import 时补丁才应用。
