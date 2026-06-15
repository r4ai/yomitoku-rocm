from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from yomitoku_rocm.executable import find_yomitoku_executable
from yomitoku_rocm.progress import ProgressReporter, make_reporter

MANIFEST_VERSION = 1
DEFAULT_CHUNK_SIZE = 10
SUPPORTED_FORMATS = {"json", "csv", "html", "md", "pdf"}
CAPTURED_TAIL_LINES = 20
RESUME_HINT = "Re-run the same command to resume after fixing the error."
INTERRUPT_HINT = "Interrupted. Re-run the same command to resume from where it stopped."
# yomitoku runs the text recognizer exactly once per page; counting these log
# lines gives a best-effort per-page progress signal (it degrades gracefully if
# the format changes — the bar simply stops advancing mid-chunk).
PAGE_MARKER = re.compile(r"TextRecognizer\b.*\belapsed_time:")


@dataclass(frozen=True)
class PdfFingerprint:
    path: str
    size: int
    mtime_ns: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class Chunk:
    index: int
    start_page: int
    end_page: int
    input_path: Path
    outdir: Path

    @property
    def page_count(self) -> int:
        return self.end_page - self.start_page + 1


def main() -> int:
    args, yomitoku_args = parse_args(sys.argv[1:])
    input_pdf = args.input_pdf.resolve()
    outdir = resolve_outdir(yomitoku_args).resolve()
    fmt = resolve_format(yomitoku_args)
    if fmt not in SUPPORTED_FORMATS:
        print(
            f"Invalid output format: {fmt}. "
            f"Supported formats are {sorted(SUPPORTED_FORMATS)}",
            file=sys.stderr,
        )
        return 2

    if input_pdf.suffix.lower() != ".pdf":
        print(f"yomitoku-pdf supports PDF input only: {input_pdf}", file=sys.stderr)
        return 2

    exe = find_yomitoku_executable()
    if exe is None:
        print("yomitoku not found. Run: uv sync", file=sys.stderr)
        return 1

    outdir.mkdir(parents=True, exist_ok=True)
    fingerprint = fingerprint_pdf(input_pdf)
    workdir = (
        args.workdir or outdir / ".yomitoku-pdf" / fingerprint.sha256[:16]
    ).resolve()
    manifest_path = workdir / "manifest.json"

    if args.no_resume and workdir.exists():
        shutil.rmtree(workdir)

    reader = PdfReader(str(input_pdf))
    total_pages = len(reader.pages)
    chunks = build_chunks(workdir, total_pages, args.chunk_size)
    manifest = load_or_create_manifest(
        manifest_path=manifest_path,
        fingerprint=fingerprint,
        total_pages=total_pages,
        chunk_size=args.chunk_size,
        fmt=fmt,
        force=args.force,
    )

    write_chunks(reader, chunks, manifest)
    started_at = time.monotonic()
    done_pages_at_start = count_done_pages(chunks, manifest)
    final_path = final_output_path(input_pdf, outdir, fmt)

    try:
        return run_pipeline(
            args=args,
            yomitoku_args=yomitoku_args,
            chunks=chunks,
            manifest=manifest,
            manifest_path=manifest_path,
            exe=exe,
            fmt=fmt,
            input_pdf=input_pdf,
            final_path=final_path,
            workdir=workdir,
            total_pages=total_pages,
            started_at=started_at,
            done_pages_at_start=done_pages_at_start,
        )
    except KeyboardInterrupt:
        print(f"\n{INTERRUPT_HINT}", file=sys.stderr, flush=True)
        return 130


