from __future__ import annotations

import json
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

from adapters.moodle.target_adapter import MoodleTargetAdapter
from adapters.openedx.target_adapter import OpenEdxTargetAdapter
from core.parse import ParseService
from core.transform import TransformService


def _all_nodes(nodes):
    for node in nodes:
        yield node
        yield from _all_nodes(node.children)


def test_openedx_parse_and_transform(openedx_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(openedx_archive), "openedx", str(tmp_path / "extract"))
    course = TransformService().transform(parsed, "openedx", "job-openedx")

    nodes = list(_all_nodes(course.content_nodes))
    assert any(n.node_type.value == "html" and "Hello" in n.metadata.get("content_html", "") for n in nodes)
    video = next(n for n in nodes if n.node_type.value == "video")
    assert video.metadata["youtube_id"] == "abc12345678"
    assert any(n.node_type.value == "forum" for n in nodes)
    assert any(n.node_type.value == "openassessment" for n in nodes)
    assert {q.question_type for q in course.questions} >= {
        "multichoice",
        "multiselect",
        "shortanswer",
        "numerical",
    }
    shortanswer = next(q for q in course.questions if q.question_type == "shortanswer")
    assert shortanswer.metadata["correct_answers"] == ["42"]
    numerical = next(q for q in course.questions if q.question_type == "numerical")
    assert numerical.metadata["correct_answer"] == "3.14"
    assert any(a.metadata.get("original_filename") == "handout.pdf" for a in course.assets)


def test_moodle_parse_and_transform(moodle_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(moodle_archive), "moodle", str(tmp_path / "extract"))
    course = TransformService().transform(parsed, "moodle", "job-moodle")

    nodes = list(_all_nodes(course.content_nodes))
    assert any(n.node_type.value == "scorm" for n in nodes)
    assert any(n.node_type.value == "video" for n in nodes)
    assert any(n.node_type.value == "problem" for n in nodes)
    assert any(n.node_type.value == "html" for n in nodes)
    assert {q.question_type for q in course.questions} >= {
        "multichoice",
        "truefalse",
        "shortanswer",
        "numerical",
    }
    assert any(a.metadata.get("is_scorm") for a in course.assets)
    assert any(a.metadata.get("is_video") for a in course.assets)


def test_openedx_to_moodle_target(openedx_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(openedx_archive), "openedx", str(tmp_path / "extract"))
    course = TransformService().transform(parsed, "openedx", "job-openedx")
    output = Path(
        MoodleTargetAdapter().generate_backup(
            course, str(tmp_path / "out.mbz"), parsed["extracted_path"]
        )
    )

    extract_dir = tmp_path / "moodle-out"
    extract_dir.mkdir()
    with tarfile.open(output, "r:gz") as archive:
        archive.extractall(extract_dir, filter="data")

    manifest = ET.parse(extract_dir / "moodle_backup.xml").getroot()
    activities = manifest.findall(".//contents/activities/activity")
    assert activities
    section_files = list((extract_dir / "sections").glob("section_*/section.xml"))
    assert section_files
    section = ET.parse(section_files[0]).getroot()
    assert section.findtext("sequence")
    questions = ET.parse(extract_dir / "questions.xml").getroot()
    assert questions.tag == "question_categories"
    assert questions.findall(".//question")

    files_root = ET.parse(extract_dir / "files.xml").getroot()
    assert "handout.pdf" in {record.findtext("filename") for record in files_root.findall("file")}


