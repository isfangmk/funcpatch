"""目标解析：取出"主分支原实现"，避免被已生效的补丁污染。

问题：补丁生效后，目标位置上的对象已被替换成替代实现。此时直接对目标取
源码 hash，得到的是**替代实现**的 hash，而不是主分支原实现的 hash：

  * 版本校验会误报 "hash mismatch"，而原实现其实没变过；
  * `funcpatch hash` 采集到的是替代实现的 hash，填进 expect_hash 后补丁永远
    无法应用；
  * 第二个 owner 申请同一目标时，真实原因（目标已被占用）被 hash 原因掩盖。

解决：解析目标时先看进程占用表——若目标已被某个 Registry 接管，
就从那个 Registry 取出它保存的原实现，而不是当前位置上的替代实现。
"""

from __future__ import annotations

from typing import Any

from ._claims import claim_holder


def resolve_original(target: str, property_part: str, raw_current: Any) -> Any:
    """返回用于版本校验的原实现。

    target         目标字符串（``module:attr``）
    property_part  目标涉及的 property 部分（get / set / delete）
    raw_current    当前位置上解析出的底层可调用对象（可能是替代实现）

    目标未被任何 Registry 接管时，原样返回 raw_current。
    """
    holder = claim_holder(target, property_part)
    if holder is None:
        return raw_current
    original = holder.get_original(target)
    if original is None:
        return raw_current
    return original
