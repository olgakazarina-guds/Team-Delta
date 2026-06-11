import json
import typer
from pathlib import Path
from datetime import datetime
from persistence.repositories import get_job
from domain.entities import Course, ContentNode
from domain.enums import NodeType

app = typer.Typer()

def _count_node_type(nodes, target_type):
    """Recursively count nodes of a given type."""
    count = 0
    for node in nodes:
        if node.node_type.value == target_type:
            count += 1
        count += _count_node_type(node.children, target_type)
    return count

def report_command(
    job_id: str = typer.Argument(..., help="Job ID from previous inspection or migration"),
    format: str = typer.Option("html", "--format", "-f", help="Output format: json or html"),
    output: str = typer.Option(None, "--output", "-o", help="Save report to file"),
):
    """Generate a detailed report for a previous job."""
    job = get_job(job_id)
    if not job:
        typer.echo(f"Error: Job {job_id} not found", err=True)
        raise typer.Exit(1)

    course = Course.model_validate_json(job["course_json"])
    report_items = json.loads(job["report_json"])

    # Count components
    chapters = _count_node_type(course.content_nodes, "chapter")
    sequentials = _count_node_type(course.content_nodes, "sequential")
    verticals = _count_node_type(course.content_nodes, "vertical")
    html_components = _count_node_type(course.content_nodes, "html")
    problem_components = _count_node_type(course.content_nodes, "problem")
    video_components = _count_node_type(course.content_nodes, "video")

    # Extract unsupported activity types from mapping notes
    unsupported_types = set()
    for note in report_items:
        if note.get("code") == "UNSUPPORTED_NODES":
            # note.message might contain the list
            unsupported_types.add(note.get("message", ""))
        elif note.get("code") == "UNSUPPORTED_QUESTION_TYPE":
            unsupported_types.add("question_type")

    if format == "json":
        report_data = {
            "job_id": job["job_id"],
            "source_type": job["source_type"],
            "target_type": job["target_type"],
            "created_at": job["created_at"],
            "course_title": course.title,
            "content_nodes": len(course.content_nodes),
            "assessments": len(course.assessments),
            "questions": len(course.questions),
            "components": {
                "chapters": chapters,
                "sequentials": sequentials,
                "verticals": verticals,
                "html": html_components,
                "problems": problem_components,
                "videos": video_components,
            },
            "assets": [{"id": a.asset_id, "path": a.path} for a in course.assets],
            "warnings": report_items,
        }
        output_json = json.dumps(report_data, indent=2)
        if output:
            Path(output).write_text(output_json)
            typer.echo(f"Report saved to {output}")
        else:
            typer.echo(output_json)
    else:  # html
        # Generate HTML with more details
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>LMS Converter Report - {job_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 2rem; }}
        h1, h2 {{ color: #2c3e50; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .warning {{ background-color: #fff3cd; }}
        .error {{ background-color: #f8d7da; }}
        .info {{ background-color: #d1ecf1; }}
        .summary {{ background-color: #e9ecef; }}
    </style>
</head>
<body>
    <h1>LMS Converter Report</h1>
    <p><strong>Job ID:</strong> {job_id}</p>
    <p><strong>Created:</strong> {job['created_at']}</p>
    <p><strong>Source LMS:</strong> {job['source_type']}</p>
    <p><strong>Target LMS:</strong> {job['target_type'] or 'N/A'}</p>
    <h2>Course Summary</h2>
    <table class="summary">
        <tr><th>Property</th><th>Value</th></tr>
        <tr><td>Title</td><td>{course.title}</td></tr>
        <tr><td>Content Nodes</td><td>{len(course.content_nodes)}</td></tr>
        <tr><td>Chapters</td><td>{chapters}</td></tr>
        <tr><td>Sequentials</td><td>{sequentials}</td></tr>
        <tr><td>Verticals</td><td>{verticals}</td></tr>
        <tr><td>HTML Components</td><td>{html_components}</td></tr>
        <tr><td>Problem Components</td><td>{problem_components}</td></tr>
        <tr><td>Video Components</td><td>{video_components}</td></tr>
        <tr><td>Assessments</td><td>{len(course.assessments)}</td></tr>
        <tr><td>Questions</td><td>{len(course.questions)}</td></tr>
        <tr><td>Answer Options</td><td>{len(course.answer_options)}</td></tr>
        <tr><td>Assets</td><td>{len(course.assets)}</td></tr>
    </table>
"""
        if course.assets:
            html += """    <h2>Assets</h2>
    <table>
        <tr><th>Asset ID</th><th>Path</th></tr>
"""
            for a in course.assets[:20]:
                html += f"""        <tr><td>{a.asset_id}</td><td>{a.path}</td></tr>
"""
            if len(course.assets) > 20:
                html += f"""        <tr><td colspan="2">... and {len(course.assets)-20} more</td></tr>
"""
            html += "    </table>\n"

        if unsupported_types:
            html += """    <h2>Unsupported Features</h2>
    <ul>
"""
            for u in unsupported_types:
                html += f"        <li>{u}</li>\n"
            html += "    </ul>\n"

        html += """    <h2>Validation Warnings & Errors</h2>
    </table>
        <tr><th>Severity</th><th>Code</th><th>Message</th></tr>
"""
        for note in report_items:
            severity = note.get("severity", "info")
            css_class = {"warning": "warning", "error": "error", "info": "info"}.get(severity, "")
            html += f"""        <tr class="{css_class}">
            <td>{severity}</td>
            <td>{note.get('code', '')}</td>
            <td>{note.get('message', '')}</td>
        </tr>
"""
        html += """    </table>
</body>
</html>"""
        if output:
            Path(output).write_text(html)
            typer.echo(f"HTML report saved to {output}")
        else:
            typer.echo(html)

if __name__ == "__main__":
    app()