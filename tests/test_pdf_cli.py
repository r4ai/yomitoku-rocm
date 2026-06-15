from __future__ import annotations

import io
import sys

from rich.console import Console

from yomitoku_rocm.pdf_cli import (
    PAGE_MARKER,
    ChunkResult,
    make_line_handler,
    run_chunk,
    tail_output,
)
from yomitoku_rocm.progress import RichReporter


def test_page_marker_matches_recognizer_timing_lines():
    assert PAGE_MARKER.search(
        "2026-06-15 - yomitoku - INFO - TextRecognizer __call__ elapsed_time: 0.5"
    )
    assert not PAGE_MARKER.search(
        "2026-06-15 - yomitoku - INFO - TextDetector __call__ elapsed_time: 0.2"
    )
    assert not PAGE_MARKER.search("Processing file: foo.pdf")


def test_line_handler_ticks_pages_on_marker_and_logs_everything():
    reporter = RichReporter(console=Console(file=io.StringIO()))
    reporter.start(
        input_label="d.pdf",
        output_label="o.md",
        fmt="md",
        total_pages=10,
        total_chunks=1,
        done_pages=0,
    )
    reporter.chunk_start(
        index=0, total_chunks=1, start_page=1, end_page=10, page_count=10
    )
    handle = make_line_handler(reporter)
    handle("ts - yomitoku - INFO - Processing file: chunk.pdf")
    handle("ts - yomitoku - INFO - TextRecognizer __call__ elapsed_time: 0.5")
    handle("ts - yomitoku - INFO - TextRecognizer __call__ elapsed_time: 0.6")
    assert reporter.chunk_done_pages == 2
    assert list(reporter.logs)[-1] == "TextRecognizer __call__ elapsed_time: 0.6"


def test_run_chunk_streams_lines_and_reports_returncode():
    captured: list[str] = []
    script = "import sys; print('one'); print('two'); sys.exit(3)"
    result = run_chunk(
        [sys.executable, "-c", script],
        capture=True,
        on_line=captured.append,
    )
    assert isinstance(result, ChunkResult)
    assert result.returncode == 3
    assert captured == ["one", "two"]
    assert tail_output(result) == ["one", "two"]


def test_tail_output_returns_none_when_blank():
    assert tail_output(ChunkResult(returncode=0, tail=["", "   "])) is None
