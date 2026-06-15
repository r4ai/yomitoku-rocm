from __future__ import annotations

import os
import shutil
import subprocess
import sys


def main() -> int:
    exe = shutil.which("yomitoku")
    if exe is None:
        print("yomitoku not found. Run: uv sync", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env.setdefault("HSA_ENABLE_DXG_DETECTION", "1")
    return subprocess.run([exe, *sys.argv[1:]], check=False, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
