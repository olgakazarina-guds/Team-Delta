"""
Course Migration CLI - Migrate courses between Moodle and Open edX.

Supports:
- Moodle (.mbz) → Open edX (.tar.gz)
- Open edX (.tar.gz) → Moodle (.mbz)

Validates migration readiness before conversion and shows detailed progress.
"""

from pathlib import Path
from typing import List

import typer

from core.ingest import IngestService
from core.migrate import MigrationService


def migrate_command(
    source_path: str = typer.Argument(..., help="Path to source course file"),
    source: str = typer.Option(
        None, "--source", "-s", help="Source LMS: 'moodle' or 'openedx' (auto-detected)"
    ),
    target: str = typer.Option(
        "openedx", "--target", "-t", help="Target LMS: 'openedx' or 'moodle'"
    ),
    output: str = typer.Option(
        "export.tar.gz", "--output", "-o", help="Output file path"
    ),
    detailed: bool = typer.Option(
        False, "--detailed", "-d", help="Show detailed progress"
    ),
) -> None:
    """
    Migrate a course from source LMS to target LMS.
    """
    # Auto-detect source LMS if not provided
    if not source:
        source = _detect_source(source_path)

    # Validate input file exists
    if not Path(source_path).exists():
        typer.echo(f"Error: File {source_path} not found", err=True)
        raise typer.Exit(1)

    # Inspect source course
    typer.echo(f"Inspecting {source.title()} course from {source_path}...")
    ingest = IngestService()
    try:
        result = ingest.inspect(source_path, source_type=source, work_dir="data/extracted")
    except Exception as e:
        typer.echo(f"Inspection failed: {e}", err=True)
        raise typer.Exit(1)

    course = result["course"]

    # Print source course summary
    _print_course_summary(course, result)

    # Show detailed structure if requested
    if detailed:
        typer.echo("\nTransformed Course Structure:")
        for node in course.content_nodes:
            _print_node_tree(node, indent=0)

    # Validate migration readiness
    notes = result.get("report", [])
    _validate_migration(notes)

    # Perform migration
    _perform_migration(course, target, output, result)

    # Print migration summary
    _print_migration_summary(course, notes)


def _detect_source(source_path: str) -> str:
    """
    Auto-detect source LMS from file extension.

    Args:
        source_path: Path to source course file

    Returns:
        Source system: 'moodle' or 'openedx'

    Raises:
        typer.Exit: If extension is not recognized
    """
    if source_path.endswith(".mbz"):
        return "moodle"
    if source_path.endswith(".tar.gz"):
        return "openedx"

    typer.echo("Error: Could not auto-detect source LMS. Use --source", err=True)
    raise typer.Exit(1)


def _print_course_summary(course: Any, result: dict) -> None:
    """Print source course summary statistics."""
    typer.echo("\n[ Source Course Summary ]")
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
    typer.echo(f"Answer Options: {len(course.answer_options)}")
    typer.echo(f"Assets: {len(course.assets)}")
    typer.echo(f"Raw Fragments: {result['raw_fragments_count']}")


def _validate_migration(notes: List[Any]) -> None:
    """
    Print validation notes and abort if errors exist.

    Args:
        notes: List of validation notes from inspection

    Raises:
        typer.Exit: If errors are found
    """
    if not notes:
        typer.echo("\nNo validation issues found.")
        return

    typer.echo("\n[ Validation Warnings/Errors ]")

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

    if error_count > 0:
        typer.echo("\nAborting migration due to errors.")
        raise typer.Exit(1)


def _perform_migration(course: Any, target: str, output: str, result: dict) -> None:
    """
    Perform the actual migration to target LMS.

    Args:
        course: Canonical Course entity
        target: Target LMS ('openedx' or 'moodle')
        output: Output file path
        result: Inspection result containing extracted_path

    Raises:
        typer.Exit: If target is unsupported or migration fails
    """
    typer.echo(f"\n[ Migrating to {target.title()} ]")
    migrator = MigrationService()

    try:
        if target == "openedx":
            typer.echo("Converting to Open edX format...")
            output_path = migrator.migrate_to_openedx(
                course, output, source_extracted_path=result.get("extracted_path")
            )
        elif target == "moodle":
            typer.echo("Converting to Moodle format...")
            output_path = migrator.migrate_to_moodle(
                course, output, source_extracted_path=result.get("extracted_path")
            )
        else:
            typer.echo(f"Unsupported target: {target}", err=True)
            raise typer.Exit(1)

        typer.echo("Migration complete!")
    except Exception as e:
        typer.echo(f"Migration failed: {e}", err=True)
        raise typer.Exit(1)


def _print_migration_summary(course: Any, notes: List[Any]) -> None:
    """Print migration summary with content statistics."""
    typer.echo("\n[ Migration Summary ]")
    typer.echo(f"Output File: {output_path}")
    typer.echo(f"Course Title: {course.title}")

    typer.echo("\nMigrated Content:")
    typer.echo(
        f"  - Chapters: {sum(1 for n in course.content_nodes if n.node_type.value == 'chapter')}"
    )
    typer.echo(
        f"  - Sequentials: {sum(1 for n in course.content_nodes if n.node_type.value == 'sequential')}"
    )
    typer.echo(
        f"  - Verticals: {sum(1 for n in course.content_nodes if n.node_type.value == 'vertical')}"
    )
    typer.echo(
        f"  - HTML Components: {sum(1 for n in course.content_nodes if n.node_type.value == 'html')}"
    )
    typer.echo(
        f"  - Problem Components: {sum(1 for n in course.content_nodes if n.node_type.value == 'problem')}"
    )
    typer.echo(
        f"  - Video Components: {sum(1 for n in course.content_nodes if n.node_type.value == 'video')}"
    )
    typer.echo(f"  - Assessments: {len(course.assessments)}")
    typer.echo(f"  - Questions: {len(course.questions)}")
    typer.echo(f"  - Assets: {len(course.assets)}")

    if notes:
        typer.echo(f"\nValidation Notes: {len(notes)} warnings/errors (see above)")

    typer.echo(f"\nMigration successful! Output saved to: {output_path}")


def _print_node_tree(node: Any, indent: int = 0) -> None:
    """
    Recursively print content node tree with indentation.

    Args:
        node: ContentNode entity
        indent: Current indentation level
    """
    prefix = "  " * indent
    node_type = (
        node.node_type.value if hasattr(node.node_type, "value") else node.node_type
    )
    title = node.title or "Untitled"
    typer.echo(f"{prefix}- {node_type}: {title}")

    for child in node.children:
        _print_node_tree(child, indent + 1)
