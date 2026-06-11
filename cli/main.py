"""
LMS Converter CLI – Migrate courses between Open edX and Moodle.

Commands:
- inspect: Inspect a course and show structure, warnings, and migration readiness
- migrate: Migrate a course from source LMS to target LMS

Usage:
    lms-converter inspect path/to/course.tar.gz --source openedx
    lms-converter migrate path/to/course.mbz --target openedx --output export.tar.gz
"""

import typer

from cli.commands import inspect_command, migrate_command, report_command

# Create Typer application with help text
app = typer.Typer(
    help="LMS Converter - Migrate courses between Open edX and Moodle"
)


@app.callback()
def main() -> None:
    """
    LMS Converter - Migrate courses between Open edX and Moodle.

    Use 'inspect' to analyze a course and check migration readiness.
    Use 'migrate' to convert a course from one LMS to another.
    """
    pass

# Register commands
app.command("inspect")(inspect_command)
app.command("migrate")(migrate_command)
app.command("report")(report_command)

if __name__ == "__main__":
    app()
