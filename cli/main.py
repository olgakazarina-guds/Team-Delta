import typer
import json
from pathlib import Path
from core.ingest import IngestService

app = typer.Typer(help="LMS Converter - Migrate courses between Open edX and Moodle")

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

    # Print summary
    course = result["course"]
    typer.echo(f"\nCourse Title: {course['title']}")
    typer.echo(f"Source System: {course['source_system']}")
    typer.echo(f"Raw Fragments: {result['raw_fragments_count']}")

    # Print structure tree (only if verbose)
    if verbose:
        typer.echo("\nCourse Structure:")
        for node in course.get("content_nodes", []):
            _print_node_tree(node, indent=0)

    # Print validation notes
    notes = result.get("report", [])
    if notes:
        typer.echo("\nValidation Warnings/Errors:")
        for note in notes:
            typer.echo(f"  [{note.severity}] {note.code}: {note.message}")
    else:
        typer.echo("\nNo validation issues found.")

    if output:
        with open(output, "w") as f:
            json.dump(result, f, indent=2)
        typer.echo(f"\nReport saved to {output}")

def _print_node_tree(node, indent=0):
    prefix = "  " * indent
    typer.echo(f"{prefix}- {node['node_type']}: {node['title'] or 'Untitled'}")
    for child in node.get("children", []):
        _print_node_tree(child, indent + 1)

if __name__ == "__main__":
    app()
