from __future__ import annotations

import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.moodle.target_adapter import MoodleTargetAdapter
from adapters.openedx.target_adapter import OpenEdxTargetAdapter
from core.parse import ParseService
from core.transform import TransformService
from domain.entities import (
    AnswerOption,
    Assessment,
    Asset,
    Course,
    Question,
)
from domain.enums import AssessmentType, SourceSystem


def _extract(archive_path: Path, target: Path) -> Path:
    target.mkdir()
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(target, filter="data")
    return target


def _all_node_ids(nodes):
    for node in nodes:
        yield node.node_id
        yield from _all_node_ids(node.children)


def test_moodle_page_roundtrip_does_not_duplicate_body(moodle_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(moodle_archive), "moodle", str(tmp_path / "extract"))
    course = TransformService().transform(parsed, "moodle", "job-page")
    output = Path(
        MoodleTargetAdapter().generate_backup(
            course, str(tmp_path / "page.mbz"), parsed["extracted_path"]
        )
    )
    root = _extract(output, tmp_path / "page-out")
    page_file = next(root.glob("activities/page_*/page.xml"))
    page = ET.parse(page_file).getroot().find("page")

    assert page is not None
    assert page.findtext("intro") == "Intro"
    assert page.findtext("content") == "<p>Page content</p>"


def test_truefalse_answers_are_mapped_by_text_not_position(tmp_path: Path):
    course = Course(
        course_id="course-tf",
        title="TF Course",
        source_system=SourceSystem.MOODLE,
        assessments=[
            Assessment(
                assessment_id="assessment-tf",
                course_id="course-tf",
                title="TF Quiz",
                assessment_type=AssessmentType.QUIZ,
            )
        ],
        questions=[
            Question(
                question_id="question-tf",
                assessment_id="assessment-tf",
                question_type="truefalse",
                prompt_text="Is this correct?",
            )
        ],
        answer_options=[
            AnswerOption(
                option_id="false",
                question_id="question-tf",
                text="False",
                is_correct=True,
            ),
            AnswerOption(
                option_id="true",
                question_id="question-tf",
                text="True",
                is_correct=False,
            ),
        ],
    )

    output = Path(MoodleTargetAdapter().generate_backup(course, str(tmp_path / "tf.mbz")))
    root = _extract(output, tmp_path / "tf-out")
    questions = ET.parse(root / "questions.xml").getroot()
    plugin = questions.find(".//plugin_qtype_truefalse_question")
    assert plugin is not None
    answers = {answer.findtext("answertext"): answer for answer in plugin.findall(".//answer")}
    truefalse = plugin.find("truefalse")
    assert truefalse is not None
    assert truefalse.findtext("trueanswer") == answers["True"].get("id")
    assert truefalse.findtext("falseanswer") == answers["False"].get("id")
    assert answers["False"].findtext("fraction") == "1.0000000"


def test_target_does_not_emit_duplicate_question_ids(tmp_path: Path):
    questions = [
        Question(
            question_id="shared-question",
            assessment_id=assessment_id,
            question_type="shortanswer",
            prompt_text="Shared",
            metadata={"correct_answers": ["42"]},
        )
        for assessment_id in ("assessment-a", "assessment-b")
    ]
    course = Course(
        course_id="course-dup",
        title="Duplicate Question Course",
        source_system=SourceSystem.MOODLE,
        assessments=[
            Assessment(
                assessment_id="assessment-a",
                course_id="course-dup",
                title="A",
                assessment_type=AssessmentType.QUIZ,
            ),
            Assessment(
                assessment_id="assessment-b",
                course_id="course-dup",
                title="B",
                assessment_type=AssessmentType.QUIZ,
            ),
        ],
        questions=questions,
    )

    output = Path(MoodleTargetAdapter().generate_backup(course, str(tmp_path / "dup.mbz")))
    root = _extract(output, tmp_path / "dup-out")
    qroot = ET.parse(root / "questions.xml").getroot()
    ids = [question.get("id") for question in qroot.findall(".//question")]
    assert len(ids) == len(set(ids))


def test_openedx_identity_is_stable_across_job_ids(openedx_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(openedx_archive), "openedx", str(tmp_path / "extract"))
    first = TransformService().transform(parsed, "openedx", "job-one")
    second = TransformService().transform(parsed, "openedx", "job-two")

    assert first.course_id == second.course_id
    assert list(_all_node_ids(first.content_nodes)) == list(_all_node_ids(second.content_nodes))
    assert [q.question_id for q in first.questions] == [q.question_id for q in second.questions]
    assert [a.assessment_id for a in first.assessments] == [
        a.assessment_id for a in second.assessments
    ]


def test_openedx_export_preserves_nested_asset_paths(tmp_path: Path):
    source = tmp_path / "source"
    (source / "static" / "sub").mkdir(parents=True)
    (source / "static" / "sub" / "img.png").write_bytes(b"image")
    course = Course(
        course_id="course-assets",
        title="Asset Course",
        source_system=SourceSystem.OPENEDX,
        assets=[
            Asset(
                asset_id="asset-img",
                course_id="course-assets",
                path="static/sub/img.png",
                mime_type="image/png",
                metadata={"original_filename": "img.png"},
            )
        ],
    )

    output = Path(
        OpenEdxTargetAdapter().generate_export(course, str(tmp_path / "assets.tar.gz"), str(source))
    )
    root = _extract(output, tmp_path / "assets-out")
    assert (root / "static" / "sub" / "img.png").read_bytes() == b"image"


def test_moodle_adapter_can_be_reused_without_state_leak(moodle_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(moodle_archive), "moodle", str(tmp_path / "extract"))
    course = TransformService().transform(parsed, "moodle", "job-reuse")
    adapter = MoodleTargetAdapter()

    first = Path(adapter.generate_backup(course, str(tmp_path / "first.mbz")))
    second = Path(adapter.generate_backup(course, str(tmp_path / "second.mbz")))
    first_root = _extract(first, tmp_path / "first-out")
    second_root = _extract(second, tmp_path / "second-out")

    assert len(list(first_root.glob("sections/section_*"))) == len(
        list(second_root.glob("sections/section_*"))
    )
    assert len(list(first_root.glob("activities/*"))) == len(list(second_root.glob("activities/*")))
