"""Moodle 5.3 certification target backed by Docker Compose."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tests.certification.artifacts import BuiltArtifact, safe_name
from tests.certification.evidence import Evidence, load_evidence, sha256_file
from tests.certification.models import (
    EnvironmentInfo,
    ImportResult,
    ImportStatus,
    ReimportInfo,
)
from tests.certification.runtime import CommandError, CommandResult, CommandRunner, SubprocessRunner
from tests.certification.targets import (
    CertificationUnavailable,
    FeatureCheck,
)
from tests.certification.verifiers import verify_feature

MOODLE_VERSION = "5.3.1"
MOODLE_IMAGE = (
    "moodlehq/moodle-php-apache:8.4"
    "@sha256:093506f1d1dbdfaeaeb204793e17c5352329368914ab4ea7f7a9fc2a120e9269"
)
MOODLE_RELEASE = "5.3 LTS"
MOODLE_COMPONENTS = {
    "php": "8.4",
    "database": "MariaDB 11.4",
    "moodle": MOODLE_VERSION,
}


class MoodleTarget:
    """Import a generated .mbz into a disposable Moodle instance."""

    name = "moodle"

    def __init__(
        self,
        runner: CommandRunner | None = None,
        *,
        run_id: str = "local",
        root: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.root = root or Path(__file__).parent / "environments" / "moodle"
        self.project = f"lms-certification-moodle-{safe_name(run_id)}"
        self.env = {
            "MOODLE_DB_PASSWORD": os.environ.get("MOODLE_DB_PASSWORD", "certification"),
            "MOODLE_DB_ROOT_PASSWORD": os.environ.get(
                "MOODLE_DB_ROOT_PASSWORD", "certification-root"
            ),
            "MOODLE_ADMIN_PASSWORD": os.environ.get("MOODLE_ADMIN_PASSWORD", "Certification1!"),
            "MOODLE_PORT": os.environ.get("MOODLE_PORT", "18080"),
        }
        if environment:
            self.env.update(environment)
        self.env["MOODLE_WWWROOT"] = os.environ.get(
            "MOODLE_WWWROOT",
            f"http://127.0.0.1:{self.env['MOODLE_PORT']}",
        )
        self._started = False
        self._artifact: BuiltArtifact | None = None
        self._reimport_path: Path | None = None
        self._reimport_info: ReimportInfo | None = None
        self._original_evidence: Evidence | None = None
        self._reimport_evidence: Evidence | None = None
        self._logs: list[tuple[str, Path]] = []
        self._last_command: list[str] = []
        self._import_command: list[str] = []
        self._import_exit_code: int | None = None

    def environment(self) -> EnvironmentInfo:
        return EnvironmentInfo(
            target=self.name,
            release=MOODLE_RELEASE,
            patch=MOODLE_VERSION,
            components=dict(MOODLE_COMPONENTS),
            image=MOODLE_IMAGE,
        )

    def import_artifact(self, artifact: BuiltArtifact, work_dir: Path) -> ImportResult:
        self._artifact = artifact
        self._reimport_path = None
        self._reimport_info = None
        work_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()

        try:
            self._ensure_started(work_dir)
            import_result = self._restore(artifact, work_dir)
            self._import_command = list(import_result.command)
            self._import_exit_code = import_result.exit_code
            self._reimport(work_dir)
        except CertificationUnavailable:
            raise
        except CommandError as exc:
            return self._failure(exc, work_dir, started)
        except Exception as exc:
            return ImportResult(
                status=ImportStatus.ERROR,
                message=f"{type(exc).__name__}: {exc}",
                log_file=self._combined_log(work_dir),
            )

        elapsed = round(time.monotonic() - started, 3)
        return ImportResult(
            status=ImportStatus.PASSED,
            command=self._import_command,
            exit_code=self._import_exit_code,
            duration_seconds=elapsed,
            log_file=self._combined_log(work_dir),
            message=f"Moodle {MOODLE_VERSION} restored and re-exported the course.",
            reimport=self._reimport_info,
        )

    def verify_feature(self, feature: Mapping[str, Any], work_dir: Path) -> FeatureCheck:
        if self._artifact is None or self._reimport_path is None:
            raise CertificationUnavailable("Moodle import evidence is not available")
        if self._original_evidence is None:
            self._original_evidence = load_evidence(
                self._artifact.path,
                "moodle",
                work_dir / "verify-original",
            )
        if self._reimport_evidence is None:
            self._reimport_evidence = load_evidence(
                self._reimport_path,
                "moodle",
                work_dir / "verify-reimport",
            )
        return verify_feature(
            str(feature["id"]),
            self._original_evidence,
            self._reimport_evidence,
        )

    def close(self) -> None:
        if not self._started:
            return
        self._started = False
        result = self.runner.run(
            self._compose_command(["down", "-v", "--remove-orphans"]),
            cwd=self.root,
            env=self.env,
            timeout=180,
        )
        if result.exit_code != 0:
            return

    def _ensure_started(self, work_dir: Path) -> None:
        if self._started:
            return

        docker = self.runner.run(
            ["docker", "info"],
            timeout=30,
            log_path=work_dir / "logs" / "docker-info.log",
        )
        if not docker.ok:
            raise CertificationUnavailable(
                "Moodle certification environment is not available: Docker is unavailable"
            )

        self._compose(
            ["down", "-v", "--remove-orphans"],
            work_dir,
            "compose-down-before-up.log",
            timeout=180,
            required=False,
        )
        self._started = True
        self._compose(
            ["up", "-d", "--build", "--wait"],
            work_dir,
            "compose-up.log",
            timeout=1800,
        )
        self._compose(
            [
                "exec",
                "-T",
                "moodle",
                "php",
                "admin/cli/install.php",
                "--non-interactive",
                f"--wwwroot={self.env['MOODLE_WWWROOT']}",
                "--dataroot=/var/moodledata",
                "--dbtype=mariadb",
                "--dbhost=db",
                "--dbname=moodle",
                "--dbuser=moodle",
                f"--dbpass={self.env['MOODLE_DB_PASSWORD']}",
                "--fullname=Certification Course",
                "--shortname=certification",
                "--adminuser=admin",
                f"--adminpass={self.env['MOODLE_ADMIN_PASSWORD']}",
                "--adminemail=admin@example.test",
                "--agree-license",
            ],
            work_dir,
            "install.log",
            timeout=600,
        )

    def _restore(self, artifact: BuiltArtifact, work_dir: Path) -> CommandResult:
        self._compose(
            ["cp", str(artifact.path), "moodle:/tmp/certification-import.mbz"],
            work_dir,
            "copy-import.log",
            timeout=180,
        )
        return self._compose(
            [
                "exec",
                "-T",
                "moodle",
                "php",
                "admin/cli/restore_backup.php",
                "--file=/tmp/certification-import.mbz",
                "--categoryid=1",
                "--showdebugging",
            ],
            work_dir,
            "restore.log",
            timeout=900,
        )

    def _reimport(self, work_dir: Path) -> None:
        course_id = self._course_id(work_dir)
        self._compose(
            ["exec", "-T", "moodle", "rm", "-rf", "/tmp/certification-reimport"],
            work_dir,
            "cleanup-reimport.log",
            required=False,
        )
        self._compose(
            ["exec", "-T", "moodle", "mkdir", "-p", "/tmp/certification-reimport"],
            work_dir,
            "prepare-reimport.log",
            timeout=60,
        )
        backup = self._compose(
            [
                "exec",
                "-T",
                "moodle",
                "php",
                "admin/cli/backup.php",
                f"--courseid={course_id}",
                "--destination=/tmp/certification-reimport",
            ],
            work_dir,
            "rebackup.log",
            timeout=900,
        )
        remote_file = self._remote_backup_file(work_dir)
        destination = work_dir / "reimport.mbz"
        self._compose(
            ["cp", f"moodle:{remote_file}", str(destination)],
            work_dir,
            "copy-reimport.log",
            timeout=180,
        )
        self._reimport_path = destination
        self._reimport_info = ReimportInfo(
            status=ImportStatus.PASSED,
            command=list(backup.command),
            exit_code=backup.exit_code,
            duration_seconds=backup.duration_seconds,
            file_name=destination.name,
            sha256=sha256_file(destination),
            size_bytes=destination.stat().st_size,
            log_file="rebackup.log",
        )

    def _course_id(self, work_dir: Path) -> str:
        script = (
            'define("CLI_SCRIPT", true); '
            'require("/var/www/html/config.php"); '
            "$rows = $DB->get_records_sql("
            '"SELECT id FROM {course} WHERE id > 1 ORDER BY id DESC", null, 0, 1); '
            "$row = reset($rows); echo $row ? (string)$row->id : '';"
        )
        result = self._compose(
            ["exec", "-T", "moodle", "php", "-r", script],
            work_dir,
            "course-id.log",
            timeout=120,
        )
        match = re.search(r"(\d+)\s*$", result.stdout)
        if not match:
            raise RuntimeError("Moodle restore did not create a course")
        return match.group(1)

    def _remote_backup_file(self, work_dir: Path) -> str:
        script = (
            '$files = glob("/tmp/certification-reimport/*.mbz"); '
            "sort($files); echo $files ? end($files) : '';"
        )
        result = self._compose(
            ["exec", "-T", "moodle", "php", "-r", script],
            work_dir,
            "find-rebackup.log",
            timeout=60,
        )
        matches = re.findall(r"/tmp/certification-reimport/[^\s]+\.mbz", result.stdout)
        if not matches:
            raise RuntimeError("Moodle re-backup did not produce a .mbz file")
        return matches[-1]

    def _compose(
        self,
        arguments: list[str],
        work_dir: Path,
        log_name: str,
        *,
        timeout: float = 600,
        required: bool = True,
    ) -> CommandResult:
        return self._run(
            self._compose_command(arguments),
            work_dir,
            log_name,
            timeout=timeout,
            required=required,
        )

    def _compose_command(self, arguments: list[str]) -> list[str]:
        return [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(self.root / "compose.yaml"),
            *arguments,
        ]

    def _run(
        self,
        command: list[str],
        work_dir: Path,
        log_name: str,
        *,
        timeout: float = 600,
        required: bool = True,
    ) -> CommandResult:
        log_path = work_dir / "logs" / log_name
        result = self.runner.run(
            command,
            cwd=self.root,
            env=self.env,
            timeout=timeout,
            log_path=log_path,
        )
        self._last_command = list(result.command)
        self._logs.append((log_name, log_path))
        if required and not result.ok:
            raise CommandError(result, result.stderr.strip() or result.stdout.strip())
        return result

    def _combined_log(self, work_dir: Path) -> str | None:
        if not self._logs:
            return None
        target = work_dir / "import.log"
        sections: list[str] = []
        for name, path in self._logs:
            if not path.is_file():
                continue
            sections.append(f"===== {name} =====")
            sections.append(path.read_text(encoding="utf-8", errors="replace").rstrip())
        if not sections:
            return None
        target.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        return target.name

    def _failure(self, exc: CommandError, work_dir: Path, started: float) -> ImportResult:
        result = exc.result
        message = result.output or str(exc)
        return ImportResult(
            status=ImportStatus.FAILED,
            command=list(result.command),
            exit_code=result.exit_code,
            duration_seconds=round(time.monotonic() - started, 3),
            log_file=self._combined_log(work_dir),
            message=message[-4000:] if message else str(exc),
        )
