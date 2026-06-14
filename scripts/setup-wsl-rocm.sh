#!/usr/bin/env bash
set -euo pipefail

ROCM_VERSION="${ROCM_VERSION:-7.2.4}"
AMDGPU_INSTALL_VERSION="${AMDGPU_INSTALL_VERSION:-7.2.4.70204-1}"
SDK_ROOT="${SDK_ROOT:-/mnt/c/Program Files (x86)/Windows Kits/10/Include}"
ROCDXG_DIR="${ROCDXG_DIR:-$HOME/src/repos/github.com/ROCm/librocdxg}"

if [[ ! -e /dev/dxg ]]; then
  echo "ERROR: /dev/dxg is not visible. Update/restart Windows WSL GPU driver first." >&2
  exit 1
fi

if ! grep -qi microsoft /proc/version; then
  echo "ERROR: This installer is intended for WSL2." >&2
  exit 1
fi

. /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "ERROR: This script currently targets Ubuntu 24.04 WSL. Found ${ID:-unknown} ${VERSION_ID:-unknown}." >&2
  exit 1
fi

echo "==> Installing ROCm ${ROCM_VERSION} package repository"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
deb="amdgpu-install_${AMDGPU_INSTALL_VERSION}_all.deb"
url="https://repo.radeon.com/amdgpu-install/${ROCM_VERSION}/ubuntu/noble/${deb}"
wget -O "$tmpdir/$deb" "$url"
sudo apt install -y "$tmpdir/$deb"
sudo apt update

echo "==> Installing ROCm userspace packages"
sudo apt install -y python3-setuptools python3-wheel git cmake build-essential rocm
sudo usermod -a -G render,video "$USER"

echo "==> Finding Windows SDK"
win_sdk=""
if [[ -d "$SDK_ROOT" ]]; then
  win_sdk="$(find "$SDK_ROOT" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort -V | tail -1)"
fi
if [[ -z "$win_sdk" ]]; then
  echo "ERROR: Windows SDK not found under $SDK_ROOT" >&2
  echo "Install Windows SDK on Windows, then retry." >&2
  exit 1
fi
win_sdk_path="$SDK_ROOT/$win_sdk"
echo "Using Windows SDK: $win_sdk_path"

echo "==> Building ROCDXG"
mkdir -p "$(dirname "$ROCDXG_DIR")"
if [[ -d "$ROCDXG_DIR/.git" ]]; then
  git -C "$ROCDXG_DIR" pull --ff-only
else
  git clone https://github.com/ROCm/librocdxg.git "$ROCDXG_DIR"
fi
cmake -S "$ROCDXG_DIR" -B "$ROCDXG_DIR/build" -DWIN_SDK="$win_sdk_path/shared"
cmake --build "$ROCDXG_DIR/build" --parallel "$(nproc)"
sudo cmake --install "$ROCDXG_DIR/build"
sudo ldconfig

echo "==> Writing ROCm/ROCDXG shell profile"
sudo tee /etc/profile.d/rocm-rocdxg.sh >/dev/null <<'EOF'
export PATH="/opt/rocm/bin:${PATH}"
export LD_LIBRARY_PATH="/opt/rocm/lib:${LD_LIBRARY_PATH:-}"
export HSA_ENABLE_DXG_DETECTION=1
EOF

export PATH="/opt/rocm/bin:${PATH}"
export LD_LIBRARY_PATH="/opt/rocm/lib:${LD_LIBRARY_PATH:-}"
export HSA_ENABLE_DXG_DETECTION=1

echo "==> Verifying ROCm"
if ! command -v rocminfo >/dev/null 2>&1; then
  echo "ERROR: rocminfo not found after ROCm install." >&2
  exit 1
fi
rocminfo | sed -n '1,160p'

echo
echo "ROCm/ROCDXG setup finished. Run 'wsl --shutdown' from PowerShell, reopen WSL, then run:"
echo "  cd /home/r4ai/src/repos/github.com/r4ai/yomitoku-pdf"
echo "  mise run doctor"
