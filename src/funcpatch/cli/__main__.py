"""支持 python -m funcpatch.cli 运行。"""

from __future__ import annotations

import sys

from funcpatch.cli import main

if __name__ == "__main__":
    sys.exit(main())
