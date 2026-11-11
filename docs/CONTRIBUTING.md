# Contributing to LMS Converter

Thank you for considering contributing to LMS Converter. Contributions are welcome from everyone, whether you are reporting a bug, improving documentation, adding an LMS adapter, or hardening the core services.

## Reporting issues

- Search the [issue tracker](https://github.com/olgakazarina-guds/Team-Delta/issues) before opening a new issue.
- Include a clear title and description.
- Include:
  - steps to reproduce
  - Python and LMS Converter versions
  - source LMS and file format (`.mbz`, `.tar.gz`)
  - sanitized error messages or logs

Do not attach real course exports that contain student data, personal information, or institution-confidential material. Use a minimal sanitized fixture instead.

## Feature requests

- Open an issue and explain the use case and expected benefit.
- Mention whether you intend to implement it.
- For adapter or format work, include the LMS version and a small sanitized sample if possible.

## Development setup

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
uv run pytest -q
```

Useful commands:

```bash
uv run python -m cli.main --help
uv run streamlit run streamlit_app.py
uv run python -m compileall -q adapters cli core domain persistence streamlit_app.py
```

## Code contributions

1. Fork the repository and create a focused branch from `main`.
2. Add or update tests for every behavior change.
3. Keep changes scoped; avoid unrelated formatting or refactors in the same pull request.
4. Run the test suite and compile check before opening a pull request.
5. Describe migration-fidelity impact in the pull request:
   - source and target LMS versions
   - activities or question types affected
   - new warnings, placeholders, or lossy mappings
   - fixture coverage

## Coding style

- Follow the existing Python style and module structure.
- Use type hints for public functions and dataclasses/Pydantic models for structured data.
- Keep XML generation separate from parsing and transformation.
- Treat archive contents, XML, filenames, and uploaded files as untrusted input.
- Do not add new hardcoded `data/` paths; configuration work is tracked in the production-readiness plan.
- Do not add comments that restate the code. Explain non-obvious decisions only.

The project does not yet enforce a formatter or linter in CI. Until it does, match the surrounding code and keep diffs clean.

## Test data and privacy

- Put small synthetic fixtures under `tests/fixtures/`.
- Do not commit generated exports, database files, logs, or real course archives.
- Scrub names, emails, user IDs, grades, and institution identifiers from any sample package.
- If a bug requires a real package, reduce it to the smallest sanitized reproduction.

## Pull requests

- Keep the title imperative and specific, for example: `fix: preserve nested Open edX asset paths`.
- Reference the issue being addressed.
- Confirm that tests pass and that no generated data is included.
- Expect review comments about fidelity, security, and operational impact.

## Architecture and roadmap

See [production-readiness-plan.md](production-readiness-plan.md) for the current architecture, workstreams, and release criteria.

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