def test_moodle_to_openedx_target(moodle_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(moodle_archive), "moodle", str(tmp_path / "extract"))
    course = TransformService().transform(parsed, "moodle", "job-moodle")
    output = Path(
        OpenEdxTargetAdapter().generate_export(
            course, str(tmp_path / "out.tar.gz"), parsed["extracted_path"]
        )
    )

    extract_dir = tmp_path / "openedx-out"
    extract_dir.mkdir()
    with tarfile.open(output, "r:gz") as archive:
        archive.extractall(extract_dir, filter="data")

    assert (extract_dir / "course" / "course.xml").exists()
    assert (extract_dir / "course" / "scormxblock").exists()
    url_name = ET.parse(extract_dir / "course" / "course.xml").getroot().get(
        "url_name"
    )
    policy_dir = extract_dir / "course" / "policies" / url_name
    assert (policy_dir / "policy.json").exists()
    assert (policy_dir / "grading_policy.json").exists()
    assert list((extract_dir / "course" / "static").rglob("*"))
    assets_policy = json.loads(
        (extract_dir / "course" / "policies" / "assets.json").read_text(encoding="utf-8")
    )
    assert {"doc.pdf", "clip.mp4", "package.zip"} <= set(assets_policy)
    for name, asset in assets_policy.items():
        assert asset["filename"].startswith("asset-v1:")
        assert asset["filename"].endswith(f"@{name}")
        assert (extract_dir / "course" / "static" / name).is_file()
    problem_files = list((extract_dir / "course" / "problem").glob("*.xml"))
    assert problem_files
    problem_xml = problem_files[0].read_text(encoding="utf-8")
    assert "choiceresponse" in problem_xml or "multiplechoiceresponse" in problem_xml
    assert "stringresponse" in problem_xml
    assert "numericalresponse" in problem_xml
    assert "<textinput" not in problem_xml
    assert "<numericalinput" not in problem_xml


def test_moodle_to_moodle_target(moodle_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(moodle_archive), "moodle", str(tmp_path / "extract"))
    course = TransformService().transform(parsed, "moodle", "job-moodle")
    output = Path(
        MoodleTargetAdapter().generate_backup(
            course, str(tmp_path / "roundtrip.mbz"), parsed["extracted_path"]
        )
    )

    extract_dir = tmp_path / "moodle-roundtrip"
    extract_dir.mkdir()
    with tarfile.open(output, "r:gz") as archive:
        archive.extractall(extract_dir, filter="data")

    files_root = ET.parse(extract_dir / "files.xml").getroot()
    all_file_records = files_root.findall("file")
    file_records = [
        record for record in all_file_records if record.findtext("filename") != "."
    ]
    directory_records = [
        record for record in all_file_records if record.findtext("filename") == "."
    ]
    assert len(file_records) == 3
    assert directory_records
    assert {record.findtext("filename") for record in file_records} == {
        "doc.pdf",
        "clip.mp4",
        "package.zip",
    }
    records_by_name = {
        record.findtext("filename"): record for record in file_records
    }
    for record in file_records:
        contenthash = record.findtext("contenthash")
        assert (extract_dir / "files" / contenthash[:2] / contenthash).exists()
    assert records_by_name["doc.pdf"].findtext("component") == "mod_resource"
    assert records_by_name["doc.pdf"].findtext("filearea") == "content"
    assert int(records_by_name["doc.pdf"].findtext("itemid")) > 0
    assert records_by_name["clip.mp4"].findtext("component") == "mod_resource"
    assert records_by_name["package.zip"].findtext("component") == "mod_scorm"
    assert records_by_name["package.zip"].findtext("filearea") == "package"

    resource_dirs = list((extract_dir / "activities").glob("resource_*"))
    assert len(resource_dirs) == 2
    assert all((d / "inforef.xml").exists() for d in resource_dirs)

    activity_files = [
        path
        for path in (extract_dir / "activities").glob("*/*.xml")
        if path.name not in ("module.xml", "inforef.xml")
    ]
    assert activity_files
    for path in activity_files:
        root = ET.parse(path).getroot()
        assert root.tag == "activity"
        assert root.get("moduleid")
        assert root.get("modulename")
        assert len(root) == 1

    for filename in (
        "gradebook.xml",
        "roles.xml",
        "groups.xml",
        "scales.xml",
        "outcomes.xml",
        "completion.xml",
        "grade_history.xml",
        "badges.xml",
    ):
        assert (extract_dir / filename).exists()

    archive_index = (extract_dir / ".ARCHIVE_INDEX").read_text(encoding="utf-8")
    assert archive_index.startswith("Moodle archive file index. Count: ")
    assert "moodle_backup.xml\tf\t" in archive_index
