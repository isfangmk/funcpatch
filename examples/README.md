# funcpatch 示例

按"从简单到完整"排列，每个目录都能独立运行。

| 目录 | 内容 | 运行方式 |
|---|---|---|
| [basic/](basic/) | 最小示例：一条 replace 补丁，应用→效果→回滚 | `python -m examples.basic.run` |
| [modes/](modes/) | 各能力模式演示：replace / wrap / async / 描述符 / property_part / add / 事务 / 作用域 / 抑制 / 校验 / 依赖 hash | `python -m examples.modes.walkthrough` |
| [packages/](packages/) | 作为独立 pip 包分发的补丁（entry point 发现） | 见下方说明 |
| [fastapi/](fastapi/) | FastAPI 端到端集成：服务代码零改动 | `python -m examples.fastapi.run` |

## 命名约定

同一目录下文件职责固定，便于对照阅读：

| 文件名 | 职责 |
|---|---|
| `demo_module.py` | 主分支代码（被补丁的目标）。示例中不修改它 |
| `patch.py` | 补丁定义：声明 owner、目标、替代实现 |
| `run.py` | 运行入口：引导 → 观察效果 → 回滚 |
| `walkthrough.py` | 多场景自检演示，逐个场景打印结果并断言 |

## basic：最小示例

演示一条补丁的完整生命周期：

```bash
python -m examples.basic.run
```

输出：

```
补丁前: {'X-Source': 'core', 'X-User': 'alice'}
补丁后: {'X-Source': 'client_a', 'X-Tenant': 'alpha', 'X-User': 'ALICE'}
回滚后: {'X-Source': 'core', 'X-User': 'alice'}
```

对应代码：`basic/demo_module.py`（主分支）、`basic/patch.py`（补丁）、`basic/run.py`（入口）。

## modes：能力演示

一次跑完全部模式，逐个场景打印结果并自检：

```bash
python -m examples.modes.walkthrough
```

覆盖场景：

| 场景 | 说明 |
|---|---|
| replace | 完整替换函数实现 |
| wrap | 包装原函数，复用核心逻辑 |
| async | 替换异步函数，保持协程身份 |
| descriptors | classmethod / staticmethod / property |
| property_part | 只替换 property 的 setter，getter 不动 |
| add | 添加主分支里原本不存在的方法 |
| transaction | 批量应用，任一失败自动回滚 |
| scoped / suppress | 作用域补丁与上下文旁路 |
| validate | 部署前只读校验 |
| dependency hash | 目标连同同模块依赖一起校验 |
| plan --diff | 发布前预览函数会被改成什么样 |

## packages：独立补丁包

演示补丁包作为独立 pip 包分发、通过 entry point 被 funcpatch 发现：

```bash
cd examples/packages/client_a
pip install .
```

`client_a` 与 `client_b` 改同一个目标函数，演示两种 entry point 写法（补丁列表 / 返回列表的函数）。
两个包同时安装时，用环境变量决定谁生效：

```bash
export FUNC_PATCH_OWNER=client_a   # 或 client_b
```

## fastapi：端到端集成

演示"主分支零改动"：FastAPI 服务代码里没有一行提到 funcpatch，定制方只替换
`build_headers` 的内部逻辑。

```bash
pip install "funcpatch[web] @ git+https://github.com/isfangmk/funcpatch.git"
python -m examples.fastapi.run
```

启动后访问 <http://127.0.0.1:8000/headers?user=alice> 查看生效的请求头。

对应的端到端测试在 `tests/test_fastapi_integration.py`（需 fastapi 与 httpx）。
