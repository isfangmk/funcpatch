"""供测试用的目标模块（模拟主分支代码）。"""

from __future__ import annotations


def build_headers(cookie: str | None = None) -> dict[str, str]:
    """一个典型的待补丁函数。"""
    headers = {"Content-Type": "application/json", "X-Source": "original"}
    if cookie:
        headers["cookie"] = cookie
    return headers


class Settings:
    def build_headers(self, cookie: str | None = None) -> dict[str, str]:
        headers = {"X-Source": "original-method"}
        if cookie:
            headers["cookie"] = cookie
        return headers


def greet(name: str) -> str:
    return f"hello {name}"


async def async_greet(name: str) -> str:
    return f"async hello {name}"


class Descriptors:
    @classmethod
    def who(cls) -> str:
        return f"class-{cls.__name__}"

    @staticmethod
    def static() -> str:
        return "static-original"

    @property
    def prop(self) -> str:
        return "prop-original"
