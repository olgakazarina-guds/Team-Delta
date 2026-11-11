# Production-Readiness Plan: From Converter to Certified Migration Platform

## Status as of 2026-11-11

Phase 0 / Workstream 1 is committed on `phase2/lms-migration`:

- `400850c` removes generated exports and dead modules
- `64e4127` adds the production roadmap and repository policies
- `bcb4da4` hardens the migration pipeline, persistence, and reporting
- `5729227` adds central configuration, an installable wheel, and a lean CLI
- 26 unit tests pass from a rebuilt `uv` environment; the worktree is clean
- `data/lms_converter.db` is backed up and schema migration was verified against the existing 59-job database
- Generated course exports are no longer tracked; `LICENSE`, `CHANGELOG.md`, `SECURITY.md`, and corrected docs are committed
- `uv build` and a clean-venv wheel install succeed; `lms-converter --help` works outside the repository

Workstreams 1 and 2 are complete. There are still no integration or real-LMS tests.

## Verdict

The core architecture is promising: canonical Pydantic IR, deterministic IDs, Moodle/Open edX adapters, validation notes, reports, and a CLI/Streamlit surface. The current hardening pass also closes serious archive/XML/reporting issues.

It is **not production-ready yet**. The biggest gaps are:

1. Broken packaging and no clean-install proof.
2. No CI, linting, type checking, security scanning, or coverage gate.
3. No real Moodle/Open edX import validation.
4. Streamlit is an unauthenticated, unbounded upload service with arbitrary output paths and no temp cleanup.
5. Hardcoded `data/` paths, no central configuration, no ownership/tenancy.
6. Persistence lacks real schema migrations, retention, and lifecycle guarantees.
7. Adapter coverage is narrow and lossy in places, with no public fidelity contract.
8. Generated course data is tracked; docs, license, changelog, and security policy are missing.
9. No API, queue, multi-tenancy, observability, or enterprise controls.
10. No certification or evidence that a migrated course actually works in the target LMS.

## North star

Do not position this as "an XML converter." Position it as:

> **A vendor-neutral, verifiable, secure course-migration platform that proves what was preserved, what changed, and what needs human review.**

The moat is not just conversion. It is **certification, explainability, and trust**.

---

# Guiding principles

1. **Certify, don't assume.** A migration is not done until the target LMS imports it and functional checks pass.
2. **Never lose content silently.** Every unsupported or transformed object must appear in a machine-readable loss report.
3. **Local-first, enterprise-ready.** The same core should run as a CLI, a self-hosted service, an air-gapped appliance, or a managed SaaS.
4. **Secure by default.** Untrusted archives, XML, uploads, and filenames are hostile until proven safe.
5. **Explain every mapping.** Users must see source object -> target object, confidence, and remediation.
6. **Extensible by design.** Adapters should be plugins with a conformance suite, not forks.
7. **Boring operations.** Deterministic builds, migrations, backups, retention, and runbooks.
8. **Accessible and compliant.** WCAG 2.2 AA, GDPR/FERPA-aware data handling, auditability.

---

# Phase roadmap

Indicative for a small team; sequence matters more than calendar.

| Phase | Outcome | Exit criteria |
|---|---|---|
| **0. Stabilize** | Current hardening is trustworthy and committed | Tests pass, diff reviewed, clean tree, generated data untracked, docs/license committed |
| **1. Production foundation** | Installable, configurable, secure baseline | Wheel installs cleanly, CI green, settings/env config, Streamlit safe, DB migrates |
| **2. Migration certification** | Real proof of fidelity | Pinned Moodle/Open edX import harness, golden corpus, fidelity scorecard v1 |
| **3. Service core** | Shared/enterprise deployment | API, queue, object storage, auth/RBAC, retention, observability |
| **4. Differentiation** | Category-defining capabilities | Preflight advisor, review studio, adapter SDK, QTI/Common Cartridge, batch/connectors |
| **5. Enterprise assurance** | Large-organization readiness | SSO/SAML/SCIM, audit, compliance docs, LTS/support, certification program |

