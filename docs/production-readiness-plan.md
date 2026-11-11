# LMS Converter Production-Readiness Plan

## Document control

| Field | Value |
| --- | --- |
| Document version | 2.0 |
| Status | Draft for approval |
| Date | 2026-11-11 |
| Owner | Team Delta |
| Approver | TBD |
| Repository | `olgakazarina-guds/Team-Delta` |
| Branch | `phase2/lms-migration` |
| Review cycle | Monthly and at milestone completion |
| Related documents | `README.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/CONTRIBUTING.md`, `LICENSE` |

## 1. Executive summary

LMS Converter converts course packages between Moodle and Open edX. It parses source packages into a canonical course model, validates migration readiness, generates target packages, and records what was preserved, transformed, or lost.

The project has completed its initial stabilization and packaging work. The remaining work is to make the application safe to operate, prove migration fidelity against real LMS instances, and establish repeatable release controls.

This plan covers the production-readiness release: a self-hosted CLI and web pilot supported by a small team. It defines the work breakdown, milestones, ownership, risks, quality gates, and decisions required to reach that release. Long-term product expansion is listed separately in Appendix B and is outside this release.

**Decision requested:** approve the scope, milestones, and release gates in this document.

## 2. Current baseline

Status as of 2026-11-11.

| Area | Status | Evidence | Remaining work |
| --- | --- | --- | --- |
| Repository hygiene | Complete | Generated course exports are untracked; dead modules removed; repository policies added in `400850c`, `64e4127`, and `bcb4da4` | Decide whether historical generated data requires a git history rewrite |
| Packaging and configuration | Complete | `uv build` succeeds; clean-venv wheel install works; `lms-converter --version` works outside the repository; centralized `Settings` added in `5729227` | Add release automation and CI installation checks |
| Security and input controls | Implemented, uncommitted | Bounded uploads, archive and XML limits, output containment, production auth, owner-scoped jobs, sanitized UI errors, and 45 unit tests | Review and commit; add container and supply-chain controls |
| Persistence | Partial | SQLite job records, lifecycle states, and owner field exist | Add schema versioning, stop running DDL on reads, add retention and backup/restore tests |
| Migration fidelity | Partial | Canonical model, Moodle/Open edX adapters, validation notes, and JSON/HTML reports exist | Build a golden corpus, real-LMS import harness, and versioned fidelity scorecard |
| Testing and CI | Partial | 45 unit tests pass; no integration, CLI end-to-end, Streamlit, or real-LMS tests; no CI pipeline | Add test layers, coverage policy, linting, type checking, and CI gates |
| Operations | Not started | No deployment runbook, health checks, metrics, or container image | Add observability, deployment artifacts, backup/restore drill, and operator documentation |
| Documentation | Partial | README, security policy, contribution guide, changelog, license, and architecture diagram exist | Add architecture reference, deployment runbook, format matrix, and release checklist |
| Real-LMS certification | Not started | No live Moodle or Open edX environment available | Provision pinned test environments and run import certification |

## 3. Objectives and success criteria

The release objective is to provide a self-hosted alpha that a small team can install, operate, and evaluate safely, with reproducible builds, controlled input handling, durable job records, and evidence of migration fidelity against agreed LMS versions.

| ID | Objective | Success measure |
| --- | --- | --- |
| SC-1 | Reproducible installation | Wheel and source distribution build from a clean checkout; wheel installs in a clean virtual environment; CLI runs outside the repository on supported Python versions; CI is green |
| SC-2 | Secure defaults | Malicious archive, XML, and upload fixtures are rejected; output writes stay inside server-owned roots; production mode fails closed without a trusted identity; no open P0/P1 security findings |
| SC-3 | Durable persistence | Existing databases migrate without data loss; schema version is recorded; reads do not run DDL; retention and backup/restore are tested |
| SC-4 | Verified migration fidelity | Pinned Moodle and Open edX imports pass for every feature marked supported in the format matrix; every loss is visible in a machine-readable report |
| SC-5 | Operable deployment | Deployment, health checks, logs, backup, restore, and rollback are documented and exercised; restore drill passes |
| SC-6 | Release discipline | Every release passes the quality gates in Section 9; version, changelog, and artifacts are published together |

## 4. Scope and non-goals

### In scope

- Commit and stabilize the current security and input-hardening work.
- Expand unit tests and add integration, CLI, Streamlit, persistence, and security tests.
- Add CI, linting, type checking, coverage policy, dependency auditing, and wheel installation checks.
- Complete persistence lifecycle work: schema versioning, retention, cleanup, backup, and restore.
- Build a golden corpus of sanitized Moodle and Open edX fixtures.
- Stand up pinned Moodle and Open edX import environments.
- Publish a versioned migration fidelity scorecard.
- Add deployment hardening, operator documentation, and pilot readiness checks.
- Resolve the decisions in Section 11.

