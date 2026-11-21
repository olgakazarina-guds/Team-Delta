"""Execute certification plans against a target environment."""

from __future__ import annotations

import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.certification.artifacts import (
    ArtifactBuilder,
    build_golden_artifact,
    safe_name,
)
from tests.certification.models import (
    ArtifactInfo,
    CaseResult,
    CaseStatus,
    CertificationReport,
    FeatureOutcome,
    FeatureResult,
    ImportResult,
    ImportStatus,
    ReimportInfo,
    ReportStatus,
    ReportSummary,
)
from tests.certification.plan import CertificationPlan, PlannedImport
from tests.certification.redaction import redact
from tests.certification.targets import (
    CertificationTarget,
    CertificationUnavailable,
    FeatureCheck,
    TargetFactory,
)


def _sanitize_import_result(result: ImportResult) -> ImportResult:
    reimport = result.reimport
    if reimport is not None:
        reimport = reimport.model_copy(
            update={
                "command": [redact(argument) for argument in reimport.command],
                "message": redact(reimport.message) if reimport.message else None,
            }
        )
    return result.model_copy(
        update={
            "command": [redact(argument) for argument in result.command],
            "message": redact(result.message) if result.message else None,
            "reimport": reimport,
        }
    )


def _feature_result(
    feature: dict[str, Any],
    outcome: FeatureOutcome,
    details: str | None = None,
) -> FeatureResult:
    return FeatureResult(
        feature_id=str(feature["id"]),
        expected_status=str(feature["status"]),
        import_check=str(feature["import_check"]),
        evidence=str(feature["evidence"]),
        outcome=outcome,
        details=redact(details) if details else None,
    )


def _not_verified(features: tuple[dict[str, Any], ...], reason: str) -> list[FeatureResult]:
    return [_feature_result(feature, FeatureOutcome.NOT_VERIFIED, reason) for feature in features]