---

# Workstream 1 — Stabilize and protect the repository

**P0, do first.**

- Run the full suite in a clean environment; do not trust the current 23 tests until executed.
- Review the uncommitted hardening diff and commit it in logical chunks:
  - archive/XML/path hardening
  - deterministic IDs
  - persistence/lifecycle
  - report consolidation
  - adapter fidelity fixes
  - CLI/Streamlit fixes
- Snapshot `data/lms_converter.db` and test schema migration against the existing 59-job database.
- Remove tracked generated data:
  - `git rm -r --cached data/openedx_export`
  - keep only small, intentional fixtures under `tests/fixtures/`
  - decide separately whether history rewrite is required because course content may be sensitive.
- Commit `docs/`; fix `CONTRIBUTING.md`, which is incomplete and references non-existent files.
- Add `LICENSE`, `CHANGELOG.md`, `SECURITY.md`.
- Delete dead files: `main.py`, zero-byte `core/mapping.py`, `persistence/db.py`, `persistence/models.py`, `adapters/moodle/moodle_api.py` unless intentionally reserved.
- Strengthen `.gitignore`: coverage, caches, logs, `.env.*`, `.streamlit/secrets.toml`, test archives.

**Acceptance:** clean tree, tests pass, no generated course data tracked, docs/license present, DB backup verified.

---

# Workstream 2 — Packaging, configuration, and installability

**P0/P1.**

Current `pyproject.toml` is a release blocker:

- No `[build-system]`.
- Placeholder description.
- `packages = ["cli", "core", "data", "domain", "adapters", "persistence"]` omits `adapters.moodle`, `adapters.openedx`, and `cli.commands`.
- `data` is listed as a Python package but is runtime data.
- `streamlit_app.py` is not packaged deliberately.
- `alembic`, `sqlalchemy`, `httpx`, and `pytest-asyncio` are declared but unused.
- No license, readme, authors, classifiers, URLs, or version flag.

Plan:

- Add explicit build system and package discovery for all real packages.
- Make Streamlit an optional `ui` extra; keep CLI installs lean.
- Add project metadata, readme, license, classifiers, and `--version`.
- Introduce `core/config.py` with a single `Settings` object:
  - `LMS_CONVERTER_DATA_DIR`
  - `LMS_CONVERTER_DB_PATH`
  - `LMS_CONVERTER_OUTPUT_DIR`
  - upload/extraction/XML limits
  - auth mode and environment
- Default to a platform data directory; preserve `./data` in development via env.
- Remove every hardcoded `Path("data/...")` from core, CLI, adapters, and Streamlit.
- Ensure tests use `tmp_path`, never the repository's `data/`.

**Acceptance:** `uv build`, clean-venv wheel install, `lms-converter --help` works outside the repo, tests create no repo-local data.

---

# Workstream 3 — Security and input hardening

**P0/P1.**

Already improved in the worktree, but not shipped or fully tested.

- Archive limits: total size, member size, member count, compression ratio, encrypted ZIPs, symlinks, devices, duplicate entries, Windows/backslash traversal.
- XML: `defusedxml`, byte limits, entity/DTD rejection, nesting limits.
- Upload: application-level size cap, chunked reads, content hash, per-session directory, TTL cleanup.
- Output containment: no free-form output directory; only server-owned roots with `resolve_under`.
- Streamlit: remove raw HTML preview; escape all report content; replace `st.exception` with sanitized errors plus server-side logging.
- Auth: fail closed in production; OIDC or trusted reverse-proxy identity; no custom password database.
- Worker sandbox: non-root container, no network, CPU/memory/time limits, read-only source, ephemeral output.
- Supply chain: lockfile, dependency audit, secret scanning, SBOM, signed releases, pinned container images.
- Optional enterprise: antivirus scanning, PII detection/redaction, encryption at rest, customer-managed keys.

**Acceptance:** malicious archives/XML/uploads rejected; no arbitrary file writes; two users cannot access each other's jobs; production mode refuses unauthenticated access.

