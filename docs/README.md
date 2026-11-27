# funcpatch 文档

| 文档 | 内容 |
|---|---|
| [USAGE.md](USAGE.md) | 使用指南：三种接入方式、owner 选择、各模式用法 |
| [API.md](API.md) | 完整 API 参考：全部公开名称、签名与语义 |
| [COMPARISON.md](COMPARISON.md) | 与 wrapt / gorilla / pluggy 的逐项功能对比与采纳决策 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发指南：环境、编码约定、测试与文档要求 |
| [RELEASING.md](RELEASING.md) | 发布检查清单 |

架构决策与源码依据见根目录 [ARCHITECTURE.md](../ARCHITECTURE.md)，
版本记录见 [CHANGELOG.md](../CHANGELOG.md)，
可运行示例见 [examples/](../examples/)。

## 阅读顺序建议

- **第一次接触**：根目录 `README.md` → `docs/USAGE.md` → `examples/basic/`
- **要接入自己的项目**：`docs/USAGE.md` → `docs/API.md`
- **想了解为什么这样设计**：`ARCHITECTURE.md` → `docs/COMPARISON.md`
- **发布前**：`docs/RELEASING.md`
