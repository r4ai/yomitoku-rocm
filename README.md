# yomitoku-pdf

ROCm on WSL2 で YomiToku を使い、PDF を OCR して searchable PDF、Markdown、JSON、CSV、HTML に変換するための `mise` + `uv` プロジェクトです。

## 前提

- Windows 側に AMD Software: Adrenalin Edition for WSL2 を入れます。
- WSL 側は Ubuntu 24.04 または 22.04 を使います。このリポジトリは Ubuntu 24.04 で作っています。
- AMD の WSL ROCm 最新系は ROCDXG + ROCm 7.2.1 前提です。ROCDXG の Quickstart 後、WSL 内で `rocminfo` が GPU agent を表示する状態にしてください。
- RX 7000/9000 系 GPU を想定しています。
- ROCm PyTorch では AMD GPU も PyTorch 上は `cuda` device として扱われます。YomiToku 実行時も `-d cuda` を使います。

参考:

- AMD ROCm WSL guide: <https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/wsl/howto_wsl.html>
- AMD PyTorch on ROCm: <https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install/3rd-party/pytorch-install.html>
- uv PyTorch integration: <https://docs.astral.sh/uv/guides/integration/pytorch/>
- YomiToku: <https://github.com/kotaro-kinoshita/yomitoku>

## セットアップ

WSL 側の ROCm / ROCDXG をまだ入れていない場合:

```bash
mise run setup-wsl-rocm
```

この task は `sudo` を使い、AMD ROCm 7.2.4 の apt repository 登録、`rocm` userspace package の導入、ROCDXG のビルド/インストール、`HSA_ENABLE_DXG_DETECTION=1` の設定を行います。完了後に PowerShell で `wsl --shutdown` してから WSL を開き直してください。

YomiToku 用 Python 環境:

```bash
mise install
mise run sync
mise run doctor
```

`mise run doctor` は次を確認します。

- `/dev/dxg` が存在する
- `rocminfo` が使える
- `torch.version.hip` が ROCm build を示す
- `torch.cuda.is_available()` が `True`
- `yomitoku` の import と CLI 起動ができる

この環境では PyTorch 関連パッケージだけを `https://download.pytorch.org/whl/rocm7.2` から取得するよう `pyproject.toml` で明示しています。他の依存関係は通常の PyPI から解決します。2026-06-14 時点でこの index に公開されている Python 3.12 向けの整合セットとして、`torch==2.11.0`、`torchvision==0.26.0`、`torchaudio==2.11.0` を固定しています。

## PDF OCR

searchable PDF を作る例:

```bash
mise run ocr -- sample.pdf -o results -f pdf -d cuda --combine
```

Markdown を作る例:

```bash
uv run yomitoku-pdf sample.pdf -o results -f md -d cuda --combine --figure
```

GPU が使えない環境で最低限確認する例:

```bash
uv run yomitoku-pdf sample.pdf -o results -f md --lite -d cpu
```

`yomitoku-pdf` は YomiToku CLI を薄く包んだラッパーです。主なオプションはそのまま渡せます。

```bash
uv run yomitoku-pdf --help
```

## トラブルシュート

`rocminfo` が見つからない場合は、WSL 側の ROCm パッケージ導入が未完了です。Ubuntu 標準リポジトリの古い `rocminfo` ではなく、AMD の ROCm 7.2.1 / ROCDXG 手順に沿って導入してください。

`torch.cuda.is_available()` が `False` の場合は、Windows 側ドライバ、ROCDXG、WSL の GPU device 公開、GPU の対応状況を順に確認してください。まず `/dev/dxg` と `rocminfo` の GPU agent 表示が必要です。