---

# Workstream 4 — Persistence, jobs, and lifecycle

**P1.**

Current SQLite layer is a good start but still demo-grade.

- Add schema versioning with `PRAGMA user_version` or a real Alembic path.
- Stop running DDL on every `get_job()` call.
- Add ownership/tenancy fields, status lifecycle, output path, error, timestamps.
- Make migration persistence atomic; stop using `INSERT OR REPLACE` semantics that can destroy history.
- Never fall back to `course.course_id` as a job ID; generate a new ID and warn.
- Add `mark_failed`, `list_jobs`, `delete_job`, retention, and cleanup of rows plus files.
- Add indexes for recent jobs and owner queries.
- Keep SQLite for local/desktop; define a Postgres adapter for shared deployments.
- Add backup/restore, integrity checks, and retention policy.
- Store full course JSON for now, but add schema version and payload version.

**Acceptance:** existing DB migrates without data loss; no lock errors under normal concurrency; failed jobs are recorded; retention removes rows and artifacts; owners are isolated.

---

# Workstream 5 — Migration fidelity and certification

**P1, the heart of the product.**

Current support is narrow and partly placeholder-driven. Build a public contract.

## 5.1 Format and feature matrix

Publish a versioned matrix covering:

- Moodle versions, especially 4.5 LTS and current supported releases.
- Open edX supported releases.
- Activities: page, label, URL, resource, forum, quiz, assignment, choice, book, glossary, wiki, workshop, lesson, SCORM, LTI.
- Question types: multichoice, multiselect, true/false, short answer, numerical, essay, description, matching, cloze, drag-and-drop.
- Assets, embedded HTML, videos, H5P, SCORM 1.2/2004, LTI 1.3.
- Gradebook, completion, roles, groups, cohorts, badges, certificates.
- Policies, licenses, prerequisites, release dates.

For each: **native**, **transformed**, **placeholder**, or **unsupported**.

## 5.2 Lossiness contract

Every migration must emit:

- source object ID
- target object ID
- mapping status
- confidence
- reason
- remediation
- checksum/provenance

No silent loss. Unsupported content becomes an explicit, visible placeholder.

## 5.3 Golden corpus

- Small handcrafted fixtures for every supported feature.
- Real Moodle `.mbz` and Open edX exports with PII scrubbed.
- Synthetic large courses: 1,000+ activities, 10,000+ questions, large assets.
- Malformed, truncated, malicious, and version-skewed packages.
- Expected-output snapshots and round-trip invariants.

## 5.4 Real LMS import harness

This is the key credibility feature.

- Docker Compose or ephemeral CI environments with pinned Moodle and Open edX.
- Import generated package into the target.
- Verify course structure, activities, questions, assets, grades, completion, roles.
- Run nightly and as a release gate, not on every PR.
- Publish results as a certification report.

## 5.5 Fidelity scorecard v1

A signed, versioned report with:

- preserved / transformed / lost counts
- per-activity and per-question results
- asset integrity
- gradebook/completion checks
- warnings and manual-review items
- import test result
- overall confidence score

**Acceptance:** pinned target LMS imports succeed; scorecard matches expected; every loss is visible; round-trip tests pass for supported features.

---

# Workstream 6 — Testing and CI

**P0/P1.**

Current state: 23 unit tests, no CLI/Streamlit/integration/real-LMS tests, no coverage gate.

Build:

- Unit tests for core, adapters, persistence, reporting, security.
- Integration tests for full parse -> transform -> validate -> export.
- CLI end-to-end tests for inspect/migrate/report, exit codes, output files.
- Streamlit smoke tests for upload, inspect, migrate, report, session state.
- Property-based tests for round-trip invariants.
- Fuzz tests for archive/XML parsers.
- Performance tests for large courses.
- Migration tests for old DB schemas.
- Security tests for traversal, bombs, XML entities, XSS, path escapes.
- Coverage floor, starting conservatively and raising it.

CI pipeline:

