"""
Course Inspector CLI – Inspect course packages and validate migration readiness.

Supports:
- Moodle (.mbz) course backups
- Open edX (.tar.gz) course exports

Commands show course structure, transformation notes, and migration validation.
"""

import json
from pathlib import Path
from typing import Any, Dict

import typer

from core.ingest import IngestService


def inspect_command(
    path: str = typer.Argument(
        ..., help="Path to course file (.mbz for Moodle, .tar.gz for Open edX)"
    ),
    source: str = typer.Option(
        None, "--source", "-s", help="Source LMS: 'moodle' or 'openedx' (auto-detected)"
    ),
    show_source: bool = typer.Option(
        False, "--show-source", help="Show original course structure (before transformation)"
    ),
    validate_for: str = typer.Option(
        None, "--validate-for", "-v", help="Validate for migration to target LMS"
    ),
    output: str = typer.Option(
        None, "--output", "-o", help="Save detailed report as JSON file"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-d", help="Show everything"
    ),
) -> None:
    """
    Inspect a course and show its structure, warnings, and migration readiness.
    """
    # Validate input file exists
    if not Path(path).exists():
        typer.echo(f"Error: File {path} not found", err=True)
        raise typer.Exit(1)

    # Auto-detect source LMS if not provided
    if not source:
        source = _detect_source(path)

    typer.echo(f"Inspecting {source.title()} course from {path}...")

    # Run inspection
    service = IngestService()
    try:
        result = service.inspect(path, source_type=source, work_dir="data/extracted")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    course = result["course"]
    parsed = result.get("parsed", {})

    # Print course summary
    _print_course_summary(course, result)

    # Show original structure if requested
    if show_source or verbose:
        _print_original_structure(parsed, source)

    # Show transformed structure if verbose or validating
    if verbose or validate_for:
        _print_transformed_structure(course, validate_for)

    # Show validation notes
    _print_validation_notes(result, validate_for)

    # Save output to file if requested
    if output:
        _save_output(result, output)


def _detect_source(path: str) -> str:
    """
    Auto-detect source LMS from file extension.

    Args:
        path: Path to course file

    Returns:
        Source system: 'moodle' or 'openedx'

    Raises:
        typer.Exit: If extension is not recognized
    """
    if path.endswith(".mbz"):
        return "moodle"
    if path.endswith(".tar.gz"):
        return "openedx"

    typer.echo("Error: Could not auto-detect source LMS. Use --source", err=True)
    raise typer.Exit(1)


def _print_course_summary(course: Any, result: Dict[str, Any]) -> None:
    """Print course summary statistics."""
    typer.echo("\n[ Course Summary ]")
    typer.echo(f"Course Title: {course.title}")

    source_system = (
        course.source_system.value
        if hasattr(course.source_system, "value")
        else course.source_system
    )
    typer.echo(f"Source System: {source_system}")

    typer.echo(f"Content Nodes: {len(course.content_nodes)}")
    typer.echo(f"Assessments: {len(course.assessments)}")
    typer.echo(f"Questions: {len(course.questions)}")
    typer.echo(f"Raw Fragments: {result['raw_fragments_count']}")


def _print_original_structure(parsed: Dict[str, Any], source: str) -> None:
    """Print original course structure before transformation."""
    typer.echo(f"\n[ Original Structure ({source.title()}) ]")

    if source == "moodle":
        _print_moodle_raw_structure(parsed)
    elif source == "openedx":
        _print_openedx_raw_structure(parsed)


def _print_moodle_raw_structure(parsed: Dict[str, Any]) -> None:
    """Print Moodle course raw structure (sections, activities, or chapters)."""
    sections = parsed.get("sections", [])
    activities = parsed.get("activities", [])
    chapters = parsed.get("chapters", [])

    if sections:
        for idx, section in enumerate(sections):
            section_title = section.get("title", f"Section {idx}")
            typer.echo(f"- Section {idx}: {section_title}")

            for act in section.get("activities", [])[:10]:
                module = act.get("module_name", "unknown")
                title = act.get("title", "Untitled")
                typer.echo(f"    - {module}: {title}")
    elif activities:
        typer.echo("  (Flat structure - no sections)")
        for act in activities[:15]:
            module = act.get("module_name", "unknown")
            title = act.get("title", "Untitled")
            typer.echo(f"  - {module}: {title}")
    elif chapters:
        typer.echo("Note: Showing transformed structure (Moodle sections were converted)")
        for chapter in chapters[:5]:
            chapter_title = chapter.get("title", "Untitled Chapter")
            typer.echo(f"- Chapter: {chapter_title}")

            for seq in chapter.get("sequentials", [])[:3]:
                seq_title = seq.get("title", "Untitled Sequential")
                typer.echo(f"    - Sequential: {seq_title}")
    else:
        typer.echo("  No sections, activities, or chapters found")


