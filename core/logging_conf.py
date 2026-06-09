"""
===============================================================================
File:        logging_conf.py
Institution: German University of Digital Science
Project:     GUDS Coding Camp I Capstone Project
Instructor:  Prof. Dr. Thomas Staubitz
Team:        Team Delta
Members:     Olga Kazarina, Augustine Atta Abrefa, Ronald K. Sebuhinja
Date:        08 June 2026

Description:
    This module is the central logging configuration for the lms-converter CLI.

    Every module obtains its logger with ``logging.getLogger(__name__)`` and simply
    logs; this module decides *where* those records go and *how* they look.  Call
    ``setup_logging()`` once, early in a CLI command, before any pipeline work runs.

    Two sinks (output destinations) are supported:
    - a console handler (pretty, colourised via rich) - always on
    - an optional rotating-free file handler - enabled by passing ``log_file``

    The function is idempotent: calling it again replaces the handlers it added
    previously rather than stacking duplicates, so repeated CLI invocations inside
    one process (e.g. tests) do not multiply log lines.
===============================================================================
"""

import logging
from pathlib import Path
from typing import Optional, Union

from rich.logging import RichHandler

# Marker attribute so we can recognise (and replace) handlers we installed.
_OWNED = "_lmsconvert_owned"

# Maps the friendly --log-level strings to logging module constants.
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def resolve_level(level: Union[str, int]) -> int:
    """Turn a level name ('info', 'DEBUG', …) or int into a logging constant."""
    if isinstance(level, int):
        return level
    return _LEVELS.get(level.upper(), logging.INFO)


def setup_logging(level: Union[str, int] = "INFO", log_file: Optional[str] = None,) -> logging.Logger:
    """
    Configure the root logger and return the package logger ('lms_convert').

    level    - minimum severity to emit (name or logging constant).
    log_file - if given, a plain-text copy of every record (always at DEBUG)
               is appended to this path; parent directories are created.

    Console output uses RichHandler for readable, colourised lines; the file
    sink uses a detailed timestamped format suitable for later inspection.
    """
    resolved = resolve_level(level)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Drop any handlers a previous setup_logging() installed (idempotency).
    for handler in list(root.handlers):
        if getattr(handler, _OWNED, False):
            root.removeHandler(handler)

    # --- Console sink: pretty print, level-filtered ---
    console = RichHandler(
        level=resolved,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=False,
    )
    console.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    setattr(console, _OWNED, True)
    root.addHandler(console)

    # --- Optional file sink: verbose, always DEBUG ---
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
        ))
        setattr(file_handler, _OWNED, True)
        root.addHandler(file_handler)

    return logging.getLogger("lms_convert")
