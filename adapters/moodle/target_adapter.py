"""
Moodle Target Adapter – Converts canonical Course to Moodle backup (.mbz)
"""

import tarfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional
from domain.entities import Course, ContentNode, Assessment, Question, AnswerOption, Asset
from domain.enums import NodeType, AssessmentType

class MoodleTargetAdapter:
    """
    Generates a Moodle backup (.mbz) from a canonical Course.
    """
    def __init__(self):
        self.work_dir: Optional[Path] = None
        self.course: Optional[Course] = None
        self.asset_counter = 1   # for generating activity/module IDs

    def generate_backup(self, course: Course, output_path: str, source_extracted_path: Optional[str] = None) -> str:
        """
        Generate a Moodle .mbz backup file from a canonical Course.
        If source_extracted_path is provided (from the original Moodle or Open edX extraction),
        assets will be copied from there; otherwise only asset metadata is recorded.
        """
        self.course = course
        self.work_dir = Path("data/moodle_backup") / uuid.uuid4().hex
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self.work_dir / "course").mkdir(exist_ok=True)
        (self.work_dir / "sections").mkdir(exist_ok=True)
        (self.work_dir / "activities").mkdir(exist_ok=True)
        (self.work_dir / "files").mkdir(exist_ok=True)

        # Step 1: Write course/course.xml
        self._write_course_xml()

        # Step 2: Write sections and activities
        self._write_sections_and_activities()

        # Step 3: Write question bank (if any)
        self._write_questions_xml()

        # Step 4: Write files.xml and copy assets
        self._write_files_xml()
        if source_extracted_path:
            self._copy_assets(Path(source_extracted_path))

        # Step 5: Write the root moodle_backup.xml
        self._write_moodle_backup_xml()

        # Step 6: Create .mbz archive (gzipped tar)
        output_path = Path(output_path)
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(self.work_dir, arcname=".")
        return str(output_path)

    def _write_course_xml(self):
        """Write course/course.xml with course metadata."""
        root = ET.Element("course")
        ET.SubElement(root, "fullname").text = self.course.title
        ET.SubElement(root, "shortname").text = self.course.metadata.get("shortname", self.course.title[:50])
        ET.SubElement(root, "id").text = str(self.asset_counter)
        self.asset_counter += 1
        ET.SubElement(root, "category").text = "1"
        ET.SubElement(root, "format").text = "topics"
        ET.SubElement(root, "startdate").text = str(int(Path().stat().st_ctime))  # current time
        self._write_xml(self.work_dir / "course" / "course.xml", root)

    def _write_sections_and_activities(self):
        """
        Iterate over content nodes (chapters) → each becomes a section.
        Inside each chapter, verticals become activities.
        """
        section_num = 0
        for chapter in self.course.content_nodes:
            if chapter.node_type != NodeType.CHAPTER:
                continue
            section_num += 1
            # Write section.xml
            section_dir = self.work_dir / "sections" / f"section_{section_num}"
            section_dir.mkdir(exist_ok=True)
            self._write_section_xml(section_dir, section_num, chapter.title or f"Section {section_num}")

            # Process activities inside this section
            # The chapter may contain sequentials → verticals; we flatten to activities
            activities = self._collect_activities(chapter)
            for act in activities:
                self._write_activity(section_dir, act)

    def _collect_activities(self, chapter: ContentNode) -> List[ContentNode]:
        """Flatten chapter → sequentials → verticals → components into a list of activities."""
        activities = []
        for seq in chapter.children:
            if seq.node_type == NodeType.SEQUENTIAL:
                for vert in seq.children:
                    if vert.node_type == NodeType.VERTICAL:
                        for comp in vert.children:
                            activities.append(comp)
        return activities

    def _write_section_xml(self, section_dir: Path, section_num: int, title: str):
        root = ET.Element("section")
        ET.SubElement(root, "id").text = str(section_num)
        ET.SubElement(root, "number").text = str(section_num - 1)  # 0‑based
        ET.SubElement(root, "name").text = title
        ET.SubElement(root, "summary").text = ""
        ET.SubElement(root, "sequence").text = ""  # will be filled after activities are written
        self._write_xml(section_dir / "section.xml", root)

    def _write_activity(self, section_dir: Path, comp: ContentNode):
        """
        Write an activity directory and its module.xml + type‑specific XML.
        Returns the cmid (used to update section sequence).
        """
        module_name = self._map_module_name(comp)
        activity_id = self.asset_counter
        self.asset_counter += 1
        act_dir = section_dir.parent.parent / "activities" / f"{module_name}_{activity_id}"
        act_dir.mkdir(exist_ok=True)

        # Write module.xml
        self._write_module_xml(act_dir, module_name, activity_id, section_dir.name)

        # Write type‑specific XML
        if module_name == "page":
            self._write_page_xml(act_dir, comp)
        elif module_name == "label":
            self._write_label_xml(act_dir, comp)
        elif module_name == "url":
            self._write_url_xml(act_dir, comp)
        elif module_name == "quiz":
            self._write_quiz_xml(act_dir, comp)
        elif module_name == "resource":
            self._write_resource_xml(act_dir, comp)
        else:
            # Unsupported – write a simple label warning
            self._write_label_xml(act_dir, comp, warn=True)

        return activity_id

    def _map_module_name(self, comp: ContentNode) -> str:
        if comp.node_type == NodeType.HTML:
            # If it has a lot of content, use 'page', else 'label'
            content = comp.metadata.get("content_html", "")
            if len(content) > 200:
                return "page"
            else:
                return "label"
        elif comp.node_type == NodeType.PROBLEM:
            return "quiz"
        elif comp.node_type == NodeType.VIDEO:
            # Check if it's a YouTube video (has youtube_id)
            if comp.metadata.get("youtube_id"):
                return "url"
            else:
                return "resource"   # video file as resource
        elif comp.node_type == NodeType.LTI:
            return "lti"
        else:
            return "label"

    def _write_module_xml(self, act_dir: Path, module_name: str, activity_id: int, section_name: str):
        root = ET.Element("module")
        root.set("id", str(activity_id))
        root.set("version", "2025100600")
        ET.SubElement(root, "modulename").text = module_name
        ET.SubElement(root, "sectionid").text = section_name.split("_")[1]  # extract section number
        ET.SubElement(root, "sectionnumber").text = section_name.split("_")[1]
        ET.SubElement(root, "added").text = str(int(Path().stat().st_ctime))
        ET.SubElement(root, "visible").text = "1"
        self._write_xml(act_dir / "module.xml", root)

    def _write_page_xml(self, act_dir: Path, comp: ContentNode):
        root = ET.Element("page")
        ET.SubElement(root, "name").text = comp.title or "Page"
        intro = ET.SubElement(root, "intro")
        intro.text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"   # HTML format
        ET.SubElement(root, "content").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "contentformat").text = "1"
        self._write_xml(act_dir / "page.xml", root)

    def _write_label_xml(self, act_dir: Path, comp: ContentNode, warn: bool = False):
        root = ET.Element("label")
        ET.SubElement(root, "name").text = comp.title or "Label"
        intro = ET.SubElement(root, "intro")
        if warn:
            intro.text = "<p>This component could not be fully converted.</p>" + comp.metadata.get("content_html", "")
        else:
            intro.text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        self._write_xml(act_dir / "label.xml", root)

    def _write_url_xml(self, act_dir: Path, comp: ContentNode):
        root = ET.Element("url")
        ET.SubElement(root, "name").text = comp.title or "Link"
        ET.SubElement(root, "externalurl").text = comp.metadata.get("externalurl", "")
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        self._write_xml(act_dir / "url.xml", root)

    def _write_quiz_xml(self, act_dir: Path, comp: ContentNode):
        root = ET.Element("quiz")
        ET.SubElement(root, "name").text = comp.title or "Quiz"
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        ET.SubElement(root, "timeopen").text = "0"
        ET.SubElement(root, "timeclose").text = "0"
        ET.SubElement(root, "timelimit").text = "0"
        # We will add question instances after questions.xml is written.
        # Placeholder: we'll store a reference and later add instances.
        self._write_xml(act_dir / "quiz.xml", root)

    def _write_resource_xml(self, act_dir: Path, comp: ContentNode):
        root = ET.Element("resource")
        ET.SubElement(root, "name").text = comp.title or "Resource"
        ET.SubElement(root, "intro").text = comp.metadata.get("content_html", "")
        ET.SubElement(root, "introformat").text = "1"
        # For a file resource, we'll reference an asset via inforef.
        self._write_xml(act_dir / "resource.xml", root)

    def _write_questions_xml(self):
        """Write questions.xml from canonical assessments/questions/answer_options."""
        if not self.course.questions:
            return
        root = ET.Element("quiz")   # Moodle questions.xml root is <quiz>
        # Group questions by assessment (category)
        # For simplicity, create one question category per assessment
        category_id = 1
        for assessment in self.course.assessments:
            cat = ET.SubElement(root, "question", type="category")
            ET.SubElement(cat, "category").text = f"category_{category_id}"
            ET.SubElement(cat, "info").text = assessment.title
            category_id += 1

            # Get questions for this assessment
            for q in self.course.questions:
                if q.assessment_id != assessment.assessment_id:
                    continue
                self._write_single_question(root, q)

        self._write_xml(self.work_dir / "questions.xml", root)

    def _write_single_question(self, root: ET.Element, q: Question):
        """Append a <question> element to root."""
        q_elem = ET.SubElement(root, "question", type=q.question_type)
        ET.SubElement(q_elem, "name").text = q.question_id[:50]
        ET.SubElement(q_elem, "questiontext").text = q.prompt_text or ""
        ET.SubElement(q_elem, "defaultgrade").text = str(q.points)
        ET.SubElement(q_elem, "penalty").text = "0.1"
        ET.SubElement(q_elem, "hidden").text = "0"

        if q.question_type in ("multichoice", "truefalse"):
            # Add answer options
            opts = [opt for opt in self.course.answer_options if opt.question_id == q.question_id]
            for i, opt in enumerate(opts):
                ans = ET.SubElement(q_elem, "answer", fraction="100" if opt.is_correct else "0")
                ET.SubElement(ans, "text").text = opt.text
                ET.SubElement(ans, "feedback").text = ""
        elif q.question_type == "shortanswer":
            # Assume we have correct answers in metadata
            correct_answers = q.metadata.get("correct_answers", [])
            for ans_text in correct_answers:
                ans = ET.SubElement(q_elem, "answer", fraction="100")
                ET.SubElement(ans, "text").text = ans_text
        elif q.question_type == "numerical":
            correct = q.metadata.get("correct_answer")
            if correct is not None:
                ans = ET.SubElement(q_elem, "answer", fraction="100")
                ET.SubElement(ans, "text").text = str(correct)
                ET.SubElement(ans, "tolerance").text = "0"
        # For essay, description, etc., do minimal
        else:
            ET.SubElement(q_elem, "answer", fraction="0").text = "Review required"

    def _write_files_xml(self):
        """Write global files.xml from course.assets."""
        root = ET.Element("files")
        for asset in self.course.assets:
            file_elem = ET.SubElement(root, "file")
            ET.SubElement(file_elem, "id").text = asset.asset_id
            ET.SubElement(file_elem, "contenthash").text = asset.checksum or asset.asset_id
            ET.SubElement(file_elem, "filename").text = Path(asset.path).name
            ET.SubElement(file_elem, "filepath").text = "/"
            ET.SubElement(file_elem, "mimetype").text = asset.mime_type or "application/octet-stream"
        self._write_xml(self.work_dir / "files.xml", root)

    def _copy_assets(self, source_extracted: Path):
        """Copy files from source extraction into files/ with content‑addressed directory."""
        for asset in self.course.assets:
            # asset.path could be relative to source_extracted
            src = source_extracted / asset.path
            if not src.exists():
                continue
            # Compute contenthash (use SHA‑1 as Moodle does)
            import hashlib
            content = src.read_bytes()
            hash_hex = hashlib.sha1(content).hexdigest()
            subdir = hash_hex[:2]
            dest_dir = self.work_dir / "files" / subdir
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / hash_hex
            if not dest.exists():
                dest.write_bytes(content)

    def _write_moodle_backup_xml(self):
        """Write the root manifest moodle_backup.xml."""
        root = ET.Element("moodle_backup")
        info = ET.SubElement(root, "information")
        # Minimal contents – enough for Moodle to restore
        ET.SubElement(info, "name").text = self.course.title
        ET.SubElement(info, "moodle_version").text = "2025100600"
        ET.SubElement(info, "backup_version").text = "2025100600"
        ET.SubElement(info, "backup_release").text = "4.5"
        # Add course contents section
        contents = ET.SubElement(info, "contents")
        course_elem = ET.SubElement(contents, "course")
        ET.SubElement(course_elem, "title").text = self.course.title
        ET.SubElement(course_elem, "directory").text = "course"
        sections_elem = ET.SubElement(contents, "sections")
        for section_num in range(1, len([n for n in self.course.content_nodes if n.node_type == NodeType.CHAPTER]) + 1):
            sec = ET.SubElement(sections_elem, "section")
            ET.SubElement(sec, "section_id").text = str(section_num)
            ET.SubElement(sec, "title").text = f"Section {section_num}"
            ET.SubElement(sec, "directory").text = f"sections/section_{section_num}"
        self._write_xml(self.work_dir / "moodle_backup.xml", root)

    def _write_xml(self, path: Path, root: ET.Element):
        """Write XML with declaration and UTF‑8 encoding."""
        tree = ET.ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)
