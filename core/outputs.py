"""Server-owned output path resolution for web-facing workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from core.config import get_settings
from core.errors import UnsafePathError

DEFAULT_OUTPUT_SUFFIXES = (".mbz", ".tar.gz", ".tgz")


def resolve_output_path(
    filename: str,
    *,
    root: str | Path | None = None,
    allowed_suffixes: Iterable[str] | None = DEFAULT_OUTPUT_SUFFIXES,
) -> Path:
    """Resolve a user-supplied filename inside a server-owned output root.

    Only a bare filename is accepted; directory separators, absolute paths,
    traversal, and unexpected extensions are rejected.
    """
    if not filename or filename in {".", ".."}:
        raise UnsafePathError("An output filename is required")
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise UnsafePathError(f"Output filename must not contain a path: {filename!r}")

    name = Path(filename)
    if name.is_absolute() or name.name != filename:
        raise UnsafePathError(f"Output filename must be a bare name: {filename!r}")

    if allowed_suffixes is not None:
        suffixes = tuple(allowed_suffixes)
        if suffixes and not filename.lower().endswith(suffixes):
            raise UnsafePathError(
                f"Unsupported output type: {filename!r}. "
                f"Allowed: {', '.join(suffixes)}"
            )

    base = Path(root) if root is not None else get_settings().output_dir
    base.mkdir(parents=True, exist_ok=True)
    base_resolved = base.resolve()
    candidate = (base_resolved / name).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise UnsafePathError(
            f"Output path escapes the output root: {filename!r}"
        ) from exc
    return candidate
