# yomitoku-rocm

ROCm on WSL2 で [YomiToku](https://github.com/kotaro-kinoshita/yomitoku) を動かすための環境セットアップ集です。AMD GPU 向けの PyTorch ROCm 依存関係、mise タスク、環境確認ツール（doctor）を備えています。

## 前提条件

- **GPU**: AMD RX 7000/9000 系（ROCm 対応）
- **OS**: Windows + WSL2（Ubuntu 24.04 推奨）
- **Windows 側**: AMD Software: Adrenalin Edition for WSL2 をインストール済み
- **WSL 側**: ROCm 7.2.x + ROCDXG 導入済み、`rocminfo` で GPU agent が表示される状態

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
- `/etc/profile.d/rocm-rocdxg.sh` への ROCm/ROCDXG 環境変数の追加

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

ページ数の多い PDF には `yomitoku-pdf` を使います。PDF をデフォルト 10 ページ単位のチャンクに分けて OCR し、最後に 1 つの出力へ結合します。

```bash
yomitoku-pdf large.pdf -o results -f pdf -d cuda
```

実行中は進捗バー・完了ページ数・進捗率・経過時間・1 ページあたりの処理速度・残り時間・予想終了時刻と、直近のチャンク結果をライブ表示します。チャンク内のページ単位の進捗もサブバーで表示し、yomitoku 本体のログは末尾数行だけを枠付きエリアにまとめて表示します（画面を流れ続けません）。チャンクが失敗したときは末尾のログを表示します。途中で停止した場合は、同じ PDF・チャンクサイズ・出力形式で再実行すると `results/.yomitoku-pdf/<fingerprint>/manifest.json` をもとに完了済みチャンクをスキップして再開します。正常完了後はこの作業ディレクトリを自動削除します。

実行中に `Ctrl+C` で中断すると、処理中の yomitoku を停止して終了します。完了済みチャンクは保存されているため、同じコマンドで再実行すれば続きから再開できます。

パイプやファイルへリダイレクトした場合（非対話端末）は、1 イベント 1 行のプレーンな進捗ログへ自動で切り替わります。

```bash
# 20 ページ単位に変更
yomitoku-pdf large.pdf --chunk-size 20 -o results -f pdf -d cuda

# yomitoku の生ログをそのまま流す（進捗ダッシュボードは無効）
yomitoku-pdf large.pdf --verbose -o results -f pdf -d cuda

# デバッグ用に途中成果物を残す
yomitoku-pdf large.pdf --keep-workdir -o results -f pdf -d cuda

# 保存済み進捗を使わず最初から実行
yomitoku-pdf large.pdf --no-resume -o results -f pdf -d cuda
```

`yomitoku-pdf` はグローバルインストール後に直接実行した場合も、子プロセスに `HSA_ENABLE_DXG_DETECTION=1` を自動で渡します。

### グローバルインストール後

```bash
# searchable PDF を作成
yomitoku-rocm sample.pdf -o results -f pdf -d cuda --combine

# Markdown を作成（図も抽出）
yomitoku-rocm sample.pdf -o results -f md -d cuda --combine --figure

# CPU で動作確認（GPU なし環境）
yomitoku-rocm sample.pdf -o results -f md --lite -d cpu

# 巨大 PDF を分割処理して searchable PDF を作成
yomitoku-pdf large.pdf -o results -f pdf -d cuda
```

### mise 経由（開発環境）

```bash
mise run ocr -- sample.pdf -o results -f pdf -d cuda --combine
mise run ocr-pdf -- large.pdf -o results -f pdf -d cuda
```

`mise run ocr` は `uv run yomitoku` を直接呼びます。`HSA_ENABLE_DXG_DETECTION=1` も自動的に設定されます。

## 依存関係について

PyTorch 関連パッケージは `https://download.pytorch.org/whl/rocm7.2` から取得するよう `pyproject.toml` で明示しています。2026-06-14 時点でこの index の Python 3.12 向け互換セットとして `torch==2.11.0`、`torchvision==0.26.0`、`torchaudio==2.11.0` を固定しています。

## トラブルシュート

**`rocminfo` が見つからない**

WSL 側の ROCm パッケージ導入が未完了です。Ubuntu 標準リポジトリの古い `rocminfo` ではなく、AMD の ROCm 7.2.x / ROCDXG 手順に沿って導入してください。

**`torch.cuda.is_available()` が `False`**

以下を順に確認してください:

1. `/dev/dxg` が存在するか
2. `rocminfo` で GPU agent が表示されるか
3. Windows 側の Adrenalin Edition ドライバが正しくインストールされているか
4. `wsl --shutdown` 後に WSL を起動し直したか

**グローバルインストール後に GPU が検出されない**

`HSA_ENABLE_DXG_DETECTION=1` がシェル環境に設定されているか確認してください。`mise run` 経由の場合は `mise.toml` で自動設定されますが、直接 `yomitoku-rocm` を呼ぶ場合はシェルの設定ファイルへの追加が必要です（[セットアップ手順を参照](#2-インストール)）。
