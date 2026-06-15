from __future__ import annotations

import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TextIO

from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

BAR_WIDTH = 32
SUB_BAR_WIDTH = 14
RECENT_LIMIT = 3
LOG_LIMIT = 3


def clean_log_line(line: str) -> str:
    """Strip the ``time - name - LEVEL -`` prefix yomitoku's logger prepends."""
    parts = line.rstrip().split(" - ", 3)
    return parts[-1] if len(parts) == 4 else line.rstrip()


def format_duration(seconds: float) -> str:
    total = int(max(seconds, 0))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class Metrics:
    done_pages: int
    total_pages: int
    fraction: float
    elapsed: float
    seconds_per_page: float | None
    remaining: timedelta | None
    eta: datetime | None


def compute_metrics(
    done_pages: int,
    total_pages: int,
    started_at: float,
    done_pages_at_start: int,
    now: float | None = None,
) -> Metrics:
    now = time.monotonic() if now is None else now
    elapsed = max(now - started_at, 0.0)
    fraction = done_pages / total_pages if total_pages else 0.0
    processed = max(done_pages - done_pages_at_start, 0)
    if processed == 0 or elapsed <= 0:
        return Metrics(done_pages, total_pages, fraction, elapsed, None, None, None)
    seconds_per_page = elapsed / processed
    remaining_pages = max(total_pages - done_pages, 0)
    remaining = timedelta(seconds=int(seconds_per_page * remaining_pages))
    eta = datetime.now().astimezone() + remaining
    return Metrics(
        done_pages, total_pages, fraction, elapsed, seconds_per_page, remaining, eta
    )


class ProgressReporter:
    """Base interface for progress display. Methods are no-ops by default."""

    def __enter__(self) -> ProgressReporter:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False

    def start(
        self,
        *,
        input_label: str,
        output_label: str,
        fmt: str,
        total_pages: int,
        total_chunks: int,
        done_pages: int,
    ) -> None: ...

    def chunk_start(
        self,
        *,
        index: int,
        total_chunks: int,
        start_page: int,
        end_page: int,
        page_count: int,
    ) -> None: ...

    def page_tick(self) -> None: ...

    def log_line(self, line: str) -> None: ...

    def chunk_done(
        self, *, index: int, start_page: int, end_page: int, done_pages: int
    ) -> None: ...

    def chunk_skip(
        self, *, index: int, start_page: int, end_page: int, done_pages: int
    ) -> None: ...

    def chunk_fail(
        self,
        *,
        index: int,
        total_chunks: int,
        message: str,
        captured: list[str] | None,
        hint: str,
    ) -> None: ...

    def finish(
        self, *, output_label: str, total_pages: int, elapsed: float
    ) -> None: ...

    def info(self, message: str) -> None: ...

    def close(self) -> None: ...


class PlainReporter(ProgressReporter):
    """One-line-per-event output for non-interactive terminals, pipes and CI."""

    def __init__(
        self, *, stream: TextIO | None = None, error_stream: TextIO | None = None
    ) -> None:
        self.out = stream or sys.stdout
        self.err = error_stream or sys.stderr
        self.total_pages = 0
        self.total_chunks = 0
        self.started_at = 0.0
        self.done_pages_at_start = 0

    def start(
        self,
        *,
        input_label: str,
        output_label: str,
        fmt: str,
        total_pages: int,
        total_chunks: int,
        done_pages: int,
    ) -> None:
        self.total_pages = total_pages
        self.total_chunks = total_chunks
        self.started_at = time.monotonic()
        self.done_pages_at_start = done_pages
        print(f"YomiToku PDF OCR  {input_label} -> {output_label}", file=self.out)
        print(
            f"  {total_pages} pages in {total_chunks} chunks (format: {fmt})",
            file=self.out,
            flush=True,
        )

    def _line(
        self, index: int, start_page: int, end_page: int, done_pages: int, verb: str
    ) -> str:
        m = compute_metrics(
            done_pages, self.total_pages, self.started_at, self.done_pages_at_start
        )
        eta = f" · ETA {m.eta.strftime('%H:%M:%S')}" if m.eta else " · ETA --:--:--"
        return (
            f"[{index + 1}/{self.total_chunks}] {verb} · "
            f"pages {start_page}-{end_page} · "
            f"{done_pages}/{self.total_pages} ({m.fraction:.0%}){eta}"
        )

    def chunk_done(
        self, *, index: int, start_page: int, end_page: int, done_pages: int
    ) -> None:
        print(
            self._line(index, start_page, end_page, done_pages, "chunk done"),
            file=self.out,
            flush=True,
        )

    def chunk_skip(
        self, *, index: int, start_page: int, end_page: int, done_pages: int
    ) -> None:
        print(
            self._line(index, start_page, end_page, done_pages, "resumed"),
            file=self.out,
            flush=True,
        )

    def chunk_fail(
        self,
        *,
        index: int,
        total_chunks: int,
        message: str,
        captured: list[str] | None,
        hint: str,
    ) -> None:
        print(message, file=self.err)
        for line in captured or []:
            print(f"  | {line}", file=self.err)
        print(hint, file=self.err, flush=True)

    def finish(self, *, output_label: str, total_pages: int, elapsed: float) -> None:
        print(
            f"Done · {total_pages} pages · {format_duration(elapsed)} · {output_label}",
            file=self.out,
            flush=True,
        )

    def info(self, message: str) -> None:
        print(message, file=self.out, flush=True)


