from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from core.config import get_settings, reset_settings
from core.ingest import IngestService


def test_settings_resolve_environment_overrides(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LMS_CONVERTER_DATA_DIR", str(tmp_path / "root"))
    monkeypatch.setenv("LMS_CONVERTER_DB_PATH", str(tmp_path / "db" / "jobs.db"))
    monkeypatch.setenv("LMS_CONVERTER_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("LMS_CONVERTER_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("LMS_CONVERTER_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LMS_CONVERTER_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("LMS_CONVERTER_MAX_UPLOAD_BYTES", "123")
    monkeypatch.setenv("LMS_CONVERTER_MAX_EXTRACT_BYTES", "456")
    monkeypatch.setenv("LMS_CONVERTER_MAX_EXTRACT_MEMBERS", "7")
    monkeypatch.setenv("LMS_CONVERTER_MAX_XML_BYTES", "89")
    monkeypatch.setenv("LMS_CONVERTER_ENV", "production")
    monkeypatch.setenv("LMS_CONVERTER_AUTH_MODE", "proxy")
    reset_settings()

    settings = get_settings()
    settings.ensure_directories()

    assert settings.data_dir == tmp_path / "root"
    assert settings.db_path == tmp_path / "db" / "jobs.db"
    assert settings.output_dir == tmp_path / "out"
    assert settings.work_dir == tmp_path / "work"
    assert settings.upload_dir == tmp_path / "uploads"
    assert settings.report_dir == tmp_path / "reports"
    assert settings.max_upload_bytes == 123
    assert settings.max_extract_bytes == 456
    assert settings.max_extract_members == 7
    assert settings.max_xml_bytes == 89
    assert settings.environment == "production"
    assert settings.auth_mode == "proxy"
    assert all(
        path.is_dir()
        for path in (
            settings.data_dir,
            settings.output_dir,
            settings.work_dir,
            settings.upload_dir,
            settings.report_dir,
            settings.db_path.parent,
        )
    )


def test_ingest_uses_configured_data_directory(openedx_archive: Path):
    settings = get_settings()

    result = IngestService().inspect(str(openedx_archive), source_type="openedx")

    assert Path(result["extracted_path"]).is_relative_to(settings.work_dir)
    assert settings.db_path.is_file()


def test_cli_reports_installed_version():
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"
