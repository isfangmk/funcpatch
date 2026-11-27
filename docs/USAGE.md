# 使用指南

## 安装

```bash
pip install "funcpatch @ git+https://github.com/isfangmk/funcpatch.git"
```

尚未发布到 PyPI；开发时可加 `--editable` 并装上可选依赖：

```bash
pip install -e ".[dev,toml,web]"
```

- `toml`：Python 3.10 需要 `tomli`（3.11+ 用内置 `tomllib`，无需此 extra）
- `web`：FastAPI 集成示例与测试需要 `fastapi` / `httpx` / `uvicorn`

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
client_a = "patch:patches"
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
`[targets]` 的键支持点号（`app.mod.f`）与冒号（`app.mod:f`）两种写法，
内部统一比较，因此文档示例中的点号写法可直接生效。

### 全局开关

```bash
export FUNC_PATCH_ENABLED=false  # 不应用任何补丁；缺省为开启
```

关闭时注册表拒绝所有 apply（审计记录 reason=`disabled`），loader 不注册加载钩子。

## 版本校验

`expect_hash` 是目标函数的源码 hash。核心函数被改过后 hash 变化，补丁会被**拒绝并告警**，而不是静默产生错误行为。

```python
from funcpatch import get_base, source_hash
from app.core.config import Settings

# get_base 描述符安全：普通方法、classmethod、staticmethod 都能取到底层函数。
# 直接写 Settings.build_headers 时，若它是 classmethod 会取到绑定方法，取不到源码。
print(source_hash(get_base(Settings.build_headers)))  # 填入 expect_hash
```

`expect_deps_hash` 进一步覆盖目标调用的**同模块依赖**（通过全局名引用、定义在同一模块的
函数/类）。主分支改了被调用的 helper 时，仅靠 `expect_hash` 发现不了，补丁会静默跑在旧假设上：

```python
from funcpatch import dependency_hash, get_base

expect_deps_hash = dependency_hash(get_base(Settings.build_headers))
```

批量查看当前值：

```bash
funcpatch hash --package mypatches
```

`funcpatch hash` 给出的是**主分支原实现**的 hash：即使目标此刻已被某个补丁接管，
采集到的仍是原实现的值，可以直接填进 `expect_hash`。

## 三种替换模式

- `mode="replace"`（默认）：完全替换函数实现，函数体由补丁拥有。适合大量修改。
- `mode="wrap"`：包一层，可调用原函数（wrapt.FunctionWrapper 语义）。
- `mode="add"`：给目标类添加主分支里**原本不存在**的方法或属性。目标属性必须原本不存在
  （存在则拒绝，避免覆盖主分支实现），回滚时删除该属性。与其它模式一样受
  `requires`、`enabled`、`deprecated` 约束。

```python
def wrapper(original, instance, args, kwargs):
    result = original(*args, **kwargs)
    ...
    return result


PatchSpec(..., replacement=wrapper, mode="wrap")

PatchSpec(
    ...,
    target_attr="Settings.client_only_helper",
    replacement=lambda self, x: f"client-{x}",
    mode="add",
)
```

由于包装器会反映替代实现的签名，`inspect.signature` 返回的是替代函数的签名。
若需要保留原函数签名，可用 `with_signature(prototype=原函数)` 装饰替代实现。

## enabled 动态开关

`enabled` 为 `False` 时调用原函数；为 callable 时每次调用时求值（透传 wrapt）：

```python
PatchSpec(..., enabled=lambda: feature_flag_is_on())
```

## 作用域与临时补丁

不写入 Registry 的持久状态，仅在特定范围生效并自动回滚：

```python
from funcpatch import scoped_patch, transient_patch

with scoped_patch("app.core.config", "Settings.build_headers", spec):
    ...  # with 块内生效，退出自动回滚


@transient_patch("app.core.config", "Settings.build_headers", spec)
def do_something(): ...  # 仅该函数执行期间生效
```