1. `uv sync --frozen --group dev`
2. `ruff check` + `ruff format --check`
3. `mypy`/`pyright`
4. `pytest --cov --cov-fail-under`
5. `bandit`/`semgrep`
6. `pip-audit`
7. build wheel/sdist
8. install wheel in clean venv
9. smoke-test CLI and a fixture migration
10. nightly real-LMS certification

Add pre-commit hooks and branch protection.

**Acceptance:** CI green from clean checkout; wheel install tested; coverage gate enforced; nightly LMS certification visible.

---

# Workstream 7 — API, queue, and scale

**P1/P2, required for shared/enterprise deployment.**

- FastAPI service with OpenAPI schema.
- Job queue with workers, retries, cancellation, idempotency keys, and progress.
- Object storage for uploads, exports, reports, and logs (S3/MinIO).
- Multi-tenancy and RBAC: admin, migrator, reviewer, viewer.
- Batch migration: whole catalog, scheduling, resumability.
- Webhooks and API callbacks for job completion.
- Direct LMS connectors via Moodle Web Services and Open edX APIs.
- Rate limiting, quotas, and resource isolation.
- Keep CLI and library modes fully supported.

**Acceptance:** API contract tested; jobs survive worker restarts; tenants isolated; batch runs resumable; load test meets target.

---

# Workstream 8 — Observability and operations

**P1.**

- Structured JSON logs with job ID, tenant ID, source, target, duration, outcome.
- Log rotation; no unbounded files.
- OpenTelemetry traces and Prometheus metrics.
- Health and readiness endpoints.
- Audit log for access, migration, download, deletion.
- Dashboards and alerts for failures, latency, queue depth, disk usage.
- Backup/restore runbook and tested restore drill.
- Retention and deletion policy.
- Container images: non-root, read-only FS, resource limits, pinned digests.
- Deployment options: Docker Compose, Helm, systemd, air-gapped bundle.

**Acceptance:** operator can diagnose a failed job from logs/traces; alerts fire; restore drill passes; retention enforced.

---

# Workstream 9 — UX, documentation, and compliance

**P1/P2.**

- Decide UI strategy: keep Streamlit for pilot, build a proper React/TypeScript UI for enterprise.
- Replace free-form job ID with a recent-jobs list and owner-scoped lookup.
- Add side-by-side source/target preview and report diff.
- Add batch dashboard and progress.
- WCAG 2.2 AA for UI and reports; VPAT if selling to public institutions.
- i18n for UI and report strings.
- Rewrite `README.md`: install, CLI, UI, config, limits, deployment, limitations.
- Add architecture doc, adapter contract, format matrix, runbook, security policy, contribution guide, changelog, license.
- Add `.env.example` and `.streamlit/config.toml`.
- Legal review for licensing, especially Moodle GPL and Open edX AGPL implications.
- GDPR/FERPA data-handling guide; DPA and subprocessor list if SaaS.

**Acceptance:** new user can install and run from README; docs match behavior; accessibility audit passes; license reviewed.

---

# Workstream 10 — Category-defining differentiators

These are what make large organizations choose you over a script or a consultancy.

## 1. Migration Fidelity Scorecard

A signed, versioned, machine-readable proof of what survived. This becomes the artifact universities, governments, and enterprises attach to migration sign-off.

## 2. Preflight Migration Advisor

Before conversion, scan the source and report:

- unsupported activities
- broken links
- missing assets
- gradebook complexity
- question-type risks
- estimated manual effort
- recommended policy profile

This turns migration from a black box into a planned project.

## 3. Human Review Studio

Side-by-side source/target diff for every lossy mapping. Reviewers can approve, remap, or exclude items, then re-run only affected objects.

## 4. Certified Migration Program

Run the target LMS import and functional checks in a disposable environment. Publish a certification badge per course/version. This is the trust moat.

## 5. Adapter SDK and Conformance Suite

A stable plugin interface, schema, test harness, and version compatibility matrix. LMS vendors and integrators can certify adapters. You become the neutral standard.

## 6. QTI and Common Cartridge support

