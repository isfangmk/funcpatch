"""示例的主分支代码：一个 FastAPI 服务，定制方不修改它一行。

这个模块代表核心业务代码。它不知道 funcpatch 的存在；
定制方通过 funcpatch 替换 build_headers 的内部逻辑，无需改这里一行。
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="funcpatch integration demo")


def build_headers(user: str) -> dict[str, str]:
    """核心函数：被定制方替换的目标。"""
    return {"X-Source": "core", "X-User": user}


@app.get("/headers")
def get_headers(user: str = "anonymous") -> dict[str, str]:
    """端点直接调用核心函数，不感知补丁。"""
    return build_headers(user)
