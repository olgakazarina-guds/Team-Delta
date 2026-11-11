# Security Policy

## Supported versions

LMS Converter is pre-1.0. Security fixes are applied to the current development branch until a supported-release policy is published.

## Reporting a vulnerability

Do not open a public issue for a security vulnerability.

Use GitHub's private vulnerability reporting for the repository:

https://github.com/olgakazarina-guds/Team-Delta/security/advisories/new

If private reporting is unavailable, contact the repository maintainers directly and include:

- a description of the issue
- affected versions or commits
- reproduction steps or a minimal sanitized proof of concept
- potential impact
- any suggested remediation

Do not include real student data, credentials, or institution-confidential course content in a report.

## Scope

Security-sensitive areas include:

- archive extraction and path containment
- XML parsing and entity handling
- uploaded file handling and temporary storage
- output path containment
- report rendering and HTML escaping
- authentication, authorization, and job ownership
- dependency and supply-chain integrity

## Disclosure

Maintainers will acknowledge a report as soon as practical, investigate, and coordinate a fix and disclosure timeline with the reporter.