class _Dashboard:
    """Renderable that reads live state from a RichReporter on each refresh."""

    def __init__(self, reporter: RichReporter) -> None:
        self.reporter = reporter

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        r = self.reporter
        done = r.displayed_done
        m = compute_metrics(done, r.total_pages, r.started_at, r.done_pages_at_start)

        yield Text("")
        yield Padding(
            Text.assemble(
                ("YomiToku PDF OCR  ", "bold cyan"),
                (r.input_label, "white"),
                ("  →  ", "dim"),
                (r.output_label, "green"),
            ),
            (0, 2),
        )
        yield Text("")

        if r.current_index is not None:
            chunk_label = f"chunk {r.current_index + 1}/{r.total_chunks}"
        else:
            chunk_label = f"{r.total_chunks}/{r.total_chunks} chunks"
        bar = ProgressBar(
            total=r.total_pages or 1,
            completed=done,
            width=BAR_WIDTH,
            complete_style="cyan",
            finished_style="green",
        )
        head = Table.grid(padding=(0, 2))
        head.add_row(
            bar,
            Text.assemble(
                (f"{m.fraction:>4.0%}", "bold"),
                ("   ", ""),
                (f"{done}/{r.total_pages} pages", "white"),
                ("   ", ""),
                (chunk_label, "cyan"),
            ),
        )
        yield Padding(head, (0, 2))

        metrics = [f"elapsed {format_duration(m.elapsed)}"]
        if m.seconds_per_page is not None:
            metrics.append(f"{m.seconds_per_page:.1f}s/page")
        if m.remaining is not None and m.eta is not None:
            metrics.append(
                f"ETA {format_duration(m.remaining.total_seconds())} "
                f"({m.eta.strftime('%H:%M:%S')})"
            )
        else:
            metrics.append("ETA calculating")
        yield Padding(Text(" · ".join(metrics), style="dim"), (0, 2))

        if r.recent or r.current is not None:
            yield Text("")
            yield Padding(Text("recent", style="dim"), (0, 2))
            for marker, style, text in r.recent:
                yield Padding(
                    Text.assemble((f"{marker} ", style), (text, "white")), (0, 4)
                )
            if r.current is not None:
                index, start_page, end_page = r.current
                sub = ProgressBar(
                    total=r.chunk_pages or 1,
                    completed=r.chunk_done_pages,
                    width=SUB_BAR_WIDTH,
                    complete_style="yellow",
                    finished_style="green",
                )
                line = Table.grid(padding=(0, 1))
                line.add_row(
                    r.spinner,
                    Text(f"chunk {index + 1}  pages {start_page}-{end_page}", "yellow"),
                    sub,
                    Text(f"page {r.chunk_done_pages}/{r.chunk_pages}", "dim"),
                )
                yield Padding(line, (0, 4))

        if r.logs:
            yield Text("")
            body = Text(
                "\n".join(r.logs), style="dim", no_wrap=True, overflow="ellipsis"
            )
            yield Padding(
                Panel(
                    body,
                    title="yomitoku",
                    title_align="left",
                    border_style="grey37",
                    padding=(0, 1),
                ),
                (0, 2),
            )
        yield Text("")