def run_pipeline(
    *,
    args: argparse.Namespace,
    yomitoku_args: list[str],
    chunks: list[Chunk],
    manifest: dict[str, Any],
    manifest_path: Path,
    exe: str,
    fmt: str,
    input_pdf: Path,
    final_path: Path,
    workdir: Path,
    total_pages: int,
    started_at: float,
    done_pages_at_start: int,
) -> int:
    with make_reporter(verbose=args.verbose) as reporter:
        reporter.start(
            input_label=str(input_pdf),
            output_label=str(final_path),
            fmt=fmt,
            total_pages=total_pages,
            total_chunks=len(chunks),
            done_pages=done_pages_at_start,
        )
        on_line = make_line_handler(reporter)

        for chunk in chunks:
            chunk_key = str(chunk.index)
            chunk_state = manifest["chunks"].setdefault(chunk_key, {})
            output_path = chunk_state.get("output_path")
            if (
                chunk_state.get("status") == "done"
                and output_path
                and Path(output_path).exists()
            ):
                reporter.chunk_skip(
                    index=chunk.index,
                    start_page=chunk.start_page,
                    end_page=chunk.end_page,
                    done_pages=count_done_pages(chunks, manifest),
                )
                continue

            reporter.chunk_start(
                index=chunk.index,
                total_chunks=len(chunks),
                start_page=chunk.start_page,
                end_page=chunk.end_page,
                page_count=chunk.page_count,
            )
            chunk.outdir.mkdir(parents=True, exist_ok=True)
            command = build_yomitoku_command(exe, yomitoku_args, chunk, fmt)
            result = run_chunk(command, capture=not args.verbose, on_line=on_line)
            if result.returncode != 0:
                chunk_state.update(
                    {
                        "status": "failed",
                        "returncode": result.returncode,
                        "updated_at": now_iso(),
                    }
                )
                save_manifest(manifest_path, manifest)
                reporter.chunk_fail(
                    index=chunk.index,
                    total_chunks=len(chunks),
                    message=(
                        f"yomitoku exited with code {result.returncode} "
                        f"on chunk {chunk.index + 1} "
                        f"(pages {chunk.start_page}-{chunk.end_page})."
                    ),
                    captured=tail_output(result),
                    hint=RESUME_HINT,
                )
                return result.returncode

            produced = find_chunk_output(chunk.outdir, fmt)
            if produced is None:
                chunk_state.update({"status": "failed", "updated_at": now_iso()})
                save_manifest(manifest_path, manifest)
                reporter.chunk_fail(
                    index=chunk.index,
                    total_chunks=len(chunks),
                    message=(
                        f"yomitoku finished but produced no .{fmt} file "
                        f"in {chunk.outdir}."
                    ),
                    captured=tail_output(result),
                    hint=RESUME_HINT,
                )
                return 1

            chunk_state.update(
                {
                    "status": "done",
                    "output_path": str(produced),
                    "page_count": chunk.page_count,
                    "updated_at": now_iso(),
                }
            )
            save_manifest(manifest_path, manifest)
            reporter.chunk_done(
                index=chunk.index,
                start_page=chunk.start_page,
                end_page=chunk.end_page,
                done_pages=count_done_pages(chunks, manifest),
            )

        merge_outputs(
            chunks, manifest, final_path, fmt, resolve_encoding(yomitoku_args)
        )

        if args.keep_workdir:
            reporter.info(f"Work directory kept: {workdir}")
        else:
            shutil.rmtree(workdir)

        reporter.finish(
            output_label=str(final_path),
            total_pages=total_pages,
            elapsed=time.monotonic() - started_at,
        )

    return 0


@dataclass
class ChunkResult:
    returncode: int
    tail: list[str] = field(default_factory=list)


def make_line_handler(reporter: ProgressReporter) -> Callable[[str], None]:
    def handle(line: str) -> None:
        reporter.log_line(line)
        if PAGE_MARKER.search(line):
            reporter.page_tick()

    return handle