def _print_openedx_raw_structure(parsed: Dict[str, Any]) -> None:
    """Print Open edX course raw structure (chapters → sequentials → verticals)."""
    chapters = parsed.get("chapters", [])

    for chapter in chapters[:5]:
        chapter_title = chapter.get("title", "Untitled Chapter")
        typer.echo(f"- Chapter: {chapter_title}")

        for seq in chapter.get("sequentials", [])[:3]:
            seq_title = seq.get("title", "Untitled Sequential")
            typer.echo(f"    - Sequential: {seq_title}")

            for vert in seq.get("verticals", [])[:3]:
                vert_title = vert.get("title", "Untitled Vertical")
                typer.echo(f"        - Vertical: {vert_title}")

    if not chapters:
        typer.echo("  No chapters found")


def _print_transformed_structure(course: Any, validate_for: str) -> None:
    """Print transformed course structure (canonical model)."""
    target_display = validate_for if validate_for else "canonical model"
    typer.echo(f"\n[ Transformed Structure (Target: {target_display}) ]")

    for node in course.content_nodes:
        _print_node_tree(node, indent=0)


def _print_node_tree(node: Any, indent: int = 0) -> None:
    """Recursively print content node tree with indentation."""
    prefix = "  " * indent
    node_type = (
        node.node_type.value if hasattr(node.node_type, "value") else node.node_type
    )
    title = node.title or "Untitled"
    typer.echo(f"{prefix}- {node_type}: {title}")

    for child in node.children:
        _print_node_tree(child, indent + 1)


def _print_validation_notes(result: Dict[str, Any], validate_for: str) -> None:
    """Print validation notes and migration readiness status."""
    notes = result.get("report", [])

    if not notes:
        typer.echo("\nNo validation issues found.")
        return

    if validate_for:
        _print_validation_for_migration(notes, validate_for)
    else:
        _print_validation_notes_only(notes)


def _print_validation_for_migration(notes: List[Any], validate_for: str) -> None:
    """Print validation notes with migration readiness summary."""
    typer.echo(f"\n[ Validation for {validate_for.title()} Migration ]")

    error_count = sum(
        1
        for n in notes
        if (n.severity.value if hasattr(n.severity, "value") else n.severity) == "error"
    )
    warning_count = sum(
        1
        for n in notes
        if (n.severity.value if hasattr(n.severity, "value") else n.severity)
        == "warning"
    )

    typer.echo(f"Errors: {error_count}, Warnings: {warning_count}")

    for note in notes:
        severity = (
            note.severity.value if hasattr(note.severity, "value") else str(note.severity)
        )
        typer.echo(f"  [{severity}] {note.code}: {note.message}")

    # Print migration readiness summary
    if error_count > 0:
        typer.echo(f"\nMigration to {validate_for} will fail due to errors above.")
    elif warning_count > 0:
        typer.echo(
            f"\nMigration to {validate_for} will work, but review {warning_count} warning(s)."
        )
    else:
        typer.echo(f"\nMigration to {validate_for} should work flawlessly.")


def _print_validation_notes_only(notes: List[Any]) -> None:
    """Print validation notes without migration summary."""
    typer.echo("\n[ Validation Notes ]")

    for note in notes:
        severity = (
            note.severity.value if hasattr(note.severity, "value") else str(note.severity)
        )
        typer.echo(f"  [{severity}] {note.code}: {note.message}")


def _save_output(result: Dict[str, Any], output_path: str) -> None:
    """Save inspection result as JSON file."""
    output_data = _make_serializable(result)

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    typer.echo(f"\nReport saved to {output_path}")


def _make_serializable(obj: Any) -> Any:
    """
    Convert objects to JSON-serializable format.

    Handles:
    - Pydantic models (model_dump())
    - Old dataclasses (dict())
    - Enums (value)
    - Lists and dicts
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "value"):
        return obj.value
    if isinstance(obj, list):
        return [_make_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    return obj
