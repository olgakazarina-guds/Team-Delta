# LMS Converter

Vendor-neutral course migration between Moodle and Open edX.

LMS Converter parses course packages, maps them to a canonical course model, validates migration readiness, and generates restore-shaped Moodle backups or Open edX exports. Every migration produces a report describing what was preserved, what changed, and what needs human review.

> Status: alpha. The conversion pipeline is usable, but real-LMS certification and production hardening are still in progress. See [`docs/production-readiness-plan.md`](docs/production-readiness-plan.md).

## Features

- Moodle `.mbz` and Open edX `.tar.gz` inspection.
- Canonical, deterministic course model.
- Moodle to Open edX and Open edX to Moodle conversion.
- Archive, path, and XML input hardening.
- HTML and JSON migration reports.
- SQLite job history with lifecycle states.
- Optional Streamlit UI.

## Requirements

- Python 3.12 or newer.
- [uv](https://docs.astral.sh/uv/) for development and reproducible installs.

## Install

```bash
git clone https://github.com/olgakazarina-guds/Team-Delta.git
cd Team-Delta
uv sync
```

Install the optional Streamlit UI:

```bash
uv sync --extra ui
```

Install development tools:

```bash
uv sync --group dev
```

## CLI

```bash
uv run lms-converter --help
uv run lms-converter --version

uv run lms-converter inspect course.mbz --source moodle --report
uv run lms-converter inspect course.tar.gz --source openedx --validate-for moodle

uv run lms-converter migrate course.mbz --target openedx --output course.tar.gz
uv run lms-converter migrate course.tar.gz --target moodle --output course.mbz

uv run lms-converter report <job-id> --format html --output report.html
```

## Streamlit UI

```bash
uv run --extra ui streamlit run streamlit_app.py
```

## Configuration

All runtime paths and limits are controlled by environment variables. By default, data lives in the platform application data directory (for example `~/.local/share/lms-converter` on Linux), not in the repository.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LMS_CONVERTER_DATA_DIR` | platform data dir | Root for all runtime data |
| `LMS_CONVERTER_DB_PATH` | `<data>/lms_converter.db` | SQLite job database |
| `LMS_CONVERTER_OUTPUT_DIR` | `<data>/output` | Default migration output |
| `LMS_CONVERTER_WORK_DIR` | `<data>/work` | Per-job extraction and build directories |
| `LMS_CONVERTER_UPLOAD_DIR` | `<data>/uploads` | UI upload staging |
| `LMS_CONVERTER_REPORT_DIR` | `<data>/reports` | Generated migration reports |
| `LMS_CONVERTER_MAX_UPLOAD_BYTES` | `536870912` | UI upload limit |
| `LMS_CONVERTER_MAX_EXTRACT_BYTES` | `2147483648` | Archive expansion budget |
| `LMS_CONVERTER_MAX_EXTRACT_MEMBER_BYTES` | `536870912` | Single archive member limit |
| `LMS_CONVERTER_MAX_EXTRACT_MEMBERS` | `50000` | Archive entry limit |
| `LMS_CONVERTER_MAX_COMPRESSION_RATIO` | `250` | Decompression-bomb guard |
| `LMS_CONVERTER_MAX_XML_BYTES` | `67108864` | XML document limit |
| `LMS_CONVERTER_ENV` | `development` | Runtime environment |
| `LMS_CONVERTER_AUTH_MODE` | `none` | Authentication mode |
| `LMS_CONVERTER_LOG_LEVEL` | `INFO` | Default log level |

For local development with repository-local data:

```bash
LMS_CONVERTER_DATA_DIR=./data uv run lms-converter inspect course.mbz
```

## Development

```bash
uv run pytest
uv run pytest --cov=core --cov=adapters --cov=persistence --cov=cli
uv build
```

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) for contribution guidance.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