class RichReporter(ProgressReporter):
    """Live dashboard for interactive terminals."""

    def __init__(self, *, console: Console | None = None) -> None:
        self.console = console or Console()
        self.err_console = Console(stderr=True)
        self.input_label = ""
        self.output_label = ""
        self.total_pages = 0
        self.total_chunks = 0
        self.done_pages = 0
        self.started_at = 0.0
        self.done_pages_at_start = 0
        self.current: tuple[int, int, int] | None = None
        self.current_index: int | None = None
        self.chunk_pages = 0
        self.chunk_done_pages = 0
        self.recent: deque[tuple[str, str, str]] = deque(maxlen=RECENT_LIMIT)
        self.logs: deque[str] = deque(maxlen=LOG_LIMIT)
        self.spinner = Spinner("dots", style="yellow")
        self._chunk_started_at = 0.0
        self.live: Live | None = None

    @property
    def displayed_done(self) -> int:
        return self.done_pages + min(self.chunk_done_pages, self.chunk_pages)

    def start(
        self,
        *,
        input_label: str,
        output_label: str,
        fmt: str,
        total_pages: int,
        total_chunks: int,
        done_pages: int,
    ) -> None:
        self.input_label = input_label
        self.output_label = output_label
        self.total_pages = total_pages
        self.total_chunks = total_chunks
        self.done_pages = done_pages
        self.done_pages_at_start = done_pages
        self.started_at = time.monotonic()
        self.live = Live(
            _Dashboard(self),
            console=self.console,
            refresh_per_second=10,
            transient=True,
        )
        self.live.start()

    def chunk_start(
        self,
        *,
        index: int,
        total_chunks: int,
        start_page: int,
        end_page: int,
        page_count: int,
    ) -> None:
        self.current = (index, start_page, end_page)
        self.current_index = index
        self.chunk_pages = page_count
        self.chunk_done_pages = 0
        self._chunk_started_at = time.monotonic()

    def page_tick(self) -> None:
        if self.chunk_done_pages < self.chunk_pages:
            self.chunk_done_pages += 1

    def log_line(self, line: str) -> None:
        cleaned = clean_log_line(line)
        if cleaned:
            self.logs.append(cleaned)

    def chunk_done(
        self, *, index: int, start_page: int, end_page: int, done_pages: int
    ) -> None:
        self.done_pages = done_pages
        self.chunk_done_pages = 0
        self.chunk_pages = 0
        duration = format_duration(time.monotonic() - self._chunk_started_at)
        label = f"chunk {index + 1}  pages {start_page}-{end_page}   done in {duration}"
        self.recent.append(("✓", "green", label))
        self.current = None

    def chunk_skip(
        self, *, index: int, start_page: int, end_page: int, done_pages: int
    ) -> None:
        self.done_pages = done_pages
        self.current_index = index
        self.recent.append(
            (
                "↻",
                "dim",
                f"chunk {index + 1}  pages {start_page}-{end_page}   already done",
            )
        )
        self.current = None

    def chunk_fail(
        self,
        *,
        index: int,
        total_chunks: int,
        message: str,
        captured: list[str] | None,
        hint: str,
    ) -> None:
        self.recent.append(("✗", "red", f"chunk {index + 1}   failed"))
        self.current = None
        self.close()
        body = Text(message, style="bold red")
        if captured:
            body.append("\n\n")
            body.append("\n".join(captured), style="dim")
        self.err_console.print(
            Panel(body, title="✗ yomitoku failed", border_style="red", expand=False)
        )
        self.err_console.print(Text(hint, style="yellow"))

    def finish(self, *, output_label: str, total_pages: int, elapsed: float) -> None:
        self.close()
        spp = elapsed / total_pages if total_pages else 0.0
        body = Text.assemble(
            ("Output  ", "dim"),
            (output_label, "bold green"),
            ("\n"),
            ("Pages   ", "dim"),
            (f"{total_pages}", "white"),
            ("\n"),
            ("Elapsed ", "dim"),
            (f"{format_duration(elapsed)} ({spp:.1f}s/page)", "white"),
        )
        self.console.print(
            Panel(body, title="✓ done", border_style="green", expand=False)
        )

    def info(self, message: str) -> None:
        self.console.print(message)

    def close(self) -> None:
        if self.live is not None:
            self.live.stop()
            self.live = None


def make_reporter(*, verbose: bool, stdout: TextIO | None = None) -> ProgressReporter:
    stream = stdout or sys.stdout
    if not verbose and getattr(stream, "isatty", lambda: False)():
        try:
            return RichReporter()
        except Exception:
            return PlainReporter()
    return PlainReporter()
