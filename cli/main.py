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
    path: str = typer.Argument(..., help="Path to course file (.mbz for Moodle, .tar.gz for Open edX)"),
    source: str = typer.Option(None, "--source", "-s", help="Source LMS: 'moodle' or 'openedx' (auto-detected from file extension)"),
    show_source: bool = typer.Option(False, "--show-source", help="Show original course structure (before transformation)"),
    validate_for: str = typer.Option(None, "--validate-for", "-v", help="Validate for migration to target LMS: 'openedx' or 'moodle'"),
    output: str = typer.Option(None, "--output", "-o", help="Save detailed report as JSON file"),
    verbose: bool = typer.Option(False, "--verbose", "-d", help="Show everything: source structure + transformed structure + validation"),
):
    """Inspect a course and show its structure, warnings, and migration readiness.
    
    Examples:
      [ See Moodle course structure (sections -> activities) ]
        lms-converter inspect course.mbz --show-source
      
      [ Check if course can be migrated to Open edX ]
        lms-converter inspect course.mbz --validate-for openedx
      
      [ Show everything ]
        lms-converter inspect course.mbz --verbose
    """
    if not Path(path).exists():
        typer.echo(f"Error: File {path} not found", err=True)
        raise typer.Exit(1)

    # Auto-detect source from file extension if not specified
    if not source:
        if path.endswith(".mbz"):
            source = "moodle"
        elif path.endswith(".tar.gz"):
            source = "openedx"
        else:
            typer.echo("Error: Could not auto-detect source LMS. Use --source moodle or --source openedx", err=True)
            raise typer.Exit(1)

    typer.echo(f"Inspecting {source.title()} course from {path}...")
    service = IngestService()
    try:
        result = service.inspect(path, source_type=source, work_dir="data/extracted")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    course = result["course"]
    parsed = result.get("parsed", {})
    
    # Print summary
    typer.echo(f"\n[ Course Summary ]")
    typer.echo(f"Course Title: {course.title}")
    typer.echo(f"Source System: {course.source_system.value if hasattr(course.source_system, 'value') else course.source_system}")
    typer.echo(f"Content Nodes: {len(course.content_nodes)}")
    typer.echo(f"Assessments: {len(course.assessments)}")
    typer.echo(f"Questions: {len(course.questions)}")
    typer.echo(f"Raw Fragments: {result['raw_fragments_count']}")

    # Show raw source structure if --show-source or --detailed
    if show_source or verbose:
        typer.echo(f"\n[ Original Structure ({source.title()}) ]")
        _print_raw_structure(parsed, source)

    # Show transformed (canonical) structure if --detailed or --validate-for
    if verbose or validate_for:
        target_display = validate_for if validate_for else "canonical model"
        typer.echo(f"\n[ Transformed Structure (Target: {target_display}) ]")
        for node in course.content_nodes:
            _print_node_tree(node, indent=0)

    # Print validation notes
    notes = result.get("report", [])
    if validate_for and notes:
        typer.echo(f"\n[ Validation for {validate_for.title()} Migration ]")
        error_count = sum(1 for n in notes if (n.severity.value if hasattr(n.severity, 'value') else n.severity) == "error")
        warning_count = sum(1 for n in notes if (n.severity.value if hasattr(n.severity, 'value') else n.severity) == "warning")
        typer.echo(f"Errors: {error_count}, Warnings: {warning_count}")
        
        for note in notes:
            severity = note.severity.value if hasattr(note.severity, 'value') else str(note.severity)
            typer.echo(f"  [{severity}] {note.code}: {note.message}")
        
        if error_count > 0:
            typer.echo(f"\nMigration to {validate_for} will fail due to errors above.")
        elif warning_count > 0:
            typer.echo(f"\nMigration to {validate_for} will work, but review {warning_count} warning(s).")
        else:
            typer.echo(f"\nMigration to {validate_for} should work flawlessly.")
    elif not validate_for and notes:
        typer.echo(f"\n[ Validation Notes ]")
        for note in notes:
            severity = note.severity.value if hasattr(note.severity, 'value') else str(note.severity)
            typer.echo(f"  [{severity}] {note.code}: {note.message}")
    elif not notes:
        typer.echo(f"\nNo validation issues found.")

    if output:
        output_data = _make_serializable(result)
        with open(output, "w") as f:
            json.dump(output_data, f, indent=2)
        typer.echo(f"\nReport saved to {output}")