它们同样校验 `expect_hash` 并检查进程占用，只是占用只在作用域/调用期间持有，
退出即释放；可用于测试隔离而不必 `bootstrap()`。

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
from funcpatch import is_patched, get_applied_info, get_wrapper

is_patched("app.core.config:Settings.build_headers")  # 是否被打补丁
get_applied_info("app.core.config:Settings.build_headers")
# {'owner': 'client_a', 'target': 'app.core.config:Settings.build_headers', 'targets': [...]}
```

`targets` 列出共用同一 replacement 的全部目标；`target` 是本次查询的目标。

`get_wrapper()` 返回当前生效的包装器/替代函数。另有 `unwrap_target()` 可拆掉包装链，
但它**有副作用**（补丁标记随之消失），仅在确实要拆包装时使用。

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

property 可以只替换其中一部分，其余保持原样：

```python
PatchSpec(..., target_attr="Mutable.value", replacement=new_setter, property_part="set")
PatchSpec(..., target_attr="Mutable.value", replacement=new_deleter, property_part="delete")
```

## 并发安全

`Registry.apply()` / `revert()` 内部用 `RLock` 保护，可被多个线程安全调用，
重复 apply 同一目标只会应用一次（幂等）。

"单一生效"由进程级占用表保证：即使创建多个 `Registry` 实例，同一目标也只能被
一个实例占用，后 apply 的会被拒绝并记冲突；回滚后占用释放，可重新接管。
用 `claims_snapshot()` 可查看当前每个目标被哪个 owner 占用。

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
`AuditReport` 支持 `to_dict()` 导出结构化数据、`clear()` 清空，日志只打印自上次调用以来的增量，
避免目标模块逐个导入时重复刷屏。

## 部署前校验与严格模式

`validate()` 只读检查目标可解析、hash 匹配、owner 命中，不修改任何状态，适合放在 CI：

```python
from funcpatch import validate, discover_all
from funcpatch.config import load_config

# 传入 config 才会检查 owner 命中：部署配置了 owner 却没有任何补丁命中时，
# 这里报出 owner mismatch，与 plan() 的结论一致。
results = validate(discover_all(), config=load_config())
failed = [r.to_dict() for r in results if not r.ok]
assert not failed, failed
```

命令行等价物会按配置读取 owner：

```bash
funcpatch validate --config funcpatch.toml
```

`Registry.plan()` 返回每个目标"将会做什么"的列表（selected / skipped / would_apply / reason）。
`plan(include_diff=True)` 还会为 `replace` 模式的补丁生成 unified diff，展示目标实现与
替代实现的源码差异，便于发布前确认"这个函数会被改成什么样"。

```bash
funcpatch plan --diff
```

默认是 fail-safe（失败返回 `False` 并记录）；需要部署期 fail-fast 时用 `strict=True`，
拒绝点会抛 `PatchRejectedError` / `PathResolutionError` / `TargetNotFoundError`。

## 批量事务

```python
from funcpatch import get_registry

reg = get_registry()
result = reg.apply_all(["mod:fn1", "mod:fn2"])
if not result.ok:
    print(result.failed, result.rolled_back)  # 本次已成功项全部回滚

with reg.transaction():
    reg.apply("mod:fn1")
    # 块内抛异常时自动回滚
```

## 生命周期

```python
from funcpatch import bootstrap, shutdown

bootstrap()  # 幂等，重复调用返回已有 Registry
shutdown()  # 回滚全部 + 清空全局状态
```

## 与 .pth 自启动结合

如果项目用 `.pth` 在解释器启动时引导：

```text
# 某个 .pth 文件
/path/to/funcpatch/src
import funcpatch; funcpatch.bootstrap()
```

`bootstrap()` 只注册 wrapt post-import-hook，**不 import 目标模块**，因此不依赖 sys.path 是否完整。目标模块首次被 import 时补丁才应用。
