import typer
import json
from pathlib import Path
from core.ingest import IngestService

def inspect_command(
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

    # Print summary
    course = result["course"]  # this is a dict from course.dict()
    typer.echo(f"\nCourse Title: {course['title']}")
    typer.echo(f"Source System: {course['source_system']}")
    typer.echo(f"Raw Fragments: {result['raw_fragments_count']}")

    # Print structure tree (only if verbose)
    if verbose:
        typer.echo("\nCourse Structure:")
        for node in course.get("content_nodes", []):
            _print_node_tree(node, indent=0)

    # Print validation notes (MappingNote objects)
    notes = result.get("report", [])
    if notes:
        typer.echo("\nValidation Warnings/Errors:")
        for note in notes:
            # note is a MappingNote object (Pydantic model)
            severity = note.severity.value if hasattr(note.severity, 'value') else str(note.severity)
            typer.echo(f"  [{severity}] {note.code}: {note.message}")
    else:
        typer.echo("\nNo validation issues found.")

    if output:
        # Convert result to JSON-serializable (MappingNote objects to dict)
        output_data = _make_serializable(result)
        with open(output, "w") as f:
            json.dump(output_data, f, indent=2)
        typer.echo(f"\nReport saved to {output}")

def _print_node_tree(node, indent=0):
    prefix = "  " * indent
    node_type = node.get("node_type", "unknown")
    title = node.get("title", "Untitled")
    typer.echo(f"{prefix}- {node_type}: {title}")
    for child in node.get("children", []):
        _print_node_tree(child, indent + 1)

def _make_serializable(obj):
    """Convert Pydantic models and enums to JSON-serializable types."""
    if hasattr(obj, "dict"):
        return obj.dict()
    elif hasattr(obj, "value"):
        return obj.value
    elif isinstance(obj, list):
        return [_make_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    else:
        return obj