def run_chunk(
    command: list[str], *, capture: bool, on_line: Callable[[str], None]
) -> ChunkResult:
    """Run a chunk, streaming output line by line so progress stays live.

    When ``capture`` is false the child inherits stdio (``--verbose``); otherwise
    output is piped, forwarded to ``on_line``, and the tail is kept for failures.
    On KeyboardInterrupt the child is terminated before the exception propagates.
    """
    if not capture:
        proc = subprocess.Popen(command, env=child_env())
        try:
            return ChunkResult(returncode=proc.wait())
        except KeyboardInterrupt:
            terminate_process(proc)
            raise

    proc = subprocess.Popen(
        command,
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    tail: deque[str] = deque(maxlen=CAPTURED_TAIL_LINES)
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            tail.append(line)
            on_line(line)
        return ChunkResult(returncode=proc.wait(), tail=list(tail))
    except KeyboardInterrupt:
        terminate_process(proc)
        raise
    finally:
        if proc.stdout is not None:
            proc.stdout.close()


def terminate_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def tail_output(result: ChunkResult) -> list[str] | None:
    lines = [line for line in result.tail if line.strip()]
    return lines or None


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Run YomiToku on large PDFs in resumable page chunks.",
        allow_abbrev=False,
    )
    parser.add_argument("input_pdf", type=Path, help="target PDF file")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--keep-workdir", action="store_true")
    parser.add_argument(
        "--force", action="store_true", help="discard incompatible saved progress"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="stream raw yomitoku output instead of the live progress dashboard",
    )
    args, yomitoku_args = parser.parse_known_args(argv)
    if args.chunk_size < 1:
        parser.error("--chunk-size must be greater than zero")
    return args, yomitoku_args


def resolve_outdir(args: list[str]) -> Path:
    for i, arg in enumerate(args):
        if arg in {"-o", "--outdir"} and i + 1 < len(args):
            return Path(args[i + 1])
        if arg.startswith("--outdir="):
            return Path(arg.split("=", 1)[1])
    return Path("results")


def resolve_format(args: list[str]) -> str:
    fmt = "pdf"
    for i, arg in enumerate(args):
        if arg in {"-f", "--format"} and i + 1 < len(args):
            fmt = args[i + 1]
        elif arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
    fmt = fmt.lower()
    return "md" if fmt == "markdown" else fmt


def resolve_encoding(args: list[str]) -> str:
    for i, arg in enumerate(args):
        if arg == "--encoding" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--encoding="):
            return arg.split("=", 1)[1]
    return "utf-8"


def fingerprint_pdf(path: Path) -> PdfFingerprint:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return PdfFingerprint(
        path=str(path),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=digest.hexdigest(),
    )


def build_chunks(workdir: Path, total_pages: int, chunk_size: int) -> list[Chunk]:
    chunks = []
    chunk_dir = workdir / "chunks"
    output_root = workdir / "outputs"
    for index, start in enumerate(range(1, total_pages + 1, chunk_size)):
        end = min(start + chunk_size - 1, total_pages)
        name = f"{index + 1:05d}_p{start:05d}-{end:05d}"
        chunks.append(
            Chunk(
                index=index,
                start_page=start,
                end_page=end,
                input_path=chunk_dir / f"{name}.pdf",
                outdir=output_root / name,
            )
        )
    return chunks


def load_or_create_manifest(
    manifest_path: Path,
    fingerprint: PdfFingerprint,
    total_pages: int,
    chunk_size: int,
    fmt: str,
    force: bool,
) -> dict[str, Any]:
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as f:
            manifest = json.load(f)
        compatible = (
            manifest.get("version") == MANIFEST_VERSION
            and manifest.get("source") == fingerprint.as_dict()
            and manifest.get("total_pages") == total_pages
            and manifest.get("chunk_size") == chunk_size
            and manifest.get("format") == fmt
        )
        if compatible:
            return manifest
        if not force:
            raise SystemExit(
                f"Saved progress in {manifest_path} is for different input/options. "
                "Use --force or --no-resume to start over."
            )
        shutil.rmtree(manifest_path.parent)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": MANIFEST_VERSION,
        "source": fingerprint.as_dict(),
        "total_pages": total_pages,
        "chunk_size": chunk_size,
        "format": fmt,
        "created_at": now_iso(),
        "chunks": {},
    }
    save_manifest(manifest_path, manifest)
    return manifest


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp_path.replace(path)