Add IMS Common Cartridge 1.3/1.4 and QTI 2.1/2.2 as first-class interchange formats. This expands beyond Moodle/Open edX to Canvas, Blackboard, D2L, Sakai, and government procurement.

## 7. Zero-trust, air-gapped deployment

No network, no telemetry, sandboxed workers, customer-managed keys. Essential for defense, government, and regulated enterprises.

## 8. Provenance ledger and rollback

Immutable record of every transformation and artifact hash. Supports audit, reproducibility, and safe rollback.

## 9. Policy profiles

Institution-specific rules: strip PII, flatten sections, exclude forums, map grading scales, enforce accessibility, rename conventions.

## 10. Batch migration and connectors

Migrate an entire catalog, not one course. Direct Moodle/Open edX connectors reduce manual export/import work.

## 11. Optional AI mapping assistant

Private, opt-in, human-approved suggestions for ambiguous mappings. Never train on customer data. Useful, but not the core moat.

## 12. Accessibility and content quality

Link checker, alt-text report, caption-track detection, HTML sanitizer, accessibility score. This is a major procurement differentiator for education and government.

---

# Prioritized backlog

## P0 — before calling it production-ready

- Commit and stabilize the current hardening work.
- Run and expand tests for every new security control.
- Fix packaging and prove clean-wheel install.
- Add CI, lint, type check, coverage, security scans.
- Remove tracked generated data; commit docs and license.
- Fix Streamlit auth/upload/temp/output-path issues.
- Add central settings and remove hardcoded paths.
- Add real schema migration and DB backup.
- Add real Moodle/Open edX fixtures and import harness.
- Publish the format/lossiness matrix.

## P1 — production operations

- Retention and cleanup for jobs, uploads, extracts, reports.
- API, queue, object storage, auth/RBAC, multi-tenancy.
- Observability, health checks, runbooks, restore drills.
- Fidelity scorecard v1.
- CLI/Streamlit integration tests.
- Documentation, deployment guides, security policy.

## P2 — category-defining

- Preflight advisor.
- Human review studio.
- Adapter SDK and conformance suite.
- QTI/Common Cartridge, H5P, LTI 1.3.
- Certified migration program.
- Batch migration and direct LMS connectors.
- Air-gapped/on-prem enterprise edition.
- Accessibility/i18n/compliance.
- AI mapping assistant.

---

# Definition of done

A release is production-ready only when:

- A clean checkout installs, tests, builds, and runs the CLI/UI.
- CI enforces lint, types, tests, coverage, security, and wheel install.
- No generated course data is tracked.
- Existing databases migrate without data loss.
- Archive/XML/upload limits are enforced and tested.
- HTML reports escape untrusted content.
- Streamlit jobs are owner-isolated and production mode fails closed without auth.
- No runtime path depends on the process CWD.
- Temp uploads and work directories are cleaned up.
- Every migration emits a lossiness report.
- A pinned Moodle and Open edX import harness passes for supported features.
- Docs, license, changelog, security policy, and runbooks exist.

---

# Decisions needed before implementation

1. **Deployment model:** local CLI only, self-hosted service, SaaS, or all three?
2. **Primary customer:** universities, government, corporate L&D, or LMS vendors?
3. **Licensing:** Apache-2.0, AGPL, or open-core with commercial enterprise features?
4. **Certification targets:** which Moodle and Open edX versions must be officially supported?
5. **UI strategy:** keep Streamlit for the pilot, or invest in React now?
6. **Database:** SQLite-only for v1, or Postgres for shared deployments?
7. **Data history:** is the tracked `data/openedx_export` content sensitive enough to require a git history rewrite?
8. **Scope:** which activities and question types are mandatory for the first certified release?

Recommended defaults: local-first CLI + self-hosted web, SQLite for local and Postgres for shared, Streamlit for pilot, Apache-2.0 core with a commercial enterprise layer after legal review, and certification against Moodle 4.5 LTS plus the current supported Open edX release.

The immediate next action is **Workstream 3: security and input hardening**.
