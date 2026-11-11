"""Moodle Target Adapter – Converts a canonical Course to a Moodle .mbz backup."""

from __future__ import annotations

import hashlib
import tarfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.archive_utils import resolve_under
from core.config import get_settings
from domain.entities import AnswerOption, Asset, ContentNode, Course, Question
from domain.enums import NodeType

MOODLE_VERSION = "2024100700"
BACKUP_VERSION = "2024100700"
BACKUP_RELEASE = "4.5"


class MoodleTargetAdapter:
    """Generate a Moodle backup archive from a canonical Course."""

    def __init__(self, work_dir: str | Path | None = None):
        self.work_root = (
            Path(work_dir) if work_dir is not None else get_settings().work_dir
        )
        self.work_dir: Optional[Path] = None
        self.course: Optional[Course] = None
        self._next_id = 1
        self.course_id = 1
        self.section_records: List[Dict[str, Any]] = []
        self.activity_records: List[Dict[str, Any]] = []
        self.file_records: List[Dict[str, Any]] = []
        self.asset_file_ids: Dict[str, int] = {}
        self.question_ids: Dict[str, int] = {}
        self.question_categories: Dict[str, int] = {}
        self.quiz_module_ids: Dict[str, int] = {}
        self._current_module_id = 0
        self._current_module_name = ""

    def generate_backup(
        self,
        course: Course,
        output_path: str,
        source_extracted_path: Optional[str] = None,
    ) -> str:
        """Generate a Moodle .mbz backup from a canonical Course."""
        self._reset_state()
        self.course = course
        self.work_dir = self.work_root / "moodle" / uuid.uuid4().hex
        self.work_dir.mkdir(parents=True, exist_ok=True)

        for subdir in ("course", "sections", "activities", "files"):
            (self.work_dir / subdir).mkdir(exist_ok=True)

        self._prepare_file_records(source_extracted_path)
        self._prepare_question_ids()
        self._write_course_xml()
        self._write_sections_and_activities()
        self._write_questions_xml()
        self._write_files_xml()
        self._write_moodle_backup_xml()
        self._write_auxiliary_files()
        self._write_archive_index()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(self.work_dir, arcname=".")
        return str(output_path)

    def _reset_state(self) -> None:
        """Clear all per-export state so one adapter instance is reusable."""
        self.work_dir = None
        self.course = None
        self._next_id = 1
        self.course_id = 1
        self.section_records = []
        self.activity_records = []
        self.file_records = []
        self.asset_file_ids = {}
        self.question_ids = {}
        self.question_categories = {}
        self.quiz_module_ids = {}
        self._current_module_id = 0
        self._current_module_name = ""

    def _new_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def _write_course_xml(self) -> None:
        self.course_id = self._new_id()
        root = ET.Element("course", id=str(self.course_id))
        ET.SubElement(root, "shortname").text = self.course.metadata.get(
            "shortname", self.course.title[:50]
        )
        ET.SubElement(root, "fullname").text = self.course.title
        ET.SubElement(root, "idnumber").text = ""
        ET.SubElement(root, "summary").text = ""
        ET.SubElement(root, "summaryformat").text = "1"
        ET.SubElement(root, "format").text = "topics"
        ET.SubElement(root, "showgrades").text = "1"
        ET.SubElement(root, "newsitems").text = "0"
        ET.SubElement(root, "startdate").text = str(int(time.time()))
        ET.SubElement(root, "enddate").text = "0"
        ET.SubElement(root, "marker").text = "0"
        ET.SubElement(root, "maxbytes").text = "0"
        ET.SubElement(root, "legacyfiles").text = "0"
        ET.SubElement(root, "showreports").text = "0"
        ET.SubElement(root, "visible").text = "1"
        ET.SubElement(root, "groupmode").text = "0"
        ET.SubElement(root, "groupmodeforce").text = "0"
        ET.SubElement(root, "defaultgroupingid").text = "0"
        ET.SubElement(root, "lang").text = self.course.metadata.get("lang") or "en"
        ET.SubElement(root, "theme").text = ""
        ET.SubElement(root, "timecreated").text = str(int(time.time()))
        ET.SubElement(root, "timemodified").text = str(int(time.time()))
        ET.SubElement(root, "requested").text = "0"
        ET.SubElement(root, "enablecompletion").text = "1"
        ET.SubElement(root, "completionnotify").text = "0"
        ET.SubElement(root, "hiddensections").text = "0"
        ET.SubElement(root, "coursedisplay").text = "0"
        category = ET.SubElement(root, "category", id="1")
        ET.SubElement(category, "name").text = "Default"
        ET.SubElement(category, "description").text = ""
        ET.SubElement(root, "tags")
        self._write_xml(self.work_dir / "course" / "course.xml", root)

    def _write_sections_and_activities(self) -> None:
        section_number = 0
        for chapter in sorted(self.course.content_nodes, key=lambda n: n.position):
            if chapter.node_type != NodeType.CHAPTER:
                continue
            section_number += 1
            section_id = self._new_id()
            section_dir = self.work_dir / "sections" / f"section_{section_id}"
            section_dir.mkdir(parents=True, exist_ok=True)

            sequence = []
            for comp in self._collect_activities(chapter):
                module_id = self._write_activity(section_id, section_number, comp)
                sequence.append(module_id)

            self.section_records.append({
                "id": section_id,
                "number": section_number,
                "title": chapter.title or f"Section {section_number}",
                "directory": f"sections/section_{section_id}",
                "sequence": sequence,
            })
            self._write_section_xml(section_dir, section_id, section_number, chapter.title, sequence)

    def _collect_activities(self, chapter: ContentNode) -> List[ContentNode]:
        activities = []
        for seq in sorted(chapter.children, key=lambda n: n.position):
            if seq.node_type != NodeType.SEQUENTIAL:
                continue
            for vert in sorted(seq.children, key=lambda n: n.position):
                if vert.node_type == NodeType.VERTICAL:
                    activities.extend(sorted(vert.children, key=lambda n: n.position))
        return activities

    def _write_section_xml(
        self,
        section_dir: Path,
        section_id: int,
        section_number: int,
        title: Optional[str],
        sequence: List[int],
    ) -> None:
        root = ET.Element("section", id=str(section_id))
        ET.SubElement(root, "number").text = str(section_number - 1)
        ET.SubElement(root, "name").text = title or f"Section {section_number}"
        ET.SubElement(root, "summary").text = ""
        ET.SubElement(root, "summaryformat").text = "1"
        ET.SubElement(root, "sequence").text = ",".join(str(i) for i in sequence)
        ET.SubElement(root, "visible").text = "1"
        ET.SubElement(root, "availabilityjson").text = "$@NULL@$"
        ET.SubElement(root, "timemodified").text = "0"
        self._write_xml(section_dir / "section.xml", root)

    def _write_activity(
        self, section_id: int, section_number: int, comp: ContentNode
    ) -> int:
        module_name = self._map_module_name(comp)
        module_id = self._new_id()
        self._current_module_id = module_id
        self._current_module_name = module_name
        act_dir = self.work_dir / "activities" / f"{module_name}_{module_id}"
        act_dir.mkdir(parents=True, exist_ok=True)

        self._write_module_xml(
            act_dir, module_name, module_id, section_id, section_number
        )
        if module_name == "page":
            self._write_page_xml(act_dir, comp)
        elif module_name == "label":
            self._write_label_xml(act_dir, comp)
        elif module_name == "url":
            self._write_url_xml(act_dir, comp)
        elif module_name == "quiz":
            self._write_quiz_xml(act_dir, comp, module_id)
        elif module_name == "resource":
            self._write_resource_xml(act_dir, comp)
        elif module_name == "forum":
            self._write_forum_xml(act_dir, comp)
        elif module_name == "workshop":
            self._write_workshop_xml(act_dir, comp)
        elif module_name == "scorm":
            self._write_scorm_xml(act_dir, comp)
        else:
            self._write_label_xml(act_dir, comp, warn=True)

        self.activity_records.append({
            "module_id": module_id,
            "section_id": section_id,
            "module_name": module_name,
            "title": comp.title or module_name.title(),
            "directory": f"activities/{module_name}_{module_id}",
        })
        return module_id

    def _map_module_name(self, comp: ContentNode) -> str:
        if comp.node_type in (NodeType.HTML, NodeType.PAGE):
            if comp.metadata.get("moodle_module") == "page":
                return "page"
            content = comp.metadata.get("content_html", "")
            return "page" if len(content) > 200 else "label"
        if comp.node_type == NodeType.PROBLEM:
            return "quiz"
        if comp.node_type == NodeType.VIDEO:
            return "url" if comp.metadata.get("youtube_id") else "resource"
        if comp.node_type == NodeType.SCORM:
            return "scorm"
        if comp.node_type == NodeType.FORUM:
            return "forum"
        if comp.node_type == NodeType.OPENASSESSMENT:
            return "workshop"
        if comp.node_type == NodeType.ACTIVITY:
            return "resource" if comp.metadata.get("asset_id") else "url"
        if comp.node_type == NodeType.LTI:
            return "url"
        return "label"

    def _write_module_xml(
        self,
        act_dir: Path,
        module_name: str,
        module_id: int,
        section_id: int,
        section_number: int,
    ) -> None:
        root = ET.Element("module", id=str(module_id), version=MOODLE_VERSION)
        ET.SubElement(root, "modulename").text = module_name
        ET.SubElement(root, "sectionid").text = str(section_id)
        ET.SubElement(root, "sectionnumber").text = str(section_number - 1)
        ET.SubElement(root, "idnumber").text = ""
        ET.SubElement(root, "added").text = str(int(time.time()))
        ET.SubElement(root, "score").text = "0"
        ET.SubElement(root, "indent").text = "0"
        ET.SubElement(root, "visible").text = "1"
        ET.SubElement(root, "visibleoncoursepage").text = "1"
        ET.SubElement(root, "visibleold").text = "1"
        ET.SubElement(root, "groupmode").text = "0"
        ET.SubElement(root, "groupingid").text = "0"
        ET.SubElement(root, "completion").text = "2"
        ET.SubElement(root, "completiongradeitemnumber").text = "0"
        ET.SubElement(root, "completionview").text = "0"
        ET.SubElement(root, "completionexpected").text = "0"
        ET.SubElement(root, "availability").text = "$@NULL@$"
        ET.SubElement(root, "showdescription").text = "1"
        ET.SubElement(root, "tags")
        self._write_xml(act_dir / "module.xml", root)

    def _write_page_xml(self, act_dir: Path, comp: ContentNode) -> None:
        content = comp.metadata.get("content_html", "")
        intro = comp.metadata.get("intro_html", "")
        root = ET.Element("page", id=str(self._new_id()))
        ET.SubElement(root, "name").text = comp.title or "Page"
        ET.SubElement(root, "intro").text = intro
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "content").text = content
        ET.SubElement(root, "contentformat").text = "1"
        ET.SubElement(root, "legacyfiles").text = "0"
        ET.SubElement(root, "legacyfileslast").text = "$@NULL@$"
        ET.SubElement(root, "display").text = "0"
        ET.SubElement(root, "displayoptions").text = "a:1:{s:10:\"printintro\";i:1;}"
        ET.SubElement(root, "revision").text = "1"
        ET.SubElement(root, "timemodified").text = str(int(time.time()))
        self._write_activity_xml(act_dir, "page.xml", root)

    def _write_label_xml(
        self, act_dir: Path, comp: ContentNode, warn: bool = False
    ) -> None:
        intro = comp.metadata.get("content_html", "")
        if warn:
            intro = "<p>This component could not be fully converted.</p>" + intro
        root = ET.Element("label", id=str(self._new_id()))
        ET.SubElement(root, "name").text = comp.title or "Label"
        ET.SubElement(root, "intro").text = intro
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "timemodified").text = str(int(time.time()))
        self._write_activity_xml(act_dir, "label.xml", root)

    def _write_url_xml(self, act_dir: Path, comp: ContentNode) -> None:
        external_url = comp.metadata.get("externalurl", "")
        if not external_url and comp.metadata.get("youtube_id"):
            external_url = (
                f"https://www.youtube.com/watch?v={comp.metadata['youtube_id']}"
            )
        root = ET.Element("url", id=str(self._new_id()))
        ET.SubElement(root, "name").text = comp.title or "Link"
        ET.SubElement(root, "externalurl").text = external_url
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "display").text = "0"
        ET.SubElement(root, "displayoptions").text = "a:2:{s:10:\"printintro\";i:1;s:17:\"printintrofield\";i:1;}"
        ET.SubElement(root, "timemodified").text = str(int(time.time()))
        self._write_activity_xml(act_dir, "url.xml", root)

    def _write_quiz_xml(
        self, act_dir: Path, comp: ContentNode, module_id: int
    ) -> None:
        assessment = next(
            (
                a
                for a in self.course.assessments
                if a.assessment_id == comp.assessment_id
            ),
            None,
        )
        questions = (
            [q for q in self.course.questions if q.assessment_id == assessment.assessment_id]
            if assessment
            else []
        )
        root = ET.Element("quiz", id=str(self._new_id()))
        ET.SubElement(root, "name").text = comp.title or "Quiz"
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "timeopen").text = "0"
        ET.SubElement(root, "timeclose").text = "0"
        ET.SubElement(root, "timelimit").text = "0"
        ET.SubElement(root, "overduehandling").text = "autoabandon"
        ET.SubElement(root, "graceperiod").text = "0"
        ET.SubElement(root, "preferredbehaviour").text = "deferredfeedback"
        ET.SubElement(root, "attempts_number").text = "0"
        ET.SubElement(root, "grademethod").text = "1"
        ET.SubElement(root, "decimalpoints").text = "2"
        ET.SubElement(root, "questiondecimalpoints").text = "-1"
        ET.SubElement(root, "questionsperpage").text = "0"
        ET.SubElement(root, "navmethod").text = "free"
        ET.SubElement(root, "shuffleanswers").text = "1"
        ET.SubElement(root, "sumgrades").text = str(
            sum(q.points for q in questions)
        )
        ET.SubElement(root, "grade").text = "10.00000"
        ET.SubElement(root, "timemodified").text = str(int(time.time()))

        instances = ET.SubElement(root, "question_instances")
        for slot, question in enumerate(questions, start=1):
            numeric_id = self.question_ids.get(question.question_id)
            if numeric_id is None:
                continue
            instance = ET.SubElement(instances, "question_instance", id=str(self._new_id()))
            ET.SubElement(instance, "slot").text = str(slot)
            ET.SubElement(instance, "page").text = "1"
            ET.SubElement(instance, "requireprevious").text = "0"
            ET.SubElement(instance, "questionid").text = str(numeric_id)
            ET.SubElement(instance, "questioncategoryid").text = "$@NULL@$"
            ET.SubElement(instance, "includingsubcategories").text = "$@NULL@$"
            ET.SubElement(instance, "maxmark").text = f"{question.points:.7f}"
            ET.SubElement(instance, "tags")

        if assessment:
            self.quiz_module_ids[assessment.assessment_id] = module_id
        self._write_activity_xml(act_dir, "quiz.xml", root)

    def _write_resource_xml(self, act_dir: Path, comp: ContentNode) -> None:
        instance_id = self._new_id()
        root = ET.Element("resource", id=str(instance_id))
        ET.SubElement(root, "name").text = comp.title or "Resource"
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "tobemigrated").text = "0"
        ET.SubElement(root, "legacyfiles").text = "0"
        ET.SubElement(root, "legacyfileslast").text = "$@NULL@$"
        ET.SubElement(root, "display").text = "0"
        ET.SubElement(root, "displayoptions").text = "a:1:{s:10:\"printintro\";i:1;}"
        ET.SubElement(root, "filterfiles").text = "0"
        ET.SubElement(root, "revision").text = "1"
        ET.SubElement(root, "timemodified").text = str(int(time.time()))
        self._write_activity_xml(act_dir, "resource.xml", root)
        asset_id = comp.metadata.get("asset_id")
        self._write_inforef(act_dir, asset_id)
        self._assign_asset_file(asset_id, "mod_resource", "content", instance_id)

    def _write_scorm_xml(self, act_dir: Path, comp: ContentNode) -> None:
        settings = comp.metadata.get("scorm_settings", {})
        instance_id = self._new_id()
        root = ET.Element("scorm", id=str(instance_id))
        ET.SubElement(root, "name").text = comp.title or "SCORM Package"
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "scormtype").text = "local"
        ET.SubElement(root, "reference").text = ""
        version = settings.get("version", "")
        ET.SubElement(root, "version").text = (
            "SCORM_2004" if "2004" in version else "SCORM_1.2"
        )
        ET.SubElement(root, "launch").text = settings.get("launch", "")
        ET.SubElement(root, "skipview").text = settings.get("skipview", "0")
        ET.SubElement(root, "auto").text = settings.get("auto", "0")
        ET.SubElement(root, "grademethod").text = settings.get("grademethod", "1")
        ET.SubElement(root, "maxgrade").text = settings.get("maxgrade", "100")
        ET.SubElement(root, "timemodified").text = str(int(time.time()))
        self._write_activity_xml(act_dir, "scorm.xml", root)
        asset_id = comp.metadata.get("asset_id")
        self._write_inforef(act_dir, asset_id)
        self._assign_asset_file(asset_id, "mod_scorm", "package", 0)

    def _write_forum_xml(self, act_dir: Path, comp: ContentNode) -> None:
        root = ET.Element("forum", id=str(self._new_id()))
        ET.SubElement(root, "name").text = comp.title or "Forum"
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "type").text = "general"
        ET.SubElement(root, "timemodified").text = str(int(time.time()))
        self._write_activity_xml(act_dir, "forum.xml", root)

    def _write_workshop_xml(self, act_dir: Path, comp: ContentNode) -> None:
        root = ET.Element("workshop", id=str(self._new_id()))
        ET.SubElement(root, "name").text = comp.title or "Workshop"
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "timemodified").text = str(int(time.time()))
        self._write_activity_xml(act_dir, "workshop.xml", root)

    def _write_inforef(self, act_dir: Path, asset_id: Optional[str]) -> None:
        if not asset_id:
            return
        file_id = self.asset_file_ids.get(asset_id)
        if file_id is None:
            return
        root = ET.Element("inforef")
        file_ref = ET.SubElement(root, "fileref")
        file_elem = ET.SubElement(file_ref, "file")
        ET.SubElement(file_elem, "id").text = str(file_id)
        self._write_xml(act_dir / "inforef.xml", root)

    def _assign_asset_file(
        self, asset_id: Optional[str], component: str, filearea: str, itemid: int
    ) -> None:
        """Attach an asset's file record to the module that uses it."""
        if not asset_id:
            return
        for record in self.file_records:
            if record["asset_id"] == asset_id:
                record["component"] = component
                record["filearea"] = filearea
                record["itemid"] = itemid
                return

    def _prepare_question_ids(self) -> None:
        for assessment in self.course.assessments:
            questions = [
                q for q in self.course.questions if q.assessment_id == assessment.assessment_id
            ]
            if not questions:
                continue
            self.question_categories[assessment.assessment_id] = self._new_id()
            for question in questions:
                if question.question_id not in self.question_ids:
                    self.question_ids[question.question_id] = self._new_id()

    def _write_questions_xml(self) -> None:
        root = ET.Element("question_categories")
        written_question_ids: set[str] = set()
        for assessment in self.course.assessments:
            category_id = self.question_categories.get(assessment.assessment_id)
            if category_id is None:
                continue
            questions = [
                q for q in self.course.questions if q.assessment_id == assessment.assessment_id
            ]
            category = ET.SubElement(root, "question_category", id=str(category_id))
            ET.SubElement(category, "name").text = assessment.title or "Default"
            ET.SubElement(category, "contextid").text = str(category_id)
            ET.SubElement(category, "contextlevel").text = "50"
            ET.SubElement(category, "contextinstanceid").text = str(
                self._course_id()
            )
            ET.SubElement(category, "info").text = (
                f"Questions for {assessment.title or 'assessment'}"
            )
            ET.SubElement(category, "infoformat").text = "0"
            ET.SubElement(category, "stamp").text = f"lms-converter+{uuid.uuid4().hex}"
            ET.SubElement(category, "parent").text = "0"
            ET.SubElement(category, "sortorder").text = "999"
            ET.SubElement(category, "idnumber").text = "$@NULL@$"
            questions_elem = ET.SubElement(category, "questions")
            for question in questions:
                numeric_id = self.question_ids.get(question.question_id)
                if numeric_id is None or question.question_id in written_question_ids:
                    continue
                written_question_ids.add(question.question_id)
                self._write_single_question(questions_elem, question, numeric_id)

        self._write_xml(self.work_dir / "questions.xml", root)

    def _course_id(self) -> int:
        return self.course_id

    def _write_single_question(
        self, parent: ET.Element, question: Question, numeric_id: int
    ) -> None:
        qtype = question.question_type
        moodle_type = (
            "truefalse"
            if qtype == "truefalse"
            else "shortanswer"
            if qtype in ("shortanswer", "text_input")
            else "numerical"
            if qtype == "numerical"
            else "essay"
            if qtype in ("essay", "description")
            else "multichoice"
        )
        q_elem = ET.SubElement(parent, "question", id=str(numeric_id))
        ET.SubElement(q_elem, "parent").text = "0"
        ET.SubElement(q_elem, "name").text = (question.prompt_text or "Question")[:50]
        ET.SubElement(q_elem, "questiontext").text = question.prompt_text or ""
        ET.SubElement(q_elem, "questiontextformat").text = "1"
        ET.SubElement(q_elem, "generalfeedback").text = ""
        ET.SubElement(q_elem, "generalfeedbackformat").text = "1"
        ET.SubElement(q_elem, "defaultmark").text = f"{question.points:.7f}"
        ET.SubElement(q_elem, "penalty").text = "0.3333333"
        ET.SubElement(q_elem, "qtype").text = moodle_type
        ET.SubElement(q_elem, "length").text = "1"
        ET.SubElement(q_elem, "stamp").text = f"lms-converter+{uuid.uuid4().hex}"
        ET.SubElement(q_elem, "version").text = f"lms-converter+{uuid.uuid4().hex}"
        ET.SubElement(q_elem, "hidden").text = "0"
        ET.SubElement(q_elem, "timecreated").text = str(int(time.time()))
        ET.SubElement(q_elem, "timemodified").text = str(int(time.time()))
        ET.SubElement(q_elem, "createdby").text = "0"
        ET.SubElement(q_elem, "modifiedby").text = "0"
        ET.SubElement(q_elem, "idnumber").text = "$@NULL@$"

        options = [
            opt for opt in self.course.answer_options if opt.question_id == question.question_id
        ]

        if moodle_type == "multichoice":
            plugin = ET.SubElement(q_elem, "plugin_qtype_multichoice_question")
            answers_elem = ET.SubElement(plugin, "answers")
            answer_ids = []
            for option in options:
                answer_id = self._new_id()
                answer_ids.append((answer_id, option))
                self._write_moodle_answer(
                    answers_elem, answer_id, option.text, option.is_correct
                )
            multi = ET.SubElement(plugin, "multichoice", id=str(self._new_id()))
            ET.SubElement(multi, "layout").text = "0"
            ET.SubElement(multi, "single").text = "0" if qtype == "multiselect" else "1"
            ET.SubElement(multi, "shuffleanswers").text = "1"
            ET.SubElement(multi, "correctfeedback").text = ""
            ET.SubElement(multi, "correctfeedbackformat").text = "1"
            ET.SubElement(multi, "partiallycorrectfeedback").text = ""
            ET.SubElement(multi, "partiallycorrectfeedbackformat").text = "1"
            ET.SubElement(multi, "incorrectfeedback").text = ""
            ET.SubElement(multi, "incorrectfeedbackformat").text = "1"
            ET.SubElement(multi, "answernumbering").text = "abc"
            ET.SubElement(multi, "shownumcorrect").text = "1"

        elif moodle_type == "truefalse":
            plugin = ET.SubElement(q_elem, "plugin_qtype_truefalse_question")
            answers_elem = ET.SubElement(plugin, "answers")
            if not options:
                options = [
                    AnswerOption(
                        option_id=f"{question.question_id}-true",
                        question_id=question.question_id,
                        text="True",
                        is_correct=True,
                    ),
                    AnswerOption(
                        option_id=f"{question.question_id}-false",
                        question_id=question.question_id,
                        text="False",
                        is_correct=False,
                    ),
                ]
            true_option = next(
                (o for o in options if o.text.strip().lower() == "true"), None
            )
            false_option = next(
                (o for o in options if o.text.strip().lower() == "false"), None
            )
            if true_option is None:
                true_option = AnswerOption(
                    option_id=f"{question.question_id}-true",
                    question_id=question.question_id,
                    text="True",
                    is_correct=not any(o.is_correct for o in options),
                )
            if false_option is None:
                false_option = AnswerOption(
                    option_id=f"{question.question_id}-false",
                    question_id=question.question_id,
                    text="False",
                    is_correct=not any(o.is_correct for o in options),
                )
            true_id = self._new_id()
            false_id = self._new_id()
            self._write_moodle_answer(
                answers_elem, true_id, true_option.text, true_option.is_correct
            )
            self._write_moodle_answer(
                answers_elem, false_id, false_option.text, false_option.is_correct
            )
            truefalse = ET.SubElement(plugin, "truefalse", id=str(self._new_id()))
            ET.SubElement(truefalse, "trueanswer").text = str(true_id)
            ET.SubElement(truefalse, "falseanswer").text = str(false_id)

        elif moodle_type == "shortanswer":
            plugin = ET.SubElement(q_elem, "plugin_qtype_shortanswer_question")
            answers_elem = ET.SubElement(plugin, "answers")
            correct_answers = question.metadata.get("correct_answers", [])
            for text in correct_answers:
                self._write_moodle_answer(
                    answers_elem, self._new_id(), str(text), True
                )
            shortanswer = ET.SubElement(plugin, "shortanswer", id=str(self._new_id()))
            ET.SubElement(shortanswer, "usecase").text = "0"

        elif moodle_type == "numerical":
            plugin = ET.SubElement(q_elem, "plugin_qtype_numerical_question")
            answers_elem = ET.SubElement(plugin, "answers")
            correct = question.metadata.get("correct_answer")
            if correct is None and question.metadata.get("correct_answers"):
                correct = question.metadata["correct_answers"][0]
            if correct is not None:
                answer_id = self._new_id()
                self._write_moodle_answer(
                    answers_elem, answer_id, str(correct), True
                )
                tolerance = ET.SubElement(
                    answers_elem.find("answer"), "tolerance"
                )
                tolerance.text = str(question.metadata.get("tolerance", "0"))
            numerical = ET.SubElement(plugin, "numerical", id=str(self._new_id()))
            ET.SubElement(numerical, "tolerance").text = str(
                question.metadata.get("tolerance", "0")
            )

        else:
            plugin = ET.SubElement(q_elem, "plugin_qtype_essay_question")
            essay = ET.SubElement(plugin, "essay", id=str(self._new_id()))
            ET.SubElement(essay, "responseformat").text = "1"
            ET.SubElement(essay, "responserequired").text = "1"
            ET.SubElement(essay, "responsefieldlines").text = "15"
            ET.SubElement(essay, "attachments").text = "0"
            ET.SubElement(essay, "attachmentsrequired").text = "0"

        ET.SubElement(q_elem, "question_hints")
        ET.SubElement(q_elem, "tags")

    def _write_moodle_answer(
        self,
        answers_elem: ET.Element,
        answer_id: int,
        text: str,
        is_correct: bool,
    ) -> None:
        answer = ET.SubElement(answers_elem, "answer", id=str(answer_id))
        ET.SubElement(answer, "answertext").text = text
        ET.SubElement(answer, "answerformat").text = "1"
        ET.SubElement(answer, "fraction").text = "1.0000000" if is_correct else "0.0000000"
        ET.SubElement(answer, "feedback").text = ""
        ET.SubElement(answer, "feedbackformat").text = "1"

    def _prepare_file_records(self, source_extracted_path: Optional[str]) -> None:
        source_root = Path(source_extracted_path) if source_extracted_path else None
        for asset in self.course.assets:
            content = b""
            source = None
            if source_root is not None:
                try:
                    source = resolve_under(source_root, asset.path)
                except ValueError:
                    source = None
            if source is not None and source.is_file():
                content = source.read_bytes()
                contenthash = hashlib.sha1(content).hexdigest()
            else:
                contenthash = asset.checksum or hashlib.sha1(
                    asset.path.encode("utf-8")
                ).hexdigest()

            file_id = self._new_id()
            self.asset_file_ids[asset.asset_id] = file_id
            record = {
                "id": file_id,
                "asset_id": asset.asset_id,
                "contenthash": contenthash,
                "filename": asset.metadata.get("original_filename")
                or Path(asset.path).name
                or f"file_{file_id}",
                "filepath": "/",
                "filesize": len(content),
                "mimetype": asset.mime_type or "application/octet-stream",
                "component": "course",
                "filearea": "content",
                "itemid": 0,
            }
            self.file_records.append(record)

            if content:
                dest_dir = self.work_dir / "files" / contenthash[:2]
                dest_dir.mkdir(parents=True, exist_ok=True)
                (dest_dir / contenthash).write_bytes(content)

    def _write_files_xml(self) -> None:
        root = ET.Element("files")
        directory_keys = set()
        for record in self.file_records:
            self._write_file_record(root, record)
            key = (record["component"], record["filearea"], record["itemid"])
            if key in directory_keys:
                continue
            directory_keys.add(key)
            directory_record = {
                "id": self._new_id(),
                "contenthash": hashlib.sha1(b"").hexdigest(),
                "filepath": record["filepath"],
                "filename": ".",
                "filesize": 0,
                "mimetype": "$@NULL@$",
                "component": record["component"],
                "filearea": record["filearea"],
                "itemid": record["itemid"],
            }
            self._write_file_record(root, directory_record)
        if directory_keys:
            empty_hash = hashlib.sha1(b"").hexdigest()
            empty_dir = self.work_dir / "files" / empty_hash[:2]
            empty_dir.mkdir(parents=True, exist_ok=True)
            (empty_dir / empty_hash).write_bytes(b"")
        self._write_xml(self.work_dir / "files.xml", root)

    def _write_file_record(self, root: ET.Element, record: Dict[str, Any]) -> None:
        file_elem = ET.SubElement(root, "file", id=str(record["id"]))
        ET.SubElement(file_elem, "contenthash").text = record["contenthash"]
        ET.SubElement(file_elem, "contextid").text = str(self._course_id())
        ET.SubElement(file_elem, "component").text = record["component"]
        ET.SubElement(file_elem, "filearea").text = record["filearea"]
        ET.SubElement(file_elem, "itemid").text = str(record["itemid"])
        ET.SubElement(file_elem, "filepath").text = record["filepath"]
        ET.SubElement(file_elem, "filename").text = record["filename"]
        ET.SubElement(file_elem, "userid").text = "0"
        ET.SubElement(file_elem, "filesize").text = str(record["filesize"])
        ET.SubElement(file_elem, "mimetype").text = record["mimetype"]
        ET.SubElement(file_elem, "status").text = "0"
        ET.SubElement(file_elem, "timecreated").text = str(int(time.time()))
        ET.SubElement(file_elem, "timemodified").text = str(int(time.time()))
        ET.SubElement(file_elem, "source").text = record["filename"]
        ET.SubElement(file_elem, "author").text = ""
        ET.SubElement(file_elem, "license").text = ""
        ET.SubElement(file_elem, "sortorder").text = "0"
        ET.SubElement(file_elem, "repositorytype").text = "$@NULL@$"
        ET.SubElement(file_elem, "repositoryid").text = "$@NULL@$"
        ET.SubElement(file_elem, "reference").text = "$@NULL@$"

    def _write_moodle_backup_xml(self) -> None:
        root = ET.Element("moodle_backup")
        info = ET.SubElement(root, "information")
        ET.SubElement(info, "name").text = f"backup-moodle2-course-{self._course_id()}-{uuid.uuid4().hex[:8]}.mbz"
        ET.SubElement(info, "moodle_version").text = MOODLE_VERSION
        ET.SubElement(info, "moodle_release").text = BACKUP_RELEASE
        ET.SubElement(info, "backup_version").text = BACKUP_VERSION
        ET.SubElement(info, "backup_release").text = BACKUP_RELEASE
        ET.SubElement(info, "backup_date").text = str(int(time.time()))
        ET.SubElement(info, "mnet_remoteusers").text = "0"
        ET.SubElement(info, "include_files").text = "1"
        ET.SubElement(info, "include_file_references_to_external_content").text = "0"
        ET.SubElement(info, "original_wwwroot").text = ""
        ET.SubElement(info, "original_site_identifier_hash").text = ""
        ET.SubElement(info, "original_course_id").text = str(self._course_id())
        ET.SubElement(info, "original_course_format").text = "topics"
        ET.SubElement(info, "original_course_fullname").text = self.course.title
        ET.SubElement(info, "original_course_shortname").text = self.course.metadata.get(
            "shortname", self.course.title[:50]
        )
        ET.SubElement(info, "original_course_startdate").text = str(int(time.time()))
        ET.SubElement(info, "original_course_enddate").text = "0"
        ET.SubElement(info, "original_course_contextid").text = str(self._course_id())
        ET.SubElement(info, "original_system_contextid").text = "1"

        details = ET.SubElement(info, "details")
        detail = ET.SubElement(details, "detail", backup_id=uuid.uuid4().hex)
        ET.SubElement(detail, "type").text = "course"
        ET.SubElement(detail, "format").text = "moodle2"
        ET.SubElement(detail, "interactive").text = "1"
        ET.SubElement(detail, "mode").text = "10"
        ET.SubElement(detail, "execution").text = "1"
        ET.SubElement(detail, "executiontime").text = "0"

        contents = ET.SubElement(info, "contents")
        activities_elem = ET.SubElement(contents, "activities")
        for record in self.activity_records:
            activity = ET.SubElement(activities_elem, "activity")
            ET.SubElement(activity, "moduleid").text = str(record["module_id"])
            ET.SubElement(activity, "sectionid").text = str(record["section_id"])
            ET.SubElement(activity, "modulename").text = record["module_name"]
            ET.SubElement(activity, "title").text = record["title"]
            ET.SubElement(activity, "directory").text = record["directory"]

        sections_elem = ET.SubElement(contents, "sections")
        for record in self.section_records:
            section = ET.SubElement(sections_elem, "section")
            ET.SubElement(section, "sectionid").text = str(record["id"])
            ET.SubElement(section, "title").text = record["title"]
            ET.SubElement(section, "directory").text = record["directory"]

        course_elem = ET.SubElement(contents, "course")
        ET.SubElement(course_elem, "courseid").text = str(self._course_id())
        ET.SubElement(course_elem, "title").text = self.course.title
        ET.SubElement(course_elem, "directory").text = "course"

        settings = ET.SubElement(info, "settings")
        for name, value in (
            ("filename", f"backup-moodle2-course-{self._course_id()}.mbz"),
            ("activities", "1"),
            ("sections", "1"),
            ("files", "1"),
            ("users", "0"),
            ("anonymize", "0"),
        ):
            setting = ET.SubElement(settings, "setting")
            ET.SubElement(setting, "level").text = "root"
            ET.SubElement(setting, "name").text = name
            ET.SubElement(setting, "value").text = value

        self._write_xml(self.work_dir / "moodle_backup.xml", root)

    def _write_archive_index(self) -> None:
        entries: List[str] = []
        for path in sorted(self.work_dir.rglob("*")):
            relative = path.relative_to(self.work_dir).as_posix()
            if relative == ".ARCHIVE_INDEX":
                continue
            if path.is_dir():
                entries.append(f"{relative}/\td\t0\t?")
            else:
                entries.append(
                    f"{relative}\tf\t{path.stat().st_size}\t{int(path.stat().st_mtime)}"
                )
        content = (
            f"Moodle archive file index. Count: {len(entries)}\n"
            + "\n".join(entries)
            + "\n"
        )
        (self.work_dir / ".ARCHIVE_INDEX").write_text(content, encoding="utf-8")

    def _write_auxiliary_files(self) -> None:
        """Write the empty root-level XML files a Moodle backup normally contains."""
        auxiliary = {
            "gradebook.xml": (
                "gradebook",
                ["attributes", "grade_categories", "grade_items", "grade_letters", "grade_settings"],
            ),
            "roles.xml": ("roles_definition", []),
            "groups.xml": ("groups", ["groupings"]),
            "scales.xml": ("scales_definition", []),
            "outcomes.xml": ("outcomes_definition", []),
            "completion.xml": ("course_completion", []),
            "grade_history.xml": ("grade_history", ["grade_grades"]),
            "badges.xml": ("badges", []),
        }
        for filename, (root_name, children) in auxiliary.items():
            root = ET.Element(root_name)
            for child_name in children:
                ET.SubElement(root, child_name)
            self._write_xml(self.work_dir / filename, root)
        (self.work_dir / "moodle_backup.log").write_text("", encoding="utf-8")

    def _write_activity_xml(
        self, act_dir: Path, filename: str, inner: ET.Element
    ) -> None:
        activity_id = inner.get("id") or str(self._new_id())
        activity = ET.Element(
            "activity",
            id=activity_id,
            moduleid=str(self._current_module_id),
            modulename=self._current_module_name,
            contextid=str(self.course_id),
        )
        activity.append(inner)
        self._write_xml(act_dir / filename, activity)

    def _write_xml(self, path: Path, root: ET.Element) -> None:
        tree = ET.ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)
