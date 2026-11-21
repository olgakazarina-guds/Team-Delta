from __future__ import annotations

import hashlib
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
    assert any(
        n.node_type.value == "html" and "Hello" in n.metadata.get("content_html", "") for n in nodes
    )
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
    assert numerical.metadata.get("tolerance") is None
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

    manifest_path = extract_dir / "moodle_backup.xml"
    assert manifest_path.read_text(encoding="utf-8").startswith(
        '<?xml version="1.0" encoding="UTF-8"?>'
    )
    assert (extract_dir / "course" / "roles.xml").is_file()
    for activity_dir in (extract_dir / "activities").iterdir():
        assert (activity_dir / "roles.xml").is_file()
        assert (activity_dir / "grades.xml").is_file()
    manifest = ET.parse(manifest_path).getroot()
    activities = manifest.findall(".//contents/activities/activity")
    assert activities
    section_files = list((extract_dir / "sections").glob("section_*/section.xml"))
    assert section_files
    section = ET.parse(section_files[0]).getroot()
    assert section.findtext("sequence")
    questions = ET.parse(extract_dir / "questions.xml").getroot()
    assert questions.tag == "question_categories"
    categories = questions.findall("question_category")
    assert len(categories) >= 2
    top_category = next(category for category in categories if category.findtext("parent") == "0")
    assert top_category.find("question_bank_entries") is not None
    assert not top_category.findall(".//question")
    child_categories = [
        category for category in categories if category.findtext("parent") == top_category.get("id")
    ]
    assert child_categories
    for category in child_categories:
        assert category.findtext("contextid")
        assert category.findtext("contextlevel") == "50"
    entries = questions.findall("question_category/question_bank_entries/question_bank_entry")
    assert entries
    for entry in entries:
        assert entry.findtext("questioncategoryid")
        version = entry.find("question_version/question_versions")
        assert version is not None
        assert version.findtext("version")
        assert version.findtext("status") == "ready"
        question = version.find("questions/question")
        assert question is not None
        assert question.findtext("qtype")
        assert question.find("version") is None
        assert question.find("hidden") is None

    course_root = ET.parse(extract_dir / "course" / "course.xml").getroot()
    assert course_root.get("contextid") == course_root.get("id")
    course_inforef = ET.parse(extract_dir / "course" / "inforef.xml").getroot()
    referenced_files = {
        file_ref.findtext("id") for file_ref in course_inforef.findall("fileref/file")
    }
    referenced_categories = {
        category_ref.findtext("id")
        for category_ref in course_inforef.findall("question_categoryref/question_category")
    }
    assert referenced_files
    assert referenced_categories == {category.get("id") for category in categories}

    files_root = ET.parse(extract_dir / "files.xml").getroot()
    file_records = files_root.findall("file")
    assert "handout.pdf" in {record.findtext("filename") for record in file_records}
    handout = next(
        record for record in file_records if record.findtext("filename") == "handout.pdf"
    )
    assert handout.findtext("component") == "course"
    assert handout.findtext("filearea") == "summary"
    assert handout.findtext("contextid") == course_root.get("id")
    assert handout.get("id") in referenced_files

    module_context_ids = {
        ET.parse(activity).getroot().get("contextid")
        for activity in (extract_dir / "activities").glob("*/module.xml")
    }
    module_files = [
        record for record in file_records if (record.findtext("component") or "").startswith("mod_")
    ]
    for record in module_files:
        assert record.findtext("contextid") in module_context_ids

    forum_settings = ET.parse(next(extract_dir.glob("activities/forum_*/forum.xml"))).getroot()
    assert forum_settings.findtext("forum/assesstimestart") == "0"
    assert forum_settings.findtext("forum/assesstimefinish") == "0"

    workshop_settings = ET.parse(
        next(extract_dir.glob("activities/workshop_*/workshop.xml"))
    ).getroot()
    assert workshop_settings.findtext("workshop/strategy") == "accumulative"
    assert workshop_settings.findtext("workshop/submissionstart") == "0"
    assert workshop_settings.findtext("workshop/assessmentend") == "0"

    for quiz_file in (extract_dir / "activities").glob("quiz_*/quiz.xml"):
        activity = ET.parse(quiz_file).getroot()
        quiz_settings = activity.find("quiz")
        assert quiz_settings is not None
        assert quiz_settings.findtext("password") == ""
        assert quiz_settings.findtext("subnet") == ""
        assert quiz_settings.findtext("browsersecurity") == "-"
        instances = quiz_settings.findall("question_instances/question_instance")
        assert instances
        for instance in instances:
            reference = instance.find("question_reference")
            assert reference is not None
            assert instance.find("questionid") is None
            assert reference.findtext("component") == "mod_quiz"
            assert reference.findtext("questionarea") == "slot"
            assert reference.findtext("usingcontextid") == activity.get("contextid")
            assert reference.findtext("questionbankentryid") in {
                entry.get("id") for entry in entries
            }