@app.command()
def migrate(
    source_path: str = typer.Argument(..., help="Path to source course file"),
    source: str = typer.Option(None, "--source", "-s", help="Source LMS: 'moodle' or 'openedx' (auto-detected from file extension)"),
    target: str = typer.Option("openedx", "--target", "-t", help="Target LMS: 'openedx' or 'moodle'"),
    output: str = typer.Option("export.tar.gz", "--output", "-o", help="Output file path"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed progress"),
):
    """Migrate a course from source LMS to target LMS.
    
    Examples:
      [ Migrate Moodle to Open edX ]
        lms-converter migrate course.mbz --source moodle --target openedx
      
      [ Migrate Open edX to Moodle ]
        lms-converter migrate course.tar.gz --source openedx --target moodle
    """
    # Auto-detect source from file extension if not specified
    if not source:
        if source_path.endswith(".mbz"):
            source = "moodle"
        elif source_path.endswith(".tar.gz"):
            source = "openedx"
        else:
            typer.echo("Error: Could not auto-detect source LMS. Use --source moodle or --source openedx", err=True)
            raise typer.Exit(1)

    if not Path(source_path).exists():
        typer.echo(f"Error: File {source_path} not found", err=True)
        raise typer.Exit(1)

    typer.echo(f"Inspecting {source.title()} course from {source_path}...")
    ingest = IngestService()
    try:
        result = ingest.inspect(source_path, source_type=source, work_dir="data/extracted")
    except Exception as e:
        typer.echo(f"Inspection failed: {e}", err=True)
        raise typer.Exit(1)

    course = result["course"]
    
    typer.echo(f"\n[ Source Course Summary ]")
    typer.echo(f"Course Title: {course.title}")
    typer.echo(f"Source System: {course.source_system.value if hasattr(course.source_system, 'value') else course.source_system}")
    typer.echo(f"Content Nodes: {len(course.content_nodes)}")
    typer.echo(f"Assessments: {len(course.assessments)}")
    typer.echo(f"Questions: {len(course.questions)}")
    typer.echo(f"Answer Options: {len(course.answer_options)}")
    typer.echo(f"Assets: {len(course.assets)}")
    typer.echo(f"Raw Fragments: {result['raw_fragments_count']}")

    if detailed:
        typer.echo("\nTransformed Course Structure:")
        for node in course.content_nodes:
            _print_node_tree(node, indent=0)

    notes = result.get("report", [])
    if notes:
        typer.echo("\n[ Validation Warnings/Errors ]")
        error_count = sum(1 for n in notes if (n.severity.value if hasattr(n.severity, 'value') else n.severity) == "error")
        warning_count = sum(1 for n in notes if (n.severity.value if hasattr(n.severity, 'value') else n.severity) == "warning")
        typer.echo(f"Errors: {error_count}, Warnings: {warning_count}")
        for note in notes:
            severity = note.severity.value if hasattr(note.severity, 'value') else str(note.severity)  # ← FIXED: note.severity, not n.severity
            typer.echo(f"  [{severity}] {note.code}: {note.message}")
        
        if error_count > 0:
            typer.echo("\nAborting migration due to errors. Fix the issues above and try again.")
            raise typer.Exit(1)
    else:
        typer.echo("\nNo validation issues found.")

    typer.echo(f"\n[ Migrating to {target.title()} ]")
    migrator = MigrationService()
    try:
        if target == "openedx":
            typer.echo("Converting to Open edX format...")
            output_path = migrator.migrate_to_openedx(course, output)
            typer.echo("Migration complete!")
        elif target == "moodle":
            raise NotImplementedError("Moodle target not yet implemented")
        else:
            typer.echo(f"Unsupported target LMS: {target}", err=True)
            raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Migration failed: {e}", err=True)
        raise typer.Exit(1)

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


def _print_raw_structure(parsed, source):
    """Print raw source structure (Moodle sections/activities or Open edX hierarchy)."""
    if source == "moodle":
        # Try different keys for Moodle data
        sections = parsed.get("sections", [])
        activities = parsed.get("activities", [])
        chapters = parsed.get("chapters", [])  # Check if already transformed
        
        if sections:
            # Moodle has sections (sections → activities)
            for idx, section in enumerate(sections):
                section_title = section.get("title", f"Section {idx}")
                typer.echo(f"- Section {idx}: {section_title}")
                
                sec_activities = section.get("activities", [])
                for act in sec_activities[:10]:
                    module = act.get("module_name", "unknown")
                    title = act.get("title", "Untitled")
                    typer.echo(f"    - {module}: {title}")
                
                if len(sec_activities) > 10:
                    typer.echo(f"    ... and {len(sec_activities) - 10} more activities")
        
        elif activities:
            # Moodle has flat activities (no sections)
            typer.echo("  (Flat structure - no sections)")
            for act in activities[:15]:
                module = act.get("module_name", "unknown")
                title = act.get("title", "Untitled")
                typer.echo(f"  - {module}: {title}")
            
            if len(activities) > 15:
                typer.echo(f"  ... and {len(activities) - 15} more activities")
        
        elif chapters:
            # Already transformed to chapters (fallback)
            typer.echo("Note: Showing transformed structure (Moodle sections were converted)")
            for chapter in chapters[:5]:
                chapter_title = chapter.get("title", "Untitled Chapter")
                typer.echo(f"- Chapter: {chapter_title}")
                
                for seq in chapter.get("sequentials", [])[:3]:
                    seq_title = seq.get("title", "Untitled Sequential")
                    typer.echo(f"    - Sequential: {seq_title}")
        
        else:
            typer.echo("  No sections, activities, or chapters found")
    
    elif source == "openedx":
        # Open edX: chapters → sequentials → verticals
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


def _print_node_tree(node, indent=0):
    """Print canonical (transformed) structure tree."""
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
