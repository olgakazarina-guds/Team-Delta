"""
LMS Converter CLI - Migrate courses between Open edX and Moodle.

Commands:
- inspect: Inspect a course and show structure, warnings, and migration readiness
- migrate: Migrate a course from source LMS to target LMS

Usage:
    lms-converter inspect path/to/course.tar.gz --source openedx
    lms-converter migrate path/to/course.mbz --target openedx --output export.tar.gz
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

import typer

from cli.commands import inspect_command, migrate_command, report_command

# Create Typer application with help text
app = typer.Typer(help="LMS Converter - Migrate courses between Open edX and Moodle")


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        current = package_version("lms-converter")
    except PackageNotFoundError:
        current = "0.1.0"
    typer.echo(current)
    raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
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
