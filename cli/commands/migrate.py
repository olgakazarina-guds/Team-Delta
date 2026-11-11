"""
Course Migration CLI – Migrate courses between Moodle and Open edX.

Supports:
- Moodle (.mbz) -> Open edX (.tar.gz)
- Open edX (.tar.gz) -> Moodle (.mbz)

Validates migration readiness before conversion and shows detailed progress.
"""

import logging
from pathlib import Path
from typing import List, Any

import typer

from core.ingest import IngestService
from core.migrate import MigrationService
from core.logging_conf import setup_logging
from core.process_report import ProcessReporter

logger = logging.getLogger(__name__)


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
    log_level: str = typer.Option(
        "INFO", "--log-level", "-l", help="Console log level: DEBUG, INFO, WARNING, ERROR"
    ),
    log_file: str = typer.Option(
        None, "--log-file", help="Also write a full DEBUG log to this file"
    ),
    report: bool = typer.Option(
        False, "--report", "-r", help="Print a per-step success/failure report at the end"
    ),
) -> None:
    """
    Migrate a course from source LMS to target LMS.
    """
    setup_logging(log_level, log_file)

    # --- Pre-flight checks (not pipeline steps) ---
    target = target.strip().lower()
    if not source:
        source = _detect_source(source_path)
        logger.info("Auto-detected source LMS: %s", source)

    if not Path(source_path).exists():
        logger.error("Input file not found: %s", source_path)
        typer.echo(f"Error: File {source_path} not found", err=True)
        raise typer.Exit(1)

    reporter = ProcessReporter(f"Migrate {source} -> {target}")
    logger.info("migrate: %s (%s) -> %s (%s)", source_path, source, output, target)

    ingest = IngestService()
    course = None
    notes: List[Any] = []
    output_path = output
    failed = False
    try:
        # 1. Inspect source course
        typer.echo(f"Inspecting {source.title()} course from {source_path}...")
        with reporter.step("Inspect source course"):
            result = ingest.inspect(
                source_path,
                source_type=source,
                target_type=target,
            )

        course = result["course"]
        _print_course_summary(course, result)

        if detailed:
            typer.echo("\nTransformed Course Structure:")
            for node in course.content_nodes:
                _print_node_tree(node, indent=0)

        # 2. Validate migration readiness (raises typer.Exit on errors)
        notes = result.get("report", [])
        with reporter.step("Validate migration readiness"):
            _validate_migration(notes)

        # 3. Perform migration
        with reporter.step(f"Migrate to {target}"):
            output_path = _perform_migration(course, target, output, result)
    except typer.Exit:
        # Helper already printed a specific message; just mark the run failed.
        failed = True
    except Exception as e:
        failed = True
        logger.exception("Migration failed")
        typer.echo(f"Error: {e}", err=True)
    finally:
        if report:
            reporter.render()

    if failed:
        raise typer.Exit(1)

    # Print migration summary
    _print_migration_summary(course, notes, output_path, result)
    typer.echo(f"Job ID: {result['job_id']}")


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
    lowered = source_path.lower()
    if lowered.endswith(".mbz"):
        return "moodle"
    if lowered.endswith((".tar.gz", ".tgz")):
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


def _perform_migration(course: Any, target: str, output: str, result: dict) -> str:
    """
    Perform the actual migration to target LMS and return the output path.

    Returns:
        Path to the output file

    Returns:
        The path the converted archive was written to.

    Raises:
        typer.Exit: If target is unsupported or migration fails
    """
    typer.echo(f"\n[ Migrating to {target.title()} ]")
    logger.info("Migrating course '%s' to %s -> %s", course.title, target, output)
    migrator = MigrationService()

    try:
        if target == "openedx":
            typer.echo("Converting to Open edX format...")
            output_path = migrator.migrate_to_openedx(
                course,
                output,
                source_extracted_path=result.get("extracted_path"),
                job_id=result.get("job_id"),
                report=result.get("report", []),
            )
        elif target == "moodle":
            typer.echo("Converting to Moodle format...")
            output_path = migrator.migrate_to_moodle(
                course,
                output,
                source_extracted_path=result.get("extracted_path"),
                job_id=result.get("job_id"),
                report=result.get("report", []),
            )
        else:
            logger.error("Unsupported target: %s", target)
            typer.echo(f"Unsupported target: {target}", err=True)
            raise typer.Exit(1)

        typer.echo("Migration complete!")
        logger.debug("Migration wrote: %s", output_path)
        return output_path
    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Migration conversion failed")
        typer.echo(f"Migration failed: {e}", err=True)
        raise typer.Exit(1)


def _print_migration_summary(course: Any, notes: List[Any], output_path: str, result: dict) -> None:
    """Print migration summary with content statistics."""
    def count_node_type(nodes, target_type):
        count = 0
        for node in nodes:
            if node.node_type.value == target_type:
                count += 1
            count += count_node_type(node.children, target_type)
        return count

    typer.echo("\n[ Migration Summary ]")
    typer.echo(f"Output File: {output_path}")
    typer.echo(f"Course Title: {course.title}")

    typer.echo("\nMigrated Content:")
    typer.echo(f"  - Chapters: {count_node_type(course.content_nodes, 'chapter')}")
    typer.echo(f"  - Sequentials: {count_node_type(course.content_nodes, 'sequential')}")
    typer.echo(f"  - Verticals: {count_node_type(course.content_nodes, 'vertical')}")
    typer.echo(f"  - HTML Components: {count_node_type(course.content_nodes, 'html')}")
    typer.echo(f"  - Problem Components: {count_node_type(course.content_nodes, 'problem')}")
    typer.echo(f"  - Video Components: {count_node_type(course.content_nodes, 'video')}")
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