### Out of scope

- SaaS multi-tenancy, enterprise SSO/SAML/SCIM, and customer-managed keys.
- Direct Moodle Web Services or Open edX API connectors.
- QTI, Common Cartridge, H5P, and LTI 1.3 as first-class formats.
- A React/TypeScript replacement for the Streamlit pilot UI.
- AI-assisted mapping or automated content remediation.
- Formal accessibility certification, VPAT, or compliance audit.
- A git history rewrite unless decision D-07 requires one.

These items are recorded in Appendix B as long-term product work. They are not part of the production-readiness release.

## 5. Work breakdown structure

Effort sizes are indicative: S is up to three working days, M is one to two weeks, and L is two to four weeks. Sizes assume one engineer and must be re-baselined after staffing and LMS access are confirmed.

| ID | Deliverable | Dependencies | Owner | Size | Acceptance |
| --- | --- | --- | --- | --- | --- |
| PR-01 | Commit and stabilize security controls | Current working tree | Tech Lead | S | Workstream 3 changes reviewed; 45 tests pass; build and clean install pass; changes committed |
| PR-02 | Expand the test suite | PR-01 | QA/Automation | M | Integration, CLI end-to-end, Streamlit smoke, persistence migration, and security tests exist and run locally |
| PR-03 | Add CI and quality gates | PR-02 | Security/DevOps | M | Clean checkout runs lint, format, type checks, tests, coverage policy, security scans, build, and wheel install |
| PR-04 | Add release packaging automation | PR-03 | Tech Lead | S | Versioned wheel and source distribution are built and installed by CI; changelog and version are checked |
| PR-05 | Add database schema versioning | PR-01 | Tech Lead | M | `PRAGMA user_version` is recorded; existing database migrates without loss; reads do not run DDL; migration tests pass |
| PR-06 | Add retention and cleanup | PR-05 | Tech Lead | M | Configurable retention removes job rows and artifacts; dry-run mode exists; cleanup tests pass |
| PR-07 | Build the golden corpus | PR-01 | Fidelity/Adapter Engineer | L | Sanitized fixtures cover every supported feature; malformed and malicious fixtures exist; expected snapshots are stored |
| PR-08 | Build the LMS import harness | PR-07, DEP-01, D-04 | QA/Automation | L | Pinned Moodle and Open edX environments import generated packages; harness runs nightly and at release |
| PR-09 | Publish the fidelity scorecard | PR-07, PR-08 | Fidelity/Adapter Engineer | M | Versioned machine-readable report includes preserved, transformed, and lost counts plus import results |
| PR-10 | Write deployment and operator documentation | PR-03 | Documentation/UX | M | README, architecture reference, deployment guide, backup/restore runbook, limitations, and troubleshooting are complete |
| PR-11 | Harden deployment artifacts | PR-03 | Security/DevOps | M | Non-root container, read-only source, resource limits, pinned images, dependency audit, and SBOM are in place |
| PR-12 | Complete pilot readiness | PR-05, PR-06, PR-09, PR-10, PR-11 | Project Lead | S | Pilot checklist, support process, rollback procedure, and sign-off are complete |

## 6. Milestones and schedule

Durations are indicative and assume one to two engineers. They are not calendar commitments until staffing and LMS access are confirmed.

| Milestone | Scope | Exit criteria | Dependencies | Indicative duration |
| --- | --- | --- | --- | --- |
| M0 Baseline | PR-01, PR-02 | Security work committed; baseline test suite runs locally; test gaps recorded | Current working tree | 1-2 weeks |
| M1 Secure foundation | PR-03 to PR-06, PR-11 | CI is green; schema versioning and retention work; deployment artifacts meet the hardening checklist | M0 | 3-5 weeks |
| M2 Certification | PR-07 to PR-09 | Golden corpus, LMS import harness, and scorecard are complete for the agreed feature matrix | M1, DEP-01, D-04 | 4-6 weeks |
| M3 Pilot | PR-10, PR-12 | Documentation and runbooks are complete; pilot checklist and rollback procedure are approved | M2 | 2-3 weeks |
| M4 Production release | Release gates in Section 9 | All release gates pass; release is signed off | M3 | 1-2 weeks |

## 7. Roles and responsibilities

| Role | Responsibilities | Current assignee |
| --- | --- | --- |
| Project Lead | Scope, milestones, stakeholder decisions, risk review, release sign-off | TBD |
| Tech Lead | Architecture, core services, persistence, code review, technical decisions | TBD |
| Fidelity/Adapter Engineer | Format matrix, adapters, fixtures, loss reporting, scorecard | TBD |
| QA/Automation | Test strategy, CI, CLI/UI tests, LMS import harness | TBD |
| Security/DevOps | Threat model, dependency and secret scanning, containers, deployment | TBD |
| Documentation/UX | README, runbooks, pilot workflow, report usability | TBD |

