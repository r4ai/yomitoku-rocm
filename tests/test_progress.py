from __future__ import annotations

import io

from rich.console import Console

from yomitoku_rocm.progress import (
    PlainReporter,
    RichReporter,
    clean_log_line,
    compute_metrics,
    format_duration,
    make_reporter,
)


def test_format_duration_minutes_and_hours():
    assert format_duration(0) == "00:00"
    assert format_duration(59) == "00:59"
    assert format_duration(125) == "02:05"
    assert format_duration(3661) == "1:01:01"
    assert format_duration(-5) == "00:00"


def test_compute_metrics_without_progress_has_no_eta():
    m = compute_metrics(
        done_pages=10, total_pages=50, started_at=0.0, done_pages_at_start=10, now=5.0
    )
    assert m.fraction == 10 / 50
    assert m.seconds_per_page is None
    assert m.eta is None
    assert m.remaining is None


def test_compute_metrics_estimates_rate_and_remaining():
    m = compute_metrics(
        done_pages=30,
        total_pages=50,
        started_at=0.0,
        done_pages_at_start=10,
        now=40.0,
    )
    # 20 pages processed in 40s -> 2s/page; 20 pages remaining -> 40s.
    assert m.seconds_per_page == 2.0
    assert m.remaining is not None
    assert int(m.remaining.total_seconds()) == 40
    assert m.eta is not None


def test_compute_metrics_zero_total_is_safe():
    m = compute_metrics(0, 0, started_at=0.0, done_pages_at_start=0, now=1.0)
    assert m.fraction == 0.0
    assert m.eta is None


def _drive(reporter, *, out_done=True):
    reporter.start(
        input_label="document.pdf",
        output_label="results/document.md",
        fmt="md",
        total_pages=20,
        total_chunks=2,
        done_pages=0,
    )
    reporter.chunk_start(
        index=0, total_chunks=2, start_page=1, end_page=10, page_count=10
    )
    reporter.chunk_done(index=0, start_page=1, end_page=10, done_pages=10)
    reporter.chunk_skip(index=1, start_page=11, end_page=20, done_pages=20)
    if out_done:
        reporter.finish(
            output_label="results/document.md", total_pages=20, elapsed=42.0
        )


def test_plain_reporter_emits_one_line_per_event():
    out = io.StringIO()
    err = io.StringIO()
    reporter = PlainReporter(stream=out, error_stream=err)
    _drive(reporter)

    text = out.getvalue()
    assert "YomiToku PDF OCR  document.pdf -> results/document.md" in text
    assert "20 pages in 2 chunks (format: md)" in text
    assert "[1/2] chunk done · pages 1-10 · 10/20 (50%)" in text
    assert "[2/2] resumed · pages 11-20 · 20/20 (100%)" in text
    assert "Done · 20 pages · 00:42 · results/document.md" in text
    assert err.getvalue() == ""


def test_plain_reporter_failure_writes_to_error_stream():
    out = io.StringIO()
    err = io.StringIO()
    reporter = PlainReporter(stream=out, error_stream=err)
    reporter.start(
        input_label="d.pdf",
        output_label="o.md",
        fmt="md",
        total_pages=10,
        total_chunks=1,
        done_pages=0,
    )
    reporter.chunk_fail(
        index=0,
        total_chunks=1,
        message="yomitoku exited with code 1 on chunk 1.",
        captured=["Traceback", "RuntimeError: boom"],
        hint="Re-run to resume.",
    )
    error_text = err.getvalue()
    assert "yomitoku exited with code 1 on chunk 1." in error_text
    assert "  | RuntimeError: boom" in error_text
    assert "Re-run to resume." in error_text


def test_clean_log_line_strips_logger_prefix():
    raw = "2026-06-15 17:00:00,1 - yomitoku.text_recognizer - INFO - hello world"
    assert clean_log_line(raw) == "hello world"
    assert clean_log_line("plain line") == "plain line"
    assert clean_log_line("  trailing  \n") == "  trailing"


def test_page_tick_advances_displayed_done_and_caps_at_chunk_pages():
    reporter = RichReporter(console=Console(file=io.StringIO()))
    reporter.start(
        input_label="d.pdf",
        output_label="o.md",
        fmt="md",
        total_pages=20,
        total_chunks=2,
        done_pages=0,
    )
    reporter.chunk_start(
        index=0, total_chunks=2, start_page=1, end_page=10, page_count=10
    )
    assert reporter.displayed_done == 0
    reporter.page_tick()
    reporter.page_tick()
    assert reporter.displayed_done == 2
    for _ in range(50):
        reporter.page_tick()
    assert reporter.displayed_done == 10  # capped at the chunk's page count
    reporter.chunk_done(index=0, start_page=1, end_page=10, done_pages=10)
    assert reporter.displayed_done == 10  # reconciles to committed pages


def test_log_line_keeps_only_recent_cleaned_lines():
    reporter = RichReporter(console=Console(file=io.StringIO()))
    for i in range(6):
        reporter.log_line(f"ts - yomitoku - INFO - line {i}")
    assert list(reporter.logs) == ["line 3", "line 4", "line 5"]


def test_rich_reporter_renders_without_crashing():
    console = Console(
        file=io.StringIO(), force_terminal=True, width=100, color_system=None
    )
    reporter = RichReporter(console=console)
    _drive(reporter)
    output = console.file.getvalue()
    assert "YomiToku PDF OCR" in output
    assert "results/document.md" in output


def test_make_reporter_falls_back_to_plain_for_non_tty():
    assert isinstance(make_reporter(verbose=False, stdout=io.StringIO()), PlainReporter)
    assert isinstance(make_reporter(verbose=True, stdout=io.StringIO()), PlainReporter)
