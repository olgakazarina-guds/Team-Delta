"""
===============================================================================
File:        logging_conf.py
Institution: German University of Digital Science
Project:     GUDS Coding Camp I Capstone Project
Instructor:  Prof. Dr. Thomas Staubitz
Team:        Team Delta
Members:     Olga Kazarina, Augustine Atta Abrefa, Ronald K. Sebuhinja
Date:        09 June 2026

Description:
    This module handles the process reporting for CLI commands.

    A CLI command is a small pipeline of steps (parse, transform, validate, export,
    …).  ``ProcessReporter`` wraps each step in a context manager that:

    * logs when the step starts and finishes,
    * times it,
    * records whether it SUCCEEDED or FAILED (capturing the exception detail),
    * and re-raises any exception so the command can still abort.

    At the end the command calls ``render()`` to print a summary table showing every
    step and its outcome.  Because the failed step is recorded *before* the
    exception propagates, rendering the report in a ``finally`` block always shows
    exactly where a run broke.
===============================================================================
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from rich.console import Console
from rich.table import Table

_log = logging.getLogger("lms_convert.process")


class StepStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ProcessStep:
    """One recorded step: what it was, how it ended, how long it took."""
    name: str
    status: StepStatus
    duration_s: float
    detail: str = ""


@dataclass
class ProcessReporter:
    """
    Collects ProcessStep records for a single CLI command run.

    Usage:
        reporter = ProcessReporter("Inspect openedx course")
        try:
            with reporter.step("Parse archive"):
                ...
            with reporter.step("Transform to IR"):
                ...
        finally:
            reporter.render()      # always show what happened
    """
    title: str = "CLI process"
    steps: List[ProcessStep] = field(default_factory=list)

    @contextmanager
    def step(self, name: str):
        """Time and record a single step; re-raises on failure after recording."""
        _log.info("→ %s", name)
        start = time.perf_counter()
        try:
            yield
        except Exception as exc:
            duration = time.perf_counter() - start
            self.steps.append(ProcessStep(
                name, StepStatus.FAILED, duration, f"{type(exc).__name__}: {exc}"
            ))
            _log.error("✗ %s failed after %.3fs — %s", name, duration, exc)
            raise
        else:
            duration = time.perf_counter() - start
            self.steps.append(ProcessStep(name, StepStatus.SUCCESS, duration, ""))
            _log.info("✓ %s (%.3fs)", name, duration)

    @property
    def succeeded(self) -> bool:
        """True only if every recorded step succeeded (and at least one ran)."""
        return bool(self.steps) and all(
            s.status is StepStatus.SUCCESS for s in self.steps
        )

    @property
    def total_duration_s(self) -> float:
        return sum(s.duration_s for s in self.steps)

    def render(self, console: Optional[Console] = None) -> None:
        """Print a summary table of every step and the overall outcome."""
        console = console or Console()
        table = Table(title=self.title, show_lines=False)
        table.add_column("#", justify="right", style="dim")
        table.add_column("Step")
        table.add_column("Result", justify="center")
        table.add_column("Time", justify="right")
        table.add_column("Detail")

        for idx, step in enumerate(self.steps, start=1):
            if step.status is StepStatus.SUCCESS:
                result = "[green] success[/green]"
            else:
                result = "[red] failed[/red]"
            table.add_row(
                str(idx),
                step.name,
                result,
                f"{step.duration_s:.3f}s",
                step.detail,
            )

        console.print(table)
        if self.succeeded:
            console.print(
                f"[bold green]Process succeeded[/bold green] — "
                f"{len(self.steps)} steps in {self.total_duration_s:.3f}s"
            )
        else:
            failed = sum(1 for s in self.steps if s.status is StepStatus.FAILED)
            console.print(
                f"[bold red]Process failed[/bold red] — "
                f"{failed} of {len(self.steps)} steps failed"
            )