### RACI

R = responsible, A = accountable, C = consulted, I = informed.

| Activity | Project Lead | Tech Lead | Fidelity Engineer | QA | Security/DevOps | Documentation |
| --- | --- | --- | --- | --- | --- | --- |
| Scope and release approval | A/R | C | C | I | C | I |
| Architecture and technical design | C | A/R | C | C | C | I |
| Implementation | I | A/R | R | C | C | I |
| Test and certification strategy | A | C | R | R | C | I |
| Security and deployment review | A | C | I | C | R | I |
| Documentation and pilot readiness | A | C | C | C | C | R |

## 8. Risks, assumptions, issues, and dependencies

| ID | Type | Description | Impact | Likelihood | Mitigation | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| R-01 | Risk | No live Moodle or Open edX environment is available for import testing | High | High | Provision a Docker-based harness or hosted sandbox before M2; treat access as a milestone dependency | QA/Automation |
| R-02 | Risk | Moodle GPL and Open edX AGPL licensing may constrain distribution or commercial use | High | Medium | Complete legal review before distributing a commercial or hosted offering; keep licensing decisions documented | Project Lead |
| R-03 | Risk | Course packages may contain student data, personal information, or institution-confidential material | High | Medium | Use sanitized fixtures; document retention and deletion; restrict access to test data | Security/DevOps |
| R-04 | Risk | SQLite may produce lock contention or scale limits under concurrent jobs | Medium | Medium | Keep a single-writer design for the pilot; test concurrency; define the Postgres migration path | Tech Lead |
| R-05 | Risk | Streamlit may not meet long-term UI, accessibility, or multi-user requirements | Medium | High | Limit Streamlit to the pilot; decide on the UI strategy at M2 | Project Lead |
| R-06 | Risk | Scope expansion delays the production-readiness release | High | High | Enforce the non-goals in Section 4; require change approval for scope changes | Project Lead |
| A-01 | Assumption | Python 3.12 and newer remain the supported runtime | Low | Low | Run CI against supported Python versions; document the support policy | Tech Lead |
| A-02 | Assumption | Target LMS versions can be pinned in test environments | Medium | Medium | Confirm versions through D-04 before building the harness | Tech Lead |
| DEP-01 | Dependency | LMS test environment access is required for certification | High | High | Assign an owner and confirm access before M2 | Project Lead |
| DEP-02 | Dependency | Legal review is required before release distribution | Medium | Medium | Start review during M1; record the outcome in the decision log | Project Lead |
| ISS-01 | Issue | Current security changes are uncommitted | Medium | High | Complete PR-01 before starting dependent work | Tech Lead |

## 9. Quality, security, and release gates

### Test layers

| Level | Scope | Required run |
| --- | --- | --- |
| Unit | Core, adapters, persistence, reporting, security helpers | Every pull request |
| Integration | Parse, transform, validate, and export pipeline | Every pull request |
| CLI end-to-end | Inspect, migrate, report, exit codes, output files | Every pull request |
| Streamlit smoke | Upload, inspect, migrate, report, session isolation | Every pull request or nightly |
| Security | Traversal, archive bombs, XML entities, XSS, auth, ownership | Every pull request |
| Database migration | Previous schema to current schema | Every pull request |
| Property and fuzz | Round-trip invariants and parser robustness | Nightly |
| Performance | Large course and asset fixtures | Weekly and release |
| LMS certification | Pinned Moodle and Open edX import checks | Nightly and release |

### CI gates

1. `uv sync --frozen --group dev`
2. `ruff check` and `ruff format --check`
3. `mypy` or `pyright`
4. `pytest --cov` with the agreed coverage policy
5. `bandit` or `semgrep`
6. `pip-audit`
7. Build wheel and source distribution
8. Install the wheel in a clean virtual environment
9. Smoke-test the CLI and one fixture migration
10. Run nightly LMS certification after PR-08 is complete

### Release gates

A release is approved only when:

- All work in the approved milestone is complete.
- CI passes from a clean checkout.
- No open P0/P1 security findings remain.
- Existing databases migrate without data loss.
- Backup and restore have been exercised.
- The supported feature matrix passes LMS import certification.
- README, changelog, security policy, and operator runbook match the release.
- Project Lead, Tech Lead, QA, and Security/DevOps have signed off.

## 10. Governance and change control

- **Status reporting:** weekly written update covering completed work, work in progress, blockers, risks, and decisions needed.
- **Milestone reviews:** each milestone closes with an exit-criteria review and a plan update.
- **Decision log:** decisions are recorded in Section 11 with owner, date, and status.
- **Change control:** scope, schedule, or release-gate changes require Project Lead approval and a plan version update.
- **Risk review:** the RAID log is reviewed at every milestone and when a high-impact risk changes.
- **Repository policy:** changes require review; CI must pass before merge; generated course data and secrets must not be committed.

