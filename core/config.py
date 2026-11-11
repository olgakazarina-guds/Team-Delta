"""Central runtime configuration.

Every path and resource limit is resolved here so the CLI, adapters, persistence,
and UI can run from any working directory.  Deployments override the defaults
through environment variables; tests point ``LMS_CONVERTER_DATA_DIR`` at a
temporary directory.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

APP_NAME = "lms-converter"


def default_data_dir() -> Path:
    """Return the platform-appropriate application data directory."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class Settings:
    """Resolved application settings for one process."""

    data_dir: Path
    db_path: Path
    output_dir: Path
    work_dir: Path
    upload_dir: Path
    report_dir: Path
    max_upload_bytes: int = 512 * 1024 * 1024
    max_extract_bytes: int = 2 * 1024 * 1024 * 1024
    max_extract_member_bytes: int = 512 * 1024 * 1024
    max_extract_members: int = 50_000
    max_compression_ratio: float = 250.0
    max_xml_bytes: int = 64 * 1024 * 1024
    max_xml_depth: int = 256
    upload_ttl_seconds: int = 24 * 60 * 60
    environment: str = "development"
    auth_mode: str = "none"
    trusted_user_header: str = "X-Forwarded-User"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, data_dir: str | Path | None = None) -> "Settings":
        root = (
            Path(data_dir).expanduser()
            if data_dir is not None
            else _env_path("LMS_CONVERTER_DATA_DIR", default_data_dir())
        )
        return cls(
            data_dir=root,
            db_path=_env_path("LMS_CONVERTER_DB_PATH", root / "lms_converter.db"),
            output_dir=_env_path("LMS_CONVERTER_OUTPUT_DIR", root / "output"),
            work_dir=_env_path("LMS_CONVERTER_WORK_DIR", root / "work"),
            upload_dir=_env_path("LMS_CONVERTER_UPLOAD_DIR", root / "uploads"),
            report_dir=_env_path("LMS_CONVERTER_REPORT_DIR", root / "reports"),
            max_upload_bytes=_env_int(
                "LMS_CONVERTER_MAX_UPLOAD_BYTES", 512 * 1024 * 1024
            ),
            max_extract_bytes=_env_int(
                "LMS_CONVERTER_MAX_EXTRACT_BYTES", 2 * 1024 * 1024 * 1024
            ),
            max_extract_member_bytes=_env_int(
                "LMS_CONVERTER_MAX_EXTRACT_MEMBER_BYTES", 512 * 1024 * 1024
            ),
            max_extract_members=_env_int(
                "LMS_CONVERTER_MAX_EXTRACT_MEMBERS", 50_000
            ),
            max_compression_ratio=_env_float(
                "LMS_CONVERTER_MAX_COMPRESSION_RATIO", 250.0
            ),
            max_xml_bytes=_env_int(
                "LMS_CONVERTER_MAX_XML_BYTES", 64 * 1024 * 1024
            ),
            max_xml_depth=_env_int("LMS_CONVERTER_MAX_XML_DEPTH", 256),
            upload_ttl_seconds=_env_int(
                "LMS_CONVERTER_UPLOAD_TTL_SECONDS", 24 * 60 * 60
            ),
            environment=os.environ.get("LMS_CONVERTER_ENV", "development").lower(),
            auth_mode=os.environ.get("LMS_CONVERTER_AUTH_MODE", "none").lower(),
            trusted_user_header=os.environ.get(
                "LMS_CONVERTER_TRUSTED_USER_HEADER", "X-Forwarded-User"
            ),
            log_level=os.environ.get("LMS_CONVERTER_LOG_LEVEL", "INFO").upper(),
        )

    def ensure_directories(self) -> None:
        """Create the runtime directories, including the database parent."""
        for path in (
            self.data_dir,
            self.output_dir,
            self.work_dir,
            self.upload_dir,
            self.report_dir,
            self.db_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object."""
    return Settings.from_env()


def reset_settings() -> None:
    """Clear cached settings so environment changes take effect (tests, reloads)."""
    get_settings.cache_clear()
