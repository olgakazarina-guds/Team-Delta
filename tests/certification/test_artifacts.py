from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.certification.artifacts import build_golden_artifact
from tests.golden.corpus import load_manifest, valid_cases


def test_builds_a_target_artifact_from_the_golden_corpus(tmp_path: Path):
    manifest = load_manifest()
    case = next(case for case in valid_cases(manifest) if case["id"] == "moodle/core")

    artifact = build_golden_artifact(case, "openedx", tmp_path)

    assert artifact.path.is_file()
    assert artifact.path.name == "moodle-core.tar.gz"
    assert artifact.sha256 == hashlib.sha256(artifact.path.read_bytes()).hexdigest()
    assert artifact.size_bytes == artifact.path.stat().st_size


@pytest.mark.parametrize(
    ("case_id", "target"),
    [("moodle/core", "openedx"), ("openedx/core", "moodle")],
)
def test_builds_artifacts_with_a_relative_workspace(
    case_id: str, target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    manifest = load_manifest()
    case = next(case for case in valid_cases(manifest) if case["id"] == case_id)

    artifact = build_golden_artifact(case, target, Path("workspace"))

    assert artifact.path.is_absolute()
    assert artifact.path.is_file()


def test_rejects_a_target_that_the_case_does_not_generate(tmp_path: Path):
    manifest = load_manifest()
    case = next(case for case in valid_cases(manifest) if case["id"] == "moodle/core")

    with pytest.raises(ValueError, match="does not generate"):
        build_golden_artifact(case, "moodle", tmp_path)
