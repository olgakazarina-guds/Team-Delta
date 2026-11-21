"""Artifact construction for LMS certification imports."""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.golden.corpus import run_case, run_export


@dataclass(frozen=True)
class BuiltArtifact:
    case_id: str
    target: str
    path: Path
    sha256: str
    size_bytes: int


ArtifactBuilder = Callable[[Mapping[str, Any], str, Path], BuiltArtifact]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    return _SAFE_NAME.sub("-", value).strip("-") or "case"


def build_golden_artifact(
    case: Mapping[str, Any],
    target: str,
    workspace: Path,
) -> BuiltArtifact:
    """Generate a target archive from one golden-corpus case."""
    case_id = str(case["id"])
    targets = case.get("targets", [])
    if target not in targets:
        raise ValueError(f"Golden case {case_id!r} does not generate a {target!r} artifact")

    case_dir = Path(workspace).resolve() / "artifacts" / safe_name(case_id)
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)
    result = run_case(dict(case), case_dir / "case")
    export = run_export(
        result["course"],
        target,
        result["parsed"].get("extracted_path"),
        case_id,
        case_dir / "export",
    )

    suffix = ".mbz" if target == "moodle" else ".tar.gz"
    artifact_path = case_dir / f"{safe_name(case_id)}{suffix}"
    shutil.copy2(export["archive"], artifact_path)
    return BuiltArtifact(
        case_id=case_id,
        target=target,
        path=artifact_path,
        sha256=_file_digest(artifact_path),
        size_bytes=artifact_path.stat().st_size,
    )
