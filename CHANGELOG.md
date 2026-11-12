# Changelog

All notable changes to this project are documented here.

The format follows Keep a Changelog, and the project intends to use semantic versioning once it reaches a supported release.

## Unreleased

### Added

- Apache-2.0 license.
- Central environment-driven configuration for paths, upload limits, archive limits, XML limits, environment, and auth mode.
- Installable wheel with all adapter, CLI, core, domain, and persistence packages.
- Optional `ui` extra for Streamlit and a `--version` CLI flag.
- Bounded, chunked upload staging with SHA-256 integrity metadata and TTL cleanup.
- Production authentication gate that fails closed unless a trusted proxy identity is present.
- Owner-scoped job access for the web UI, preventing cross-user job retrieval.
- Server-owned output path resolution for web-facing migrations.
- Deterministic canonical identifiers derived from stable source keys.
- Archive extraction limits and path-containment checks, including duplicate and device entries.
- Defused XML parsing with configurable size and nesting limits.
- Typed application and security errors.
- Escaped, shared HTML report rendering.
- SQLite job lifecycle fields and failed-job recording.
- Tests for archive/XML hardening, uploads, output containment, authentication, job ownership, fidelity regressions, report escaping, and persistence.
- Integration tests for ingest and migration services, CLI end-to-end coverage, Streamlit smoke checks, and legacy schema migration coverage.
- CI workflow running lint, format, type checks, tests with a coverage policy, security scans, dependency audit, and a build/install smoke test on Python 3.12 and 3.13.
- Developer quality tooling: `ruff` lint/format, `mypy` type checks, `bandit` security scans, `pip-audit` dependency audits, and a coverage floor enforced at 80%.
- `scripts/ci_smoke.py`, which exercises a clean wheel install through inspect, migrate, and report on a generated fixture.

### Changed

- Moodle file content hashes are computed with `usedforsecurity=False` because SHA-1 is required by the Moodle backup format for addressing, not for security.
- ZIP archives are now extracted member by member after validation so only individually verified entries are written.
- Target adapters narrow optional internal state through explicit accessors, and optional variables are typed throughout, making the package pass `mypy` with `check_untyped_defs`.

- Moodle backup generation now uses restore-shaped course, section, activity, question, file, and auxiliary XML.
- Open edX export now uses valid OLX problem and SCORM structures, course-scoped policies, and asset manifests.
- Moodle file records now use correct component, file area, and item identifiers.
- Migration jobs preserve existing inspection reports when no new report is supplied.
- Streamlit report rendering delegates to the shared escaped renderer and no longer displays a raw HTML preview.
- Streamlit errors are logged server-side and shown to users as sanitized messages.
- `docs/production-readiness-plan.md` now uses a controlled project-plan structure with scope, WBS, milestones, RACI, RAID, release gates, and a decision log.

### Fixed

- Stale extraction directories could reuse an old `course.xml`.
- Moodle page bodies could be duplicated during round trips.
- True/false answers were mapped by position instead of text.
- Duplicate question identifiers could be emitted across assessments.
- Open edX nested asset paths were flattened.
- Reused target adapters could leak state between exports.

### Removed

- Generated Open edX exports from version control.
- Unused placeholder modules and the hello-world entry point.
