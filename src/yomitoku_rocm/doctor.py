from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
from pathlib import Path


def print_check(name: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return ok


def command_output(command: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return 124, output
    return completed.returncode, completed.stdout


def check_rocm_devices() -> bool:
    ok = True
    ok &= print_check("/dev/dxg", Path("/dev/dxg").exists(), "required for ROCm on WSL")

    rocminfo_path = shutil.which("rocminfo")
    ok &= print_check("rocminfo command", rocminfo_path is not None, rocminfo_path or "not found")
    if rocminfo_path is not None:
        code, output = command_output([rocminfo_path])
        has_agent = "Agent " in output
        gfx_lines = [line.strip() for line in output.splitlines() if "gfx" in line.lower()]
        detail = "; ".join(gfx_lines[:3]) if gfx_lines else "no gfx agent lines found"
        ok &= print_check("rocminfo GPU agent", code == 0 and has_agent, detail)

    return ok


def check_python_packages() -> bool:
    ok = True
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        print_check("torch import", False, repr(exc))
        return False

    ok &= print_check("torch import", True, f"version={torch.__version__}")
    hip_version = getattr(torch.version, "hip", None)
    ok &= print_check("torch.version.hip", bool(hip_version), str(hip_version))

    cuda_available = torch.cuda.is_available()
    device_detail = "no CUDA/HIP device visible"
    if cuda_available:
        try:
            device_detail = torch.cuda.get_device_name(0)
        except Exception as exc:  # noqa: BLE001
            device_detail = f"device visible, name unavailable: {exc!r}"
    ok &= print_check("torch.cuda.is_available()", cuda_available, device_detail)

    try:
        import yomitoku  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        ok &= print_check("yomitoku import", False, repr(exc))
    else:
        version = importlib.metadata.version("yomitoku")
        ok &= print_check("yomitoku import", True, f"version={version}")

    yomitoku_cli = shutil.which("yomitoku")
    ok &= print_check("yomitoku CLI", yomitoku_cli is not None, yomitoku_cli or "not found")
    if yomitoku_cli is not None:
        code, output = command_output([yomitoku_cli, "--help"])
        first_line = output.splitlines()[0] if output.splitlines() else "no output"
        ok &= print_check("yomitoku --help", code == 0, first_line)

    return ok


def main() -> int:
    print("yomitoku-rocm doctor")
    print("====================")
    rocm_ok = check_rocm_devices()
    packages_ok = check_python_packages()

    if rocm_ok and packages_ok:
        print("All checks passed.")
        return 0

    print("One or more checks failed. See README.md for ROCm WSL setup prerequisites.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

