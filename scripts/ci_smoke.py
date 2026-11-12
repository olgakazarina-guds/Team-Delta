"""Build and install verification for CI.

Generates a minimal Open edX course fixture, then runs the installed
``lms-converter`` entry point through inspect, migrate, and report so a clean
wheel install is exercised end to end.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

COURSE_FILES = {
    "course.xml": '<course url_name="course1" org="SmokeOrg" course="SMOKE101" />',
    "course/course1.xml": (
        '<course display_name="Smoke Course"><chapter url_name="ch1" /></course>'
    ),
    "chapter/ch1.xml": (
        '<chapter display_name="Chapter One"><sequential url_name="seq1" /></chapter>'
    ),
    "sequential/seq1.xml": (
        '<sequential display_name="Sequential One"><vertical url_name="vert1" /></sequential>'
    ),
    "vertical/vert1.xml": (
        '<vertical display_name="Vertical One">'
        '<html url_name="html1" display_name="Intro HTML" /></vertical>'
    ),
    "html/html1.xml": '<html display_name="Intro HTML" filename="html1.html" />',
    "html/html1.html": "<p>Hello from the smoke fixture.</p>",
}


def build_fixture(archive_path: Path) -> None:
    """Write a minimal valid Open edX export as a tar.gz archive."""
    root = archive_path.parent / "fixture-src"
    for relative, content in COURSE_FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(root)))


def run(cli: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [cli, *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"FAILED: {' '.join([cli, *args])} exited {result.returncode}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cli",
        default="lms-converter",
        help="Path to the installed lms-converter entry point",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="lms-converter-smoke-") as tmp:
        tmp_path = Path(tmp)
        data_dir = tmp_path / "data"
        env = os.environ.copy()
        env["LMS_CONVERTER_DATA_DIR"] = str(data_dir)

        fixture = tmp_path / "smoke-course.tar.gz"
        build_fixture(fixture)

        inspected = run(args.cli, env, "inspect", str(fixture), "--source", "openedx")
        match = re.search(r"Job ID:\s*([0-9a-f-]{36})", inspected.stdout)
        if not match:
            raise SystemExit("FAILED: inspect did not report a job ID")
        job_id = match.group(1)

        output = tmp_path / "out.mbz"
        run(
            args.cli,
            env,
            "migrate",
            str(fixture),
            "--source",
            "openedx",
            "--target",
            "moodle",
            "--output",
            str(output),
        )
        if not output.is_file():
            raise SystemExit("FAILED: migration did not produce an output file")

        run(args.cli, env, "report", job_id, "--format", "json")

    print("Smoke test passed.")


if __name__ == "__main__":
    main()