def write_chunks(
    reader: PdfReader, chunks: list[Chunk], manifest: dict[str, Any]
) -> None:
    for chunk in chunks:
        if chunk.input_path.exists():
            continue
        chunk.input_path.parent.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        for page_index in range(chunk.start_page - 1, chunk.end_page):
            writer.add_page(reader.pages[page_index])
        with chunk.input_path.open("wb") as f:
            writer.write(f)
        manifest["chunks"].setdefault(str(chunk.index), {}).update(
            {
                "status": "pending",
                "start_page": chunk.start_page,
                "end_page": chunk.end_page,
                "input_path": str(chunk.input_path),
            }
        )


def build_yomitoku_command(
    exe: str, args: list[str], chunk: Chunk, fmt: str
) -> list[str]:
    forwarded = strip_yomitoku_positionals_and_output(args)
    command = [exe, str(chunk.input_path), "-o", str(chunk.outdir), "-f", fmt]
    command.extend(forwarded)
    if "--combine" not in forwarded:
        command.append("--combine")
    return command


def strip_yomitoku_positionals_and_output(args: list[str]) -> list[str]:
    stripped: list[str] = []
    skip_next = False
    options_with_value = {
        "-f",
        "--format",
        "-o",
        "--outdir",
        "--pages",
    }
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in options_with_value:
            skip_next = True
            continue
        if any(
            arg.startswith(f"{option}=")
            for option in ["--format", "--outdir", "--pages"]
        ):
            continue
        stripped.append(arg)
    return stripped


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("HSA_ENABLE_DXG_DETECTION", "1")
    return env


def find_chunk_output(outdir: Path, fmt: str) -> Path | None:
    candidates = sorted(outdir.glob(f"*.{fmt}"), key=lambda p: p.stat().st_mtime_ns)
    if not candidates:
        return None
    return candidates[-1]


def count_done_pages(chunks: list[Chunk], manifest: dict[str, Any]) -> int:
    total = 0
    for chunk in chunks:
        state = manifest["chunks"].get(str(chunk.index), {})
        if state.get("status") == "done":
            total += chunk.page_count
    return total


def final_output_path(input_pdf: Path, outdir: Path, fmt: str) -> Path:
    return outdir / f"{input_pdf.stem}.{fmt}"


def merge_outputs(
    chunks: list[Chunk],
    manifest: dict[str, Any],
    final_path: Path,
    fmt: str,
    encoding: str,
) -> None:
    paths = [
        Path(manifest["chunks"][str(chunk.index)]["output_path"]) for chunk in chunks
    ]
    if fmt == "pdf":
        writer = PdfWriter()
        for path in paths:
            reader = PdfReader(str(path))
            for page in reader.pages:
                writer.add_page(page)
        with final_path.open("wb") as f:
            writer.write(f)
    elif fmt == "json":
        data = []
        for path in paths:
            with path.open(encoding=encoding, errors="ignore") as f:
                item = json.load(f)
            if isinstance(item, list):
                data.extend(item)
            else:
                data.append(item)
        with final_path.open("w", encoding=encoding, errors="ignore") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    elif fmt == "csv":
        with final_path.open(
            "w", newline="", encoding=encoding, errors="ignore"
        ) as out:
            writer = csv.writer(out)
            for path in paths:
                with path.open(newline="", encoding=encoding, errors="ignore") as inp:
                    writer.writerows(csv.reader(inp))
    else:
        separator = "\n" if fmt == "md" else "\n"
        with final_path.open("w", encoding=encoding, errors="ignore") as out:
            for i, path in enumerate(paths):
                if i > 0:
                    out.write(separator)
                out.write(path.read_text(encoding=encoding, errors="ignore"))


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
