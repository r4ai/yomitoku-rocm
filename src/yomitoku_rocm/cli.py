from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    exe = shutil.which("yomitoku")
    if exe is None:
        print("yomitoku not found. Run: uv sync", file=sys.stderr)
        return 1
    return subprocess.run([exe, *sys.argv[1:]], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
