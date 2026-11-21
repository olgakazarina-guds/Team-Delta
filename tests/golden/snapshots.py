"""Snapshot normalization and comparison helpers for the golden corpus."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import xml.etree.ElementTree as ET  # nosec B405 - generated output only
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from core.report import build_report_data
from domain.entities import Course

SNAPSHOT_VERSION = 1

VOLATILE_PATHS = frozenset(
    {
        "activity/*/timemodified",
        "activity/scorm/version",
        "course/startdate",
        "course/timecreated",
        "course/timemodified",
        "files/file/timecreated",
        "files/file/timemodified",
        "module/added",
        "moodle_backup/information/backup_date",
        "moodle_backup/information/original_course_startdate",
        "question_categories/question_category/questions/question/stamp",
        "question_categories/question_category/questions/question/timecreated",
        "question_categories/question_category/questions/question/timemodified",
        "question_categories/question_category/questions/question/version",
        "question_categories/question_category/question_bank_entries/question_bank_entry/"
        "question_version/question_versions/questions/question/stamp",
        "question_categories/question_category/question_bank_entries/question_bank_entry/"
        "question_version/question_versions/questions/question/timecreated",
        "question_categories/question_category/question_bank_entries/question_bank_entry/"
        "question_version/question_versions/questions/question/timemodified",
        "question_categories/question_category/stamp",
        "section/timemodified",
    }
)
VOLATILE_ATTRIBUTES = frozenset({"backup_id"})

UUID_PATTERN = re.compile(
    r"(?<![0-9a-fA-F])(?:"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[0-9a-fA-F]{32}"
    r"|[0-9a-fA-F]{8}"
    r")(?![0-9a-fA-F])"
)


def json_text(value: Any) -> str:
    """Return deterministic JSON with a trailing newline."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(value), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_json_snapshot(actual: Any, expected_path: Path) -> None:
    """Compare ``actual`` with a committed snapshot and show a readable diff."""
    if not expected_path.is_file():
        raise AssertionError(
            f"Missing golden snapshot: {expected_path}. "
            "Run `uv run python scripts/update_golden.py --write`."
        )

    expected = load_json(expected_path)
    if actual == expected:
        return

    diff = "\n".join(
        difflib.unified_diff(
            json_text(expected).splitlines(),
            json_text(actual).splitlines(),
            fromfile=str(expected_path),
            tofile="actual",
            lineterm="",
        )
    )
    raise AssertionError(
        f"Golden snapshot mismatch: {expected_path}\n"
        f"Run `uv run python scripts/update_golden.py --write --case <id>` after review.\n"
        f"{diff}"
    )


def _normalize_text(value: str, ids: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token not in ids:
            ids[token] = f"<id:{len(ids) + 1}>"
        return ids[token]

    return UUID_PATTERN.sub(replace, value)


def _normalize_json(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _normalize_text(value, ids)
    if isinstance(value, list):
        return [_normalize_json(item, ids) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json(item, ids) for key, item in value.items()}
    return value


def _element_to_obj(
    element: ET.Element,
    ids: dict[str, str],
    parent_path: str = "",
) -> dict[str, Any]:
    element_path = f"{parent_path}/{element.tag}" if parent_path else element.tag
    result: dict[str, Any] = {"tag": element.tag}

    attributes = {
        key: _normalize_text(value, ids)
        for key, value in element.attrib.items()
        if key not in VOLATILE_ATTRIBUTES
    }
    if attributes:
        result["attributes"] = attributes

    text = _normalize_text((element.text or "").strip(), ids)
    if text:
        result["text"] = text

    children = [
        _element_to_obj(child, ids, element_path)
        for child in element
        if not any(
            fnmatchcase(f"{element_path}/{child.tag}", pattern) for pattern in VOLATILE_PATHS
        )
    ]
    if children:
        result["children"] = children

    return result


def _normalize_archive_index(text: str, ids: dict[str, str]) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            parts[0] = _normalize_text(parts[0], ids)
            parts[-1] = "<mtime>"
            lines.append("\t".join(parts))
        else:
            lines.append(_normalize_text(line, ids))
    return "\n".join(lines)


def snapshot_course(course: Course, case: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized canonical course snapshot for one case."""
    data = course.model_dump(mode="json")
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("job_id", None)
        metadata.pop("extracted_path", None)

    for fragment in data.get("raw_fragments", []):
        location = fragment.get("source_location")
        if isinstance(location, dict):
            location.pop("file_path", None)
        fragment.pop("raw_text", None)
        fragment.pop("raw_bytes_ref", None)

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "case_id": case["id"],
        "source": case["source"],
        "course": data,
    }


def snapshot_report(
    course: Course,
    report: list[Any],
    case: dict[str, Any],
    target: str | None,
) -> dict[str, Any]:
    """Return the normalized validation report snapshot for one case."""
    job = {
        "status": "validated",
        "created_at": "1970-01-01T00:00:00Z",
        "updated_at": "1970-01-01T00:00:00Z",
        "source_type": course.source_system.value,
        "target_type": target,
        "output_path": None,
        "error": None,
    }
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "case_id": case["id"],
        "target": target,
        "report": build_report_data("golden", job, course, report),
    }


def snapshot_export_tree(
    root: Path,
    case_id: str,
    target: str,
) -> dict[str, Any]:
    """Snapshot an extracted target export without timestamps or random IDs."""
    files: list[dict[str, Any]] = []
    contents: dict[str, Any] = {}
    ids: dict[str, str] = {}

    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix()
        normalized_path = _normalize_text(relative, ids)
        size = path.stat().st_size
        suffix = path.suffix.lower()

        if suffix == ".xml":
            kind = "xml"
            value: Any = _element_to_obj(ET.parse(path).getroot(), ids)
        elif suffix == ".json":
            kind = "json"
            value = _normalize_json(json.loads(path.read_text(encoding="utf-8")), ids)
        elif path.name == ".ARCHIVE_INDEX":
            kind = "archive_index"
            value = _normalize_archive_index(path.read_text(encoding="utf-8"), ids)
        elif suffix in {".html", ".txt", ".log"}:
            kind = "text"
            value = _normalize_text(path.read_text(encoding="utf-8"), ids)
        else:
            kind = "binary"
            value = None

        entry: dict[str, Any] = {"path": normalized_path, "size": size, "kind": kind}
        if kind == "binary":
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(entry)

        if value is not None:
            if normalized_path in contents:
                raise AssertionError(f"Normalized export path collision: {normalized_path}")
            contents[normalized_path] = value

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "case_id": case_id,
        "target": target,
        "files": files,
        "contents": contents,
    }
