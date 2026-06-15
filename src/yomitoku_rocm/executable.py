from __future__ import annotations

import shutil
import sys
from pathlib import Path


def find_yomitoku_executable() -> str | None:
    local_executable = Path(sys.executable).with_name("yomitoku")
    if local_executable.exists():
        return str(local_executable)

    local_windows_executable = local_executable.with_suffix(".exe")
    if local_windows_executable.exists():
        return str(local_windows_executable)

    return shutil.which("yomitoku")
