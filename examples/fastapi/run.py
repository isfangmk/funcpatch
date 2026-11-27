"""示例入口：通过 funcpatch 引导并运行 FastAPI 服务。

用法：
    pip install "funcpatch[web]"   # 或额外安装 fastapi + uvicorn
    python -m examples.fastapi.run

启动后访问 GET http://127.0.0.1:8000/headers 查看生效的请求头。
"""

from __future__ import annotations

from funcpatch import SelectionConfig, bootstrap

from .patch import patch


def main() -> None:
    # 显式构造配置，保证示例中 owner 的取值与生效判定一致。
    config = SelectionConfig(default_owner="client_a", target_owners={}, enabled=True)
    registry = bootstrap(config=config, specs=[patch])

    # 在引导之后导入服务：hook 会拦截首次导入并应用补丁。
    from .demo_module import app

    applied = registry.is_applied(patch.target)
    print(f"owner=client_a, patch applied={applied}")
    print("启动后访问 GET http://127.0.0.1:8000/headers 查看生效的请求头")

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
