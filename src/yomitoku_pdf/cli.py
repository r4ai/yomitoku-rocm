from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


SUPPORTED_FORMATS = ("md", "json", "csv", "html", "pdf")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yomitoku-pdf",
        description="Run YomiToku OCR for PDFs and document images.",
    )
    parser.add_argument("input", type=Path, help="PDF, image, or directory to analyze")
    parser.add_argument(
        "-o",
        "--outdir",
        default="results",
        help="Output directory passed to YomiToku",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=SUPPORTED_FORMATS,
        default="pdf",
        help="Output format. Use pdf for searchable PDF output.",
    )
    parser.add_argument(
        "-d",
        "--device",
        default="cuda",
        choices=("cuda", "cpu", "mps"),
        help="Inference device passed to YomiToku. ROCm PyTorch exposes AMD GPUs as cuda.",
    )
    parser.add_argument(
        "-v",
        "--vis",
        action="store_true",
        help="Write YomiToku visualization images.",
    )
    parser.add_argument(
        "-l",
        "--lite",
        action="store_true",
        help="Use the lightweight YomiToku model.",
    )
    parser.add_argument(
        "--combine",
        action="store_true",
        help="Combine multi-page PDF results into one exported file when supported.",
    )
    parser.add_argument(
        "--figure",
        action="store_true",
        help="Export detected figures and images.",
    )
    parser.add_argument(
        "--figure-letter",
        action="store_true",
        help="Export text contained in detected figures and tables.",
    )
    parser.add_argument(
        "--ignore-line-break",
        action="store_true",
        help="Join paragraph text instead of preserving image line breaks.",
    )
    parser.add_argument(
        "--ignore-meta",
        action="store_true",
        help="Exclude detected headers, footers, and similar metadata text.",
    )
    parser.add_argument(
        "--ignore-ruby",
        action="store_true",
        help="Exclude furigana/ruby text from output.",
    )
    parser.add_argument(
        "--ruby-threshold",
        type=float,
        help="Ruby detection threshold used with --ignore-ruby.",
    )
    parser.add_argument(
        "--encoding",
        help="Output encoding passed to YomiToku, for example utf-8 or cp932.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the underlying YomiToku command without running it.",
    )
    return parser


def make_yomitoku_command(args: argparse.Namespace) -> list[str]:
    executable = shutil.which("yomitoku")
    if executable is None:
        raise SystemExit(
            "Could not find the 'yomitoku' command. Run 'uv sync' first, then retry with 'uv run yomitoku-pdf ...'."
        )

    command = [
        executable,
        str(args.input),
        "-f",
        args.format,
        "-o",
        args.outdir,
        "-d",
        args.device,
    ]

    flag_map = {
        "vis": "-v",
        "lite": "--lite",
        "combine": "--combine",
        "figure": "--figure",
        "figure_letter": "--figure_letter",
        "ignore_line_break": "--ignore_line_break",
        "ignore_meta": "--ignore_meta",
        "ignore_ruby": "--ignore_ruby",
    }
    for attr, flag in flag_map.items():
        if getattr(args, attr):
            command.append(flag)

    if args.ruby_threshold is not None:
        command.extend(["--ruby_threshold", str(args.ruby_threshold)])
    if args.encoding:
        command.extend(["--encoding", args.encoding])

    return command


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.input.exists():
        parser.error(f"input path does not exist: {args.input}")

    command = make_yomitoku_command(args)
    if args.dry_run:
        print(" ".join(command))
        return 0

    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

