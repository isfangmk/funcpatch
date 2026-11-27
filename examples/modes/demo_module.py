"""示例的主分支代码：被补丁的目标模块，示例中不修改它。

这里的函数代表真实项目中的核心实现。定制方通过 funcpatch 替换其中某个函数的
内部逻辑，而本文件一行都不用改。
"""

from __future__ import annotations


def greet(name: str) -> str:
    """普通函数：演示 replace / wrap 模式。"""
    return f"hello {name}"


async def async_greet(name: str) -> str:
    """异步函数：演示异步替换与协程身份保持。"""
    return f"async hello {name}"


class Settings:
    """演示 classmethod / staticmethod / property 的替换。"""

    def __init__(self) -> None:
        self._theme = "default"

    @property
    def theme(self) -> str:
        """演示 property 的 getter 替换与 property_part 局部替换。"""
        return self._theme

    @theme.setter
    def theme(self, value: str) -> None:
        self._theme = value

    @classmethod
    def who(cls) -> str:
        """演示 classmethod 的替换。"""
        return f"core-{cls.__name__}"

    @staticmethod
    def static() -> str:
        """演示 staticmethod 的替换。"""
        return "core-static"