## 11. Decisions and open questions

| ID | Decision | Options | Recommendation | Owner | Due | Status |
| --- | --- | --- | --- | --- | --- | --- |
| D-01 | Deployment model | CLI only; self-hosted service; SaaS; all three | Self-hosted CLI and web pilot; defer SaaS | Project Lead | M1 | Open |
| D-02 | Primary customer | Universities; government; corporate learning; LMS vendors | Higher-education and public-sector course teams | Project Lead | M1 | Open |
| D-03 | Licensing | Apache-2.0; AGPL; open-core with commercial features | Apache-2.0 core; legal review before any commercial layer | Project Lead | M1 | Open |
| D-04 | Certification targets | Moodle versions and Open edX releases | Moodle 4.5 LTS and the current supported Open edX release | Tech Lead | M1 | Open |
| D-05 | UI strategy | Streamlit; React/TypeScript | Streamlit for the pilot; revisit after M2 | Project Lead | M2 | Open |
| D-06 | Database strategy | SQLite only; SQLite local plus Postgres shared | SQLite for local and pilot; define Postgres before shared deployment | Tech Lead | M1 | Open |
| D-07 | Git history rewrite | Rewrite; retain history | Retain until data sensitivity review; rewrite only if required | Project Lead | M1 | Open |
| D-08 | First release feature scope | Full matrix; limited certified subset | Certify only features marked native or transformed in Appendix A | Fidelity/Adapter Engineer | M1 | Open |

## Appendix A: Format and feature matrix

The matrix is a release artifact. Each row must be marked native, transformed, placeholder, or unsupported, with a fixture and evidence link.

| Category | Items to classify |
| --- | --- |
| LMS versions | Moodle 4.5 LTS; current supported Open edX release; additional versions per D-04 |
| Activities | Page, label, URL, resource, forum, quiz, assignment, choice, book, glossary, wiki, workshop, lesson, SCORM, LTI |
| Question types | Multichoice, multiselect, true/false, short answer, numerical, essay, description, matching, cloze, drag-and-drop |
| Assets and content | Files, embedded HTML, video, H5P, SCORM 1.2/2004, LTI 1.3 |
| Course structure | Sections, gradebook, completion, roles, groups, cohorts, badges, certificates |
| Policies | Licenses, prerequisites, release dates |

Status definitions:

- **Native:** represented directly in the target format.
- **Transformed:** converted to a different but functional target representation.
- **Placeholder:** preserved as visible content with manual review required.
- **Unsupported:** rejected or omitted with an explicit report entry.

## Appendix B: Long-term product roadmap

These initiatives are outside the production-readiness release. They should be prioritized only after M4 or after the pilot produces evidence of demand.

| Initiative | Intended outcome | Prerequisite |
| --- | --- | --- |
| Preflight migration advisor | Report unsupported content, broken links, missing assets, and estimated manual effort before conversion | Golden corpus and format matrix |
| Human review studio | Side-by-side source and target review with approve, remap, and exclude actions | Stable job model and scorecard |
| Adapter SDK and conformance suite | Allow external adapters to be tested against a versioned contract | Stable canonical model and test harness |
| QTI and Common Cartridge support | Add IMS QTI 2.1/2.2 and Common Cartridge 1.3/1.4 as interchange formats | Format matrix and certification harness |
| Batch migration and LMS connectors | Migrate course catalogs and reduce manual export/import work | API, queue, and direct LMS integration |
| Certified migration program | Publish per-course certification results and versioned badges | LMS harness and scorecard |
| Policy profiles | Apply institution-specific rules for PII, sections, grading, accessibility, and naming | Stable transformation pipeline |
| Provenance ledger and rollback | Record transformations and artifact hashes for audit and rollback | Immutable job history |
| Accessibility and content quality | Detect missing alt text, captions, broken links, and HTML issues | Report pipeline |
| Optional AI-assisted mapping | Suggest mappings for ambiguous content with human approval and no training on customer data | Stable mapping contract and privacy review |
| Enterprise controls | SSO/SAML/SCIM, audit, air-gapped deployment, customer-managed keys | Security and deployment foundation |

## Appendix C: Document history

| Version | Date | Author | Change |
| --- | --- | --- | --- |
| 2.0 | 2026-11-11 | Team Delta | Rewrote as a controlled project plan; separated baseline, scope, WBS, milestones, RACI, RAID, gates, and decisions; moved long-term work to an appendix |
| 1.0 | 2026-11-11 | Team Delta | Initial roadmap and workstream list |
