# yomitoku-rocm

ROCm on WSL2 で [YomiToku](https://github.com/kotaro-kinoshita/yomitoku) を動かすための環境セットアップ集です。AMD GPU 向けの PyTorch ROCm 依存関係、mise タスク、環境確認ツール（doctor）をまとめています。

## 前提条件

- **GPU**: AMD RX 7000/9000 系（ROCm 対応）
- **OS**: Windows + WSL2（Ubuntu 24.04 推奨）
- **Windows 側**: AMD Software: Adrenalin Edition for WSL2 をインストール済み
- **WSL 側**: ROCm 7.2.1 + ROCDXG 導入済み、`rocminfo` で GPU agent が表示される状態

> ROCm PyTorch では AMD GPU も `cuda` デバイスとして扱われます。YomiToku 実行時は `-d cuda` を使います。

参考ドキュメント:

- [AMD ROCm WSL インストールガイド](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/wsl/howto_wsl.html)
- [AMD PyTorch on ROCm](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install/3rd-party/pytorch-install.html)
- [uv PyTorch インテグレーション](https://docs.astral.sh/uv/guides/integration/pytorch/)

## セットアップ

### 1. ROCm / ROCDXG の導入（WSL）

WSL 側の ROCm をまだ入れていない場合は、このリポジトリのセットアップスクリプトで一括導入できます:

```bash
mise run setup-wsl-rocm
```

このスクリプトは `sudo` を使い、以下を行います:

- AMD ROCm 7.2.4 の apt リポジトリ登録と `rocm` パッケージの導入
- ROCDXG のビルドとインストール
- `/etc/environment` への `HSA_ENABLE_DXG_DETECTION=1` の追加

完了後は PowerShell で `wsl --shutdown` してから WSL を起動し直してください。

### 2. インストール

#### グローバルインストール（推奨）

`uv tool install` でグローバルにインストールすると、どのディレクトリからでも `yomitoku-rocm` と `yomitoku-rocm-doctor` を呼べます。

```bash
git clone https://github.com/r4ai/yomitoku-rocm
cd yomitoku-rocm
uv tool install .
```

インストール後、`~/.local/bin` にコマンドが追加されます。PATH が通っているか確認してください:

```bash
which yomitoku-rocm
```

通っていない場合は `~/.local/bin` を PATH に追加します:

```bash
# bash / zsh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# fish
fish_add_path ~/.local/bin
```

GPU 検出に必要な環境変数をシェルの設定に追加します（`mise run` を経由しない場合に必要）:

```bash
# bash / zsh
echo 'export HSA_ENABLE_DXG_DETECTION=1' >> ~/.bashrc

# fish
set -Ux HSA_ENABLE_DXG_DETECTION 1
```

#### 開発者向けセットアップ（mise + uv）

```bash
mise install
mise run sync
```

### 3. 動作確認

```bash
yomitoku-rocm-doctor
# または開発環境では:
mise run doctor
```

以下を確認します:

- `/dev/dxg` が存在する
- `rocminfo` が使える
- `torch.version.hip` が ROCm ビルドを示す
- `torch.cuda.is_available()` が `True`
- `yomitoku` の import と CLI 起動ができる

## 使い方

`yomitoku-rocm` は `yomitoku` CLI への透過的なラッパーです。引数はそのまま yomitoku に転送されます。

```bash
yomitoku-rocm --help
```

### グローバルインストール後

```bash
# searchable PDF を作成
yomitoku-rocm sample.pdf -o results -f pdf -d cuda --combine

# Markdown を作成（図も抽出）
yomitoku-rocm sample.pdf -o results -f md -d cuda --combine --figure

# CPU で動作確認（GPU なし環境）
yomitoku-rocm sample.pdf -o results -f md --lite -d cpu
```

### mise 経由（開発環境）

```bash
mise run ocr -- sample.pdf -o results -f pdf -d cuda --combine
```

`mise run ocr` は `uv run yomitoku` を直接呼びます。`HSA_ENABLE_DXG_DETECTION=1` も自動的に設定されます。

## 依存関係について

PyTorch 関連パッケージは `https://download.pytorch.org/whl/rocm7.2` から取得するよう `pyproject.toml` で明示しています。2026-06-14 時点でこの index の Python 3.12 向け整合セットとして `torch==2.11.0`、`torchvision==0.26.0`、`torchaudio==2.11.0` を固定しています。

## トラブルシュート

**`rocminfo` が見つからない**

WSL 側の ROCm パッケージ導入が未完了です。Ubuntu 標準リポジトリの古い `rocminfo` ではなく、AMD の ROCm 7.2.1 / ROCDXG 手順に沿って導入してください。

**`torch.cuda.is_available()` が `False`**

以下を順に確認してください:

1. `/dev/dxg` が存在するか
2. `rocminfo` で GPU agent が表示されるか
3. Windows 側の Adrenalin Edition ドライバが正しくインストールされているか
4. `wsl --shutdown` 後に WSL を起動し直したか

**グローバルインストール後に GPU が検出されない**

`HSA_ENABLE_DXG_DETECTION=1` がシェル環境に設定されているか確認してください。`mise run` 経由の場合は `mise.toml` で自動設定されますが、直接 `yomitoku-rocm` を呼ぶ場合はシェルの設定ファイルへの追加が必要です（[セットアップ手順を参照](#2-インストール)）。