def test_generated_moodle_quiz_references_survive_reparse(openedx_archive: Path, tmp_path: Path):
    parsed = ParseService().parse(str(openedx_archive), "openedx", str(tmp_path / "extract"))
    course = TransformService().transform(parsed, "openedx", "job-openedx")
    output = Path(
        MoodleTargetAdapter().generate_backup(
            course, str(tmp_path / "out.mbz"), parsed["extracted_path"]
        )
    )

    reparsed = ParseService().parse(str(output), "moodle", str(tmp_path / "reparse"))
    roundtrip = TransformService().transform(reparsed, "moodle", "job-roundtrip")
    assert len(roundtrip.questions) == len(course.questions)
    assert {q.question_type for q in roundtrip.questions} == {
        q.question_type for q in course.questions
    }


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

    assert (extract_dir / "course.xml").exists()
    assert (extract_dir / "scorm").is_dir()
    scorm_files = list((extract_dir / "scorm").glob("*.xml"))
    assert scorm_files
    scorm_root = ET.parse(scorm_files[0]).getroot()
    assert scorm_root.tag == "scorm"
    package_path = extract_dir / str(scorm_root.get("scorm_package_path"))
    assert package_path.is_file()
    package_meta = json.loads(str(scorm_root.get("package_meta")))
    assert package_meta["size"] == package_path.stat().st_size
    assert package_meta["sha1"] == hashlib.sha1(package_path.read_bytes()).hexdigest()
    assert scorm_root.get("index_page_path") == "index.html"
    url_name = ET.parse(extract_dir / "course.xml").getroot().get("url_name")
    policy_dir = extract_dir / "policies" / url_name
    assert (policy_dir / "policy.json").exists()
    assert (policy_dir / "grading_policy.json").exists()
    assert list((extract_dir / "static").rglob("*"))
    assets_policy = json.loads(
        (extract_dir / "policies" / "assets.json").read_text(encoding="utf-8")
    )
    assert {"doc.pdf", "clip.mp4", "package.zip"} <= set(assets_policy)
    for name, asset in assets_policy.items():
        assert asset["filename"].startswith("asset-v1:")
        assert asset["filename"].endswith(f"@{name}")
        assert (extract_dir / "static" / name).is_file()
    problem_files = list((extract_dir / "problem").glob("*.xml"))
    assert problem_files
    problem_xml = problem_files[0].read_text(encoding="utf-8")
    assert "choiceresponse" in problem_xml or "multiplechoiceresponse" in problem_xml
    assert "stringresponse" in problem_xml
    assert "numericalresponse" in problem_xml
    assert 'type="tolerance"' in problem_xml
    assert 'default="0.01"' in problem_xml
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
    file_records = [record for record in all_file_records if record.findtext("filename") != "."]
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
    records_by_name = {record.findtext("filename"): record for record in file_records}
    for record in file_records:
        contenthash = record.findtext("contenthash")
        assert (extract_dir / "files" / contenthash[:2] / contenthash).exists()
    assert records_by_name["doc.pdf"].findtext("component") == "mod_resource"
    assert records_by_name["doc.pdf"].findtext("filearea") == "content"
    assert int(records_by_name["doc.pdf"].findtext("itemid")) > 0
    assert records_by_name["clip.mp4"].findtext("component") == "mod_resource"
    assert records_by_name["package.zip"].findtext("component") == "mod_scorm"
    assert records_by_name["package.zip"].findtext("filearea") == "package"
    assert records_by_name["package.zip"].findtext("itemid") == "0"

    scorm_activity = ET.parse(next(extract_dir.glob("activities/scorm_*/scorm.xml"))).getroot()
    scorm_settings = scorm_activity.find("scorm")
    assert scorm_settings is not None
    assert scorm_settings.findtext("launch").isdigit()
    assert scorm_settings.findtext("scoes/sco/launch") == "index.html"
    assert scorm_settings.findtext("timeopen") == "0"
    assert scorm_settings.findtext("timeclose") == "0"
    assert scorm_settings.findtext("md5hash") == "0" * 32
    assert scorm_settings.findtext("options") == ""

    resource_dirs = list((extract_dir / "activities").glob("resource_*"))
    assert len(resource_dirs) == 2
    assert all((d / "inforef.xml").exists() for d in resource_dirs)

    activity_files = [
        path
        for path in (extract_dir / "activities").glob("*/*.xml")
        if path.name not in ("module.xml", "inforef.xml", "roles.xml", "grades.xml")
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
