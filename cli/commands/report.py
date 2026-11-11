import json
from pathlib import Path
from typing import Any

import typer

from core.report import render_html_report, render_json_report
from domain.entities import Course
from persistence.repositories import get_job

app = typer.Typer()


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

    if not job.get("course_json"):
        typer.echo(f"Error: Job {job_id} has no course snapshot", err=True)
        raise typer.Exit(1)

    try:
        course = Course.model_validate_json(job["course_json"])
        report_items = json.loads(job.get("report_json") or "[]")
    except Exception as exc:
        typer.echo(f"Error: Could not load report data for {job_id}: {exc}", err=True)
        raise typer.Exit(1)

    report_format = format.strip().lower()
    if report_format == "json":
        content = render_json_report(job_id, job, course, report_items)
    elif report_format == "html":
        content = render_html_report(job_id, job, course, report_items)
    else:
        typer.echo(f"Error: Unsupported report format {format!r}", err=True)
        raise typer.Exit(1)

    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        typer.echo(f"Report saved to {output}")
    else:
        typer.echo(content)


if __name__ == "__main__":
    app()
