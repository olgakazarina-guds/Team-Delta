import typer
import json
from pathlib import Path
from core.ingest import IngestService
from core.migrate import MigrationService

app = typer.Typer(help="LMS Converter - Migrate courses between Open edX and Moodle")

@app.callback()
def main():
    """LMS Converter - Migrate courses between Open edX and Moodle"""
    pass

@app.command()
def inspect(
    path: str = typer.Argument(..., help="Path to course export (.tar.gz for Open edX, .mbz for Moodle)"),
    source: str = typer.Option("openedx", "--source", "-s", help="Source LMS: openedx or moodle"),
    output: str = typer.Option(None, "--output", "-o", help="Output JSON report file"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output")
):
    """Inspect a course export and show structure, raw fragments, and warnings."""
    if not Path(path).exists():
        typer.echo(f"Error: File {path} not found", err=True)
        raise typer.Exit(1)

    typer.echo(f"Inspecting {source} course from {path}...")
    service = IngestService()
    try:
        result = service.inspect(path, source_type=source, work_dir="data/extracted")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    # course is a Course object (Pydantic model)
    course = result["course"]
    
    # Print summary
    typer.echo(f"\nCourse Title: {course.title}")
    typer.echo(f"Source System: {course.source_system.value if hasattr(course.source_system, 'value') else course.source_system}")
    typer.echo(f"Content Nodes: {len(course.content_nodes)}")
    typer.echo(f"Assessments: {len(course.assessments)}")
    typer.echo(f"Questions: {len(course.questions)}")
    typer.echo(f"Raw Fragments: {result['raw_fragments_count']}")

    # Print structure tree (only if verbose)
    if verbose:
        typer.echo("\nCourse Structure:")
        for node in course.content_nodes:
            _print_node_tree(node, indent=0)

    # Print validation notes
    notes = result.get("report", [])
    if notes:
        typer.echo("\nValidation Warnings/Errors:")
        for note in notes:
            severity = note.severity.value if hasattr(note.severity, 'value') else str(note.severity)
            typer.echo(f"  [{severity}] {note.code}: {note.message}")
    else:
        typer.echo("\nNo validation issues found.")

    if output:
        # Convert Course object and other Pydantic models to dict for JSON
        output_data = _make_serializable(result)
        with open(output, "w") as f:
            json.dump(output_data, f, indent=2)
        typer.echo(f"\nReport saved to {output}")

@app.command()
def migrate(
    source_path: str = typer.Argument(..., help="Path to source course export"),
    source: str = typer.Option("moodle", "--source", "-s", help="Source LMS: moodle or openedx"),
    target: str = typer.Option("openedx", "--target", "-t", help="Target LMS: openedx or moodle"),
    output: str = typer.Option("export.tar.gz", "--output", "-o", help="Output file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """Migrate a course from source LMS to target LMS."""
    if not Path(source_path).exists():
        typer.echo(f"Error: File {source_path} not found", err=True)
        raise typer.Exit(1)

    typer.echo(f"Inspecting {source} course from {source_path}...")
    ingest = IngestService()
    try:
        result = ingest.inspect(source_path, source_type=source, work_dir="data/extracted")
    except Exception as e:
        typer.echo(f"Inspection failed: {e}", err=True)
        raise typer.Exit(1)

    course = result["course"]
    
    # Print summary
    typer.echo(f"\n[ Source Course Summary ]")
    typer.echo(f"Course Title: {course.title}")
    typer.echo(f"Source System: {course.source_system.value if hasattr(course.source_system, 'value') else course.source_system}")
    typer.echo(f"Content Nodes: {len(course.content_nodes)}")
    typer.echo(f"Assessments: {len(course.assessments)}")
    typer.echo(f"Questions: {len(course.questions)}")
    typer.echo(f"Answer Options: {len(course.answer_options)}")
    typer.echo(f"Assets: {len(course.assets)}")
    typer.echo(f"Raw Fragments: {result['raw_fragments_count']}")

    # Print structure tree (only if verbose)
    if verbose:
        typer.echo("\nCourse Structure:")
        for node in course.content_nodes:
            _print_node_tree(node, indent=0)

    # Print validation notes
    notes = result.get("report", [])
    if notes:
        typer.echo("\n[ Validation Warnings/Errors ]")
        error_count = sum(1 for n in notes if (n.severity.value if hasattr(n.severity, 'value') else n.severity) == "error")
        warning_count = sum(1 for n in notes if (n.severity.value if hasattr(n.severity, 'value') else n.severity) == "warning")
        typer.echo(f"Errors: {error_count}, Warnings: {warning_count}")
        for note in notes:
            severity = note.severity.value if hasattr(note.severity, 'value') else str(note.severity)
            typer.echo(f"  [{severity}] {note.code}: {note.message}")
        
        # Stop if there are errors
        if error_count > 0:
            typer.echo("\nAborting migration due to errors. Fix the issues above and try again.")
            raise typer.Exit(1)
    else:
        typer.echo("\nNo validation issues found.")

    typer.echo(f"\n=== Migrating to {target} ===")
    migrator = MigrationService()
    try:
        if target == "openedx":
            typer.echo("Converting to Open edX format...")
            output_path = migrator.migrate_to_openedx(course, output)
            typer.echo(f"Migration complete!")
        elif target == "moodle":
            raise NotImplementedError("Moodle target not yet implemented")
        else:
            typer.echo(f"Unsupported target LMS: {target}", err=True)
            raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Migration failed: {e}", err=True)
        raise typer.Exit(1)

    # Print migration summary
    typer.echo(f"\n[ Migration Summary ]")
    typer.echo(f"Output File: {output_path}")
    typer.echo(f"Course Title: {course.title}")
    
    typer.echo(f"\nMigrated Content:")
    typer.echo(f"  - Chapters: {sum(1 for n in course.content_nodes if n.node_type.value == 'chapter')}")
    typer.echo(f"  - Sequentials: {sum(1 for n in course.content_nodes if n.node_type.value == 'sequential')}")
    typer.echo(f"  - Verticals: {sum(1 for n in course.content_nodes if n.node_type.value == 'vertical')}")
    typer.echo(f"  - HTML Components: {sum(1 for n in course.content_nodes if n.node_type.value == 'html')}")
    typer.echo(f"  - Problem Components: {sum(1 for n in course.content_nodes if n.node_type.value == 'problem')}")
    typer.echo(f"  - Video Components: {sum(1 for n in course.content_nodes if n.node_type.value == 'video')}")
    typer.echo(f"  - Assessments: {len(course.assessments)}")
    typer.echo(f"  - Questions: {len(course.questions)}")
    typer.echo(f"  - Assets: {len(course.assets)}")
    
    if notes:
        typer.echo(f"\nValidation Notes: {len(notes)} warnings/errors (see above)")
    
    typer.echo(f"\nMigration successful! Output saved to: {output_path}")

def _print_node_tree(node, indent=0):
    prefix = "  " * indent
    node_type = node.node_type.value
    title = node.title or "Untitled"
    typer.echo(f"{prefix}- {node_type}: {title}")
    for child in node.children:
        _print_node_tree(child, indent + 1)

def _make_serializable(obj):
    """Convert Pydantic models and enums to JSON-serializable types."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    elif hasattr(obj, "dict"):
        return obj.dict()
    elif hasattr(obj, "value"):
        return obj.value
    elif isinstance(obj, list):
        return [_make_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    else:
        return obj

if __name__ == "__main__":
    app()
