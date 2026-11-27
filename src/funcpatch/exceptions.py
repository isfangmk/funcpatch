"""funcpatch 自定义异常类型。

让调用方能精确捕获不同失败原因，而不是裸 Exception
（借鉴 wrapt 的异常分层设计）。
"""

from __future__ import annotations


class FunCPatchError(Exception):
    """funcpatch 异常的基类。"""


class PathResolutionError(FunCPatchError):
    """目标模块或属性路径无法解析。"""


class TargetNotFoundError(FunCPatchError):
    """指定的 owner 未注册目标补丁。"""


class PatchRejectedError(FunCPatchError):
    """补丁被拒绝，例如版本校验（hash）失败。"""

    def __init__(self, target: str, reason: str) -> None:
        self.target = target
        self.reason = reason
        super().__init__(f"补丁被拒绝 {target}: {reason}")


class ConflictError(FunCPatchError):
    """检测到补丁冲突（同一目标多个 owner）。"""


class FunCPatchWarning(UserWarning):
    """funcpatch 非致命问题警告（借鉴 pluggy.PluggyWarning）。

    与异常不同，警告不中断部署，用于提示可容忍但值得关注的情况，
    例如目标函数签名与替代实现不一致。
    """


class DeprecatedTargetWarning(FunCPatchWarning):
    """补丁目标被标记为废弃时发出。"""