def _evaluate_features(
    planned: PlannedImport,
    target: CertificationTarget,
    work_dir: Path,
) -> list[FeatureResult]:
    results: list[FeatureResult] = []
    for feature in planned.features:
        expected_status = str(feature["status"])
        if expected_status == "placeholder":
            results.append(
                _feature_result(
                    feature,
                    FeatureOutcome.EXPECTED_GAP,
                    "The format matrix records this feature as a placeholder.",
                )
            )
            continue

        try:
            check = target.verify_feature(feature, work_dir)
        except NotImplementedError:
            results.append(
                _feature_result(
                    feature,
                    FeatureOutcome.NOT_VERIFIED,
                    "No certification verifier is registered for this feature.",
                )
            )
            continue
        except Exception as exc:
            results.append(
                _feature_result(
                    feature,
                    FeatureOutcome.FAILED,
                    f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        results.append(_verified_feature_result(feature, check))
    return results


def _verified_feature_result(
    feature: dict[str, Any],
    check: FeatureCheck,
) -> FeatureResult:
    if check.outcome == FeatureOutcome.EXPECTED_GAP:
        return _feature_result(
            feature,
            FeatureOutcome.FAILED,
            check.details or "Verifier reported a gap for a non-placeholder feature.",
        )
    return _feature_result(feature, check.outcome, check.details)


def _reimport_error(reimport: ReimportInfo | None) -> str | None:
    if reimport is None:
        return "Re-export evidence is missing."
    if reimport.status == ImportStatus.ERROR:
        return reimport.message or "Re-export errored."
    if reimport.status != ImportStatus.PASSED:
        return reimport.message or f"Re-export status: {reimport.status.value}"
    if reimport.exit_code != 0:
        return f"Re-export exit code: {reimport.exit_code}"
    return None


def _case_status(import_result: ImportResult, features: list[FeatureResult]) -> CaseStatus:
    if import_result.status == ImportStatus.ERROR:
        return CaseStatus.ERROR
    if import_result.status != ImportStatus.PASSED:
        return CaseStatus.FAILED
    reimport = import_result.reimport
    if reimport is not None and reimport.status == ImportStatus.ERROR:
        return CaseStatus.ERROR
    if _reimport_error(reimport) is not None:
        return CaseStatus.FAILED
    if any(
        feature.outcome in {FeatureOutcome.FAILED, FeatureOutcome.NOT_VERIFIED}
        for feature in features
    ):
        return CaseStatus.FAILED
    return CaseStatus.PASSED


def _case_errors(
    import_result: ImportResult,
    features: list[FeatureResult],
) -> list[str]:
    errors: list[str] = []
    if import_result.status != ImportStatus.PASSED:
        errors.append(import_result.message or f"Import status: {import_result.status.value}")
    if import_result.status == ImportStatus.PASSED:
        reimport_error = _reimport_error(import_result.reimport)
        if reimport_error is not None:
            errors.append(f"Re-export: {reimport_error}")
    errors.extend(
        f"{feature.feature_id}: {feature.outcome.value}"
        + (f" ({feature.details})" if feature.details else "")
        for feature in features
        if feature.outcome in {FeatureOutcome.FAILED, FeatureOutcome.NOT_VERIFIED}
    )
    return errors


def _run_import(
    planned: PlannedImport,
    target: CertificationTarget,
    workspace: Path,
    artifact_builder: ArtifactBuilder,
) -> CaseResult:
    artifact = artifact_builder(planned.case, planned.target, workspace)
    import_dir = workspace / "imports" / f"{safe_name(planned.case_id)}-{planned.target}"
    if import_dir.exists():
        shutil.rmtree(import_dir)
    import_dir.mkdir(parents=True)

    environment = planned.environment
    warnings: list[str] = []
    errors: list[str] = []
    started = time.monotonic()

    try:
        environment = target.environment()
        import_result = target.import_artifact(artifact, import_dir)
    except CertificationUnavailable:
        raise
    except Exception as exc:
        import_result = ImportResult(
            status=ImportStatus.ERROR,
            message=f"{type(exc).__name__}: {exc}",
        )

    elapsed = round(time.monotonic() - started, 3)
    if import_result.duration_seconds <= 0:
        import_result = import_result.model_copy(update={"duration_seconds": elapsed})
    import_result = _sanitize_import_result(import_result)

    if import_result.status == ImportStatus.PASSED:
        feature_results = _evaluate_features(planned, target, import_dir)
    else:
        feature_results = _not_verified(
            planned.features,
            "Import did not pass, so the feature was not verified.",
        )

    gap_count = sum(feature.outcome == FeatureOutcome.EXPECTED_GAP for feature in feature_results)
    if gap_count:
        warnings.append(f"{gap_count} feature(s) are expected gaps recorded by the format matrix.")

    errors.extend(_case_errors(import_result, feature_results))
    return CaseResult(
        case_id=planned.case_id,
        source=planned.source,
        target=planned.target,
        status=_case_status(import_result, feature_results),
        environment=environment,
        artifact=ArtifactInfo(
            case_id=artifact.case_id,
            target=artifact.target,
            file_name=artifact.path.name,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
        ),
        import_result=import_result,
        features=feature_results,
        warnings=warnings,
        errors=errors,
    )


def _summary(cases: list[CaseResult]) -> ReportSummary:
    features = [feature for case in cases for feature in case.features]
    return ReportSummary(
        cases_total=len(cases),
        cases_passed=sum(case.status == CaseStatus.PASSED for case in cases),
        cases_failed=sum(case.status != CaseStatus.PASSED for case in cases),
        features_total=len(features),
        features_verified=sum(feature.outcome == FeatureOutcome.VERIFIED for feature in features),
        features_expected_gap=sum(
            feature.outcome == FeatureOutcome.EXPECTED_GAP for feature in features
        ),
        features_not_verified=sum(
            feature.outcome == FeatureOutcome.NOT_VERIFIED for feature in features
        ),
        features_failed=sum(feature.outcome == FeatureOutcome.FAILED for feature in features),
    )


def _report_status(cases: list[CaseResult]) -> ReportStatus:
    if any(case.status == CaseStatus.ERROR for case in cases):
        return ReportStatus.ERROR
    if any(case.status == CaseStatus.FAILED for case in cases):
        return ReportStatus.FAILED
    return ReportStatus.PASSED


def run_certification(
    plan: CertificationPlan,
    workspace: Path,
    target_factory: TargetFactory,
    *,
    artifact_builder: ArtifactBuilder = build_golden_artifact,
    run_id: str | None = None,
    generated_at: datetime | None = None,
) -> CertificationReport:
    """Run every planned import and return a versioned certification report."""
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    generated = generated_at or datetime.now(UTC)
    cases: list[CaseResult] = []

    for planned in plan.imports:
        target = target_factory(planned.target)
        case: CaseResult | None = None
        try:
            case = _run_import(planned, target, workspace, artifact_builder)
        finally:
            try:
                target.close()
            except Exception as exc:
                if case is not None:
                    case.warnings.append(f"Target cleanup failed: {redact(str(exc))}")
        if case is not None:
            cases.append(case)

    return CertificationReport(
        matrix_version=plan.matrix_version,
        run_id=run_id or generated.strftime("%Y%m%dT%H%M%SZ"),
        generated_at=generated,
        status=_report_status(cases),
        cases=cases,
        summary=_summary(cases),
    )


def report_json(report: CertificationReport) -> str:
    return (
        json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


def write_report(report: CertificationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_json(report), encoding="utf-8")
