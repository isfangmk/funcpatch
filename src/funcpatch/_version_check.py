"""依赖版本守卫：funcpatch 透传 wrapt 2.5 引入的 with_doc 等 API。

在导入任何依赖这些 API 的模块前执行，给出清晰的安装提示。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

MIN_VERSION = (2, 5)


def check_wrapt_version() -> None:
    try:
        installed = version("wrapt")
    except PackageNotFoundError:
        raise ImportError("funcpatch 需要 wrapt>=2.5；请执行 pip install 'wrapt>=2.5'") from None

    parts = installed.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return  # 非标准版本号不阻断，由后续 import 自行决定
    if (major, minor) < MIN_VERSION:
        raise ImportError(
            f"funcpatch 需要 wrapt>=2.5，当前已安装 {installed}；请执行 pip install 'wrapt>=2.5'"
        )


check_wrapt_version()
