"""供测试用的目标模块（模拟主分支代码）。

每个测试通过 conftest 的 autouse fixture 恢复状态，避免相互污染。
"""

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


def _dep_prefix() -> str:
    """依赖 hash 测试用的模块级 helper。"""
    return "dep"


def with_dependency(name: str) -> str:
    """调用同模块 helper，用于验证依赖闭包 hash。"""
    return f"{_dep_prefix()}-{name}"


async def async_greet(name: str) -> str:
    return f"async hello {name}"


async def async_numbers(count: int):
    """异步生成器，用于验证 isasyncgenfunction 身份保持。"""
    for i in range(count):
        yield i


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


class Mutable:
    """带 setter/deleter 的 property，用于验证 property_part。"""

    def __init__(self) -> None:
        self._value = "original"

    @property
    def value(self) -> str:
        return self._value

    @value.setter
    def value(self, new: str) -> None:
        self._value = new

    @value.deleter
    def value(self) -> None:
        self._value = "<deleted>"


def raising_target() -> str:
    """用于测试 strict 模式拒绝。"""
    return "never-patched"
