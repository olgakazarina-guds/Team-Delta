"""
Open edX Target Adapter, Converts canonical Course domain objects into 
Open edX export format (.tar.gz).

This adapter handles:
Full course hierarchy (Chapter -> Sequential -> Vertical -> Components)
Assessments with questions and answer options
Asset file copying from Moodle backups
XML generation for all Open edX components (html, problem, video, etc.)
"""

import json
import os
import tarfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Dict, Any, List, Optional

from core.archive_utils import resolve_under
from domain.entities import Course, ContentNode, Assessment, Question, AnswerOption, Asset, RawFragment, MappingNote
from domain.enums import SourceSystem, NodeType, AssessmentType, Severity


class OpenEdxTargetAdapter:
    """
    Adapter for exporting canonical Course objects to Open edX format.

    This class transforms domain entities into Open edX's XML-based course 
    structure and packages them into a tar.gz archive suitable for import 
    into Open edX instances.

    Attributes:
        work_dir: Temporary working directory for export files
        course: The Course domain object being exported
        node_id_map: Mapping from node_id to url_name for XML references
    """

    def __init__(self):
        """Initialize the adapter with empty state."""
        self.work_dir: Optional[Path] = None
        self.course: Optional[Course] = None
        self.node_id_map: Dict[str, str] = {}
        self.asset_paths: Dict[str, str] = {}

    def generate_export(
        self, 
        course: Course, 
        output_path: str, 
        source_extracted_path: Optional[str] = None
    ) -> str:
        """
        Generate an Open edX course export tarball from a canonical Course.
    
        Creates the full directory structure, generates all XML files for 
        course hierarchy and components, copies assets if available, and 
        packages everything into a .tar.gz archive.
    
        Args:
            course: The canonical Course domain object to export
            output_path: Destination path for the .tar.gz file
            source_extracted_path: Optional path to source extraction for copying assets
            
        Returns:
            Absolute path to the generated .tar.gz export file

        Example:
             adapter = OpenEdxTargetAdapter()
             output = adapter.generate_export(course, "output/course.tar.gz")
        """
        # Step 1: Initialize working directory and course state
        self.course = course
        self.node_id_map = {}
        self.asset_paths = self._build_asset_paths()
        self.work_dir = Path("data/openedx_export") / uuid.uuid4().hex
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Step 2: Create Open edX directory structure
        for subdir in ["chapter", "sequential", "vertical", "html", "problem", "video", "openassessment", "discussion", "scormxblock", "course", "static", "policies"]:
            (self.work_dir / subdir).mkdir(parents=True, exist_ok=True)

        # Step 3: Generate root course.xml (course settings)
        self._write_root_course_xml()

        # Step 4: Generate actual course definition (course/{url_name}.xml)
        self._write_actual_course_xml()
        self._write_policies()

        # Step 5: Process content nodes and generate XML for each hierarchy level
        for node in sorted(course.content_nodes, key=lambda n: n.position):
            if node.node_type == NodeType.CHAPTER:
                self._write_chapter(node)

        # Step 6: Copy asset files from source extraction if provided
        if source_extracted_path:
            self._copy_assets(Path(source_extracted_path))

        # Step 7: Package everything into a tar.gz archive
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output_path, "w:gz") as tar:
            # Open edX expects course.xml at the archive root, not under an
            # extra wrapper directory.
            tar.add(self.work_dir, arcname=".")
        return str(output_path)

    def _safe_name(self, name: str, max_len: int = 32) -> str:
        """
        Convert a name to a safe url_name for Open edX.
        
        Removes special characters and truncates to max length. Open edX 
        requires url_names to be alphanumeric with only ., _, - allowed.
        
        Args:
            name: Original name (e.g., course title, chapter title)
            max_len: Maximum length for the safe name
            
        Returns:
            Safe url_name string (e.g., "Introduction_to_Course" or "item")
        """
        safe = "".join(c for c in name if c.isalnum() or c in "._-")
        return safe[:max_len] if safe else "item"

    def _safe_asset_filename(self, asset: Asset) -> str:
        """Return a flat, safe static filename that keeps the file extension."""
        raw = (
            asset.metadata.get("original_filename")
            or Path(asset.path).name
            or asset.asset_id
        )
        safe = "".join(c for c in raw if c.isalnum() or c in "._-")
        if not safe:
            safe = asset.asset_id
        suffix = Path(safe).suffix
        if len(safe) > 120:
            safe = safe[: 120 - len(suffix)] + suffix
        return safe

    def _safe_asset_relative_path(self, asset: Asset) -> str:
        """Return a safe path relative to ``static/``.

        Open edX HTML commonly references nested paths such as
        ``/static/sub/img.png``.  Flattening every asset to its basename breaks
        those references, so native ``static/`` paths are preserved segment by
        segment.  Other source layouts (for example Moodle's content-addressed
        ``files/`` store) use the original filename.
        """
        raw_path = asset.path.replace("\\", "/")
        if raw_path.startswith("static/"):
            relative = raw_path[len("static/"):]
            parts = []
            for part in PurePosixPath(relative).parts:
                if part in ("", "."):
                    continue
                if part == "..":
                    return self._safe_asset_filename(asset)
                safe = "".join(c for c in part if c.isalnum() or c in "._-")
                parts.append(safe or "asset")
            if parts:
                return "/".join(parts)
        return self._safe_asset_filename(asset)

    def _build_asset_paths(self) -> Dict[str, str]:
        """Map asset IDs to unique relative paths under the export's static folder."""
        paths: Dict[str, str] = {}
        used: set[str] = set()
        for asset in self.course.assets:
            name = self._safe_asset_relative_path(asset)
            if name in used:
                parent, _, filename = name.rpartition("/")
                filename = f"{asset.asset_id[:8]}_{filename or name}"
                name = f"{parent}/{filename}" if parent else filename
            used.add(name)
            paths[asset.asset_id] = name
        return paths

    def _asset_static_path(self, asset: Asset) -> str:
        """Return the static URL path for an asset."""
        return self.asset_paths.get(
            asset.asset_id, self._safe_asset_relative_path(asset)
        )

    def _get_url_name(self, node_id: str) -> str:
        """
        Get or generate a url_name for a given node_id.
        
        Maintains a mapping to ensure consistent url_names across the export.
        Generates a new safe name if this node_id hasn't been seen before.
        
        Args:
            node_id: Unique identifier for the content node
            
        Returns:
            url_name string for use in Open edX XML files
        """
        if node_id not in self.node_id_map:
            self.node_id_map[node_id] = self._safe_name(node_id)
        return self.node_id_map[node_id]

    def _write_root_course_xml(self):
        """
        Write the root course.xml file (course settings).
        
        This file defines org, course code, and url_name at the root level.
        Located at: work_dir/course.xml
        """
        root = ET.Element("course")
        root.set("url_name", self._safe_name(self.course.title, 32))
        root.set("org", self.course.metadata.get("org", "Org"))
        root.set("course", self.course.metadata.get("course_code", "Course"))
        self._write_xml(self.work_dir / "course.xml", root)

    def _write_actual_course_xml(self):
        """
        Write the actual course definition file (course/{url_name}.xml).
        
        This file contains the top-level chapter references for the course.
        Open edX uses this to discover all chapters in the course.
        Located at: work_dir/course/{url_name}.xml
        """
        url_name = self._safe_name(self.course.title, 32)
        course_dir = self.work_dir / "course"
        root = ET.Element("course")
        root.set("display_name", self.course.title)
        
        for node in self.course.content_nodes:
            if node.node_type == NodeType.CHAPTER:
                ch = ET.SubElement(root, "chapter")
                ch.set("url_name", self._get_url_name(node.node_id))
        
        self._write_xml(course_dir / f"{url_name}.xml", root)

    def _write_policies(self) -> None:
        """Write the minimal policy files expected in an OLX export."""
        url_name = self._safe_name(self.course.title, 32)
        policy = {
            f"course/{url_name}": {
                "display_name": self.course.title,
                "start": "1970-01-01T00:00:00Z",
            }
        }
        grading_policy = {
            "GRADER": [],
            "GRADE_CUTOFFS": {"Pass": 0.5},
        }
        policy_dir = self.work_dir / "policies"
        course_policy_dir = policy_dir / url_name
        course_policy_dir.mkdir(parents=True, exist_ok=True)
        (course_policy_dir / "policy.json").write_text(
            json.dumps(policy, indent=2), encoding="utf-8"
        )
        (course_policy_dir / "grading_policy.json").write_text(
            json.dumps(grading_policy, indent=2), encoding="utf-8"
        )
        org = self.course.metadata.get("org", "Org")
        course_code = self.course.metadata.get("course_code", "Course")
        assets_policy = {}
        for asset in self.course.assets:
            name = self._asset_static_path(asset)
            assets_policy[name] = {
                "contentType": asset.mime_type or "application/octet-stream",
                "content_son": {
                    "category": "asset",
                    "course": course_code,
                    "name": name,
                    "org": org,
                    "revision": None,
                    "run": url_name,
                    "tag": "c4x",
                },
                "displayname": name,
                "filename": (
                    f"asset-v1:{org}+{course_code}+{url_name}"
                    f"+type@asset+block@{name}"
                ),
                "import_path": None,
                "locked": False,
                "thumbnail_location": None,
            }
        (policy_dir / "assets.json").write_text(
            json.dumps(assets_policy, indent=2), encoding="utf-8"
        )

    def _write_chapter(self, node: ContentNode):
        """
        Write XML for a chapter (Chapter -> Sequential hierarchy).
        
        Creates chapter.xml with sequential references and recursively 
        processes all sequential children.
        Located at: work_dir/chapter/{url_name}.xml
        
        Args:
            node: ContentNode with node_type=CHAPTER
        """
        url_name = self._get_url_name(node.node_id)
        root = ET.Element("chapter")
        root.set("display_name", node.title or "Chapter")
        
        for child in sorted(node.children, key=lambda n: n.position):
            if child.node_type == NodeType.SEQUENTIAL:
                seq = ET.SubElement(root, "sequential")
                seq.set("url_name", self._get_url_name(child.node_id))
        
        self._write_xml(self.work_dir / "chapter" / f"{url_name}.xml", root)
        
        # Recursively process sequential children
        for child in sorted(node.children, key=lambda n: n.position):
            if child.node_type == NodeType.SEQUENTIAL:
                self._write_sequential(child)

    def _write_sequential(self, node: ContentNode):
        """
        Write XML for a sequential (Sequential -> Vertical hierarchy).
        
        Creates sequential.xml with vertical references and recursively 
        processes all vertical children.
        Located at: work_dir/sequential/{url_name}.xml
        
        Args:
            node: ContentNode with node_type=SEQUENTIAL
        """
        url_name = self._get_url_name(node.node_id)
        root = ET.Element("sequential")
        root.set("display_name", node.title or "Sequential")
        
        for child in sorted(node.children, key=lambda n: n.position):
            if child.node_type == NodeType.VERTICAL:
                vert = ET.SubElement(root, "vertical")
                vert.set("url_name", self._get_url_name(child.node_id))
        
        self._write_xml(self.work_dir / "sequential" / f"{url_name}.xml", root)
        
        # Recursively process vertical children
        for child in sorted(node.children, key=lambda n: n.position):
            if child.node_type == NodeType.VERTICAL:
                self._write_vertical(child)

    def _write_vertical(self, node: ContentNode):
        """
        Write XML for a vertical containing components (HTML, Problem, Video).
        
        Creates vertical.xml with component references and generates the 
        component-specific XML files (html.xml, problem.xml, video.xml).
        Located at: work_dir/vertical/{url_name}.xml
        
        Args:
            node: ContentNode with node_type=VERTICAL
        """
        url_name = self._get_url_name(node.node_id)
        root = ET.Element("vertical")
        root.set("display_name", node.title or "Vertical")
        
        for comp in sorted(node.children, key=lambda n: n.position):
            if comp.node_type in (NodeType.HTML, NodeType.PAGE):
                # HTML component
                elem = ET.SubElement(root, "html")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_html(comp)

            elif comp.node_type == NodeType.ACTIVITY:
                # Moodle URL/activity nodes are exported as linked HTML.
                elem = ET.SubElement(root, "html")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_html(comp)

            elif comp.node_type == NodeType.LTI:
                elem = ET.SubElement(root, "html")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_html(comp)
                
            elif comp.node_type == NodeType.PROBLEM:
                # Problem component with assessment link
                elem = ET.SubElement(root, "problem")
                elem.set("url_name", self._get_url_name(comp.node_id))
                
                # Try to find the assessment linked to this component
                assessment = None
                if comp.assessment_id:
                    assessment = next(
                        (a for a in self.course.assessments if a.assessment_id == comp.assessment_id), 
                        None
                    )
                
                if assessment:
                    # Get questions and answer options for this assessment
                    questions = [
                        q for q in self.course.questions 
                        if q.assessment_id == assessment.assessment_id
                    ]
                    answer_options = [
                        opt for opt in self.course.answer_options 
                        if opt.question_id in [q.question_id for q in questions]
                    ]
                    self._write_problem(comp, assessment, questions, answer_options)
                elif comp.metadata.get("problem_data"):
                    # Fallback: Let write the problem directly from stored problem_data
                    self._write_problem_from_data(comp, comp.metadata["problem_data"])
                else:
                    # Fallback: write a placeholder problem
                    self._write_placeholder_problem(comp)
                    
            elif comp.node_type == NodeType.VIDEO:
                # Video component
                elem = ET.SubElement(root, "video")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_video(comp)

            elif comp.node_type == NodeType.SCORM:
                elem = ET.SubElement(root, "scormxblock")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_scorm(comp)
            
            elif comp.node_type == NodeType.OPENASSESSMENT:
                # First, add an HTML component to display the prompt text
                if comp.metadata.get("content_html"):
                    html_prompt = ContentNode(
                        node_id=str(uuid.uuid4()),
                        node_type=NodeType.HTML,
                        title="Workshop Description",
                        parent_id=node.node_id,
                        position=len(node.children),  # append after existing components
                        metadata={"content_html": comp.metadata["content_html"]},
                    )
                    self._write_html(html_prompt)
                    # Add the html reference in the vertical
                    html_elem = ET.SubElement(root, "html")
                    html_elem.set("url_name", self._get_url_name(html_prompt.node_id))
                
                # Then add the openassessment component
                elem = ET.SubElement(root, "openassessment")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_openassessment(comp)

            elif comp.node_type == NodeType.FORUM:
                elem = ET.SubElement(root, "discussion")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_discussion(comp)

        self._write_xml(self.work_dir / "vertical" / f"{url_name}.xml", root)

    def _write_html(self, comp: ContentNode):
        """
        Write HTML component files (.html content + .xml wrapper).
        
        Creates both the HTML content file and the XML wrapper that 
        references it.
        Files: work_dir/html/{url_name}.html + work_dir/html/{url_name}.xml
        
        Args:
            comp: ContentNode with node_type=HTML and content_html metadata
        """
        url_name = self._get_url_name(comp.node_id)
        content = comp.metadata.get("content_html", comp.title or "")
        
        # Write .html file (actual content)
        html_path = self.work_dir / "html" / f"{url_name}.html"
        html_path.write_text(content, encoding="utf-8")
        
        # Write .xml wrapper
        root = ET.Element("html")
        root.set("display_name", comp.title or "HTML")
        root.set("filename", f"{url_name}.html")
        self._write_xml(self.work_dir / "html" / f"{url_name}.xml", root)

    def _write_problem(
        self, 
        comp: ContentNode, 
        assessment: Assessment, 
        questions: List[Question], 
        answer_options: List[AnswerOption]
    ):
        """
        Write problem XML with questions and answer options.
        
        Supports:
        multichoice: single-select (multiplechoiceresponse)
        truefalse: true/false (multiplechoiceresponse)
        shortanswer: text input (stringresponse)
        numerical: numerical input (numericalresponse)
        essay: open response (openassessment - not implemented, placeholder)
        
        Located at: work_dir/problem/{url_name}.xml
        
        Args:
            comp: ContentNode with node_type=PROBLEM
            assessment: Assessment entity linked to this problem
            questions: List of Question entities for this assessment
            answer_options: List of AnswerOption entities for the questions
        """
        url_name = self._get_url_name(comp.node_id)
        root = ET.Element("problem")
        root.set("display_name", assessment.title)

        for q in questions:
            q_options = [opt for opt in answer_options if opt.question_id == q.question_id]
            qtype = q.question_type

            if qtype in ("multichoice", "single-select"):
                self._write_multiple_choice(
                    root, q, q_options, multi_select=False
                )
            elif qtype in ("multiselect", "multi-select"):
                self._write_multiple_choice(
                    root, q, q_options, multi_select=True
                )
            elif qtype == "truefalse":
                if not q_options:
                    q_options = [
                        AnswerOption(
                            option_id=f"{q.question_id}-true",
                            question_id=q.question_id,
                            text="True",
                            is_correct=True,
                        ),
                        AnswerOption(
                            option_id=f"{q.question_id}-false",
                            question_id=q.question_id,
                            text="False",
                            is_correct=False,
                        ),
                    ]
                self._write_multiple_choice(
                    root, q, q_options, multi_select=False
                )
            elif qtype in ("shortanswer", "text_input"):
                correct_answers = q.metadata.get("correct_answers", [])
                self._write_string_response(
                    root, q.prompt_text or "Question", correct_answers
                )
            elif qtype == "numerical":
                correct_answer = q.metadata.get("correct_answer")
                self._write_numerical_response(
                    root,
                    q.prompt_text or "Question",
                    "" if correct_answer is None else str(correct_answer),
                )
            else:
                # Unsupported type (essay, description, etc.) - create placeholder
                multiplechoiceresponse = ET.SubElement(root, "multiplechoiceresponse")
                label = ET.SubElement(multiplechoiceresponse, "label")
                label.text = f"{q.question_type}: {q.prompt_text or 'Question'} (not fully converted)"
                choicegroup = ET.SubElement(
                    multiplechoiceresponse,
                    "choicegroup",
                    type="MultipleChoice",
                )
                choice = ET.SubElement(choicegroup, "choice")
                choice.text = "Review required"
                choice.set("correct", "false")
                choice.set("name", "a")

        self._write_xml(self.work_dir / "problem" / f"{url_name}.xml", root)

    def _write_multiple_choice(
        self,
        root: ET.Element,
        question: Question,
        options: List[AnswerOption],
        multi_select: bool,
    ) -> None:
        """Write either a single-select or multi-select choice response."""
        if multi_select:
            response = ET.SubElement(root, "choiceresponse")
            ET.SubElement(response, "label").text = question.prompt_text or "Question"
            group = ET.SubElement(response, "checkboxgroup")
        else:
            response = ET.SubElement(root, "multiplechoiceresponse")
            ET.SubElement(response, "label").text = question.prompt_text or "Question"
            group = ET.SubElement(
                response, "choicegroup", type="MultipleChoice"
            )

        for idx, opt in enumerate(options):
            choice = ET.SubElement(group, "choice")
            choice.text = opt.text
            choice.set("correct", "true" if opt.is_correct else "false")
            choice.set("name", chr(97 + idx))

    def _write_string_response(
        self, root: ET.Element, prompt: str, correct_answers: List[str]
    ) -> None:
        """Write a standard OLX text input response."""
        response = ET.SubElement(root, "stringresponse")
        response.set("answer", correct_answers[0] if correct_answers else "")
        response.set("type", "ci")
        ET.SubElement(response, "label").text = prompt
        for answer in correct_answers[1:]:
            ET.SubElement(response, "additional_answer").set("answer", answer)
        ET.SubElement(response, "textline", size="20")

    def _write_numerical_response(
        self, root: ET.Element, prompt: str, correct_answer: str
    ) -> None:
        """Write a standard OLX numerical input response."""
        response = ET.SubElement(root, "numericalresponse")
        response.set("answer", correct_answer)
        ET.SubElement(response, "label").text = prompt
        ET.SubElement(response, "formulaequationinput")

    def _write_problem_from_data(self, comp: ContentNode, problem_data: dict):
        """
        Write problem XML directly from stored problem_data dict (fallback).
        
        This method is used when the assessment lookup fails (e.g., during 
        round-trip migration where assessments are not yet linked). It writes
        the problem XML using the data originally parsed from the source.
        
        Args:
            comp: ContentNode with node_type=PROBLEM
            problem_data: Dictionary containing parsed problem data with keys:
                - assessment_title: str
                - questions: list of dicts with 'type', 'prompt', 'answer_options', etc.
        """
        url_name = self._get_url_name(comp.node_id)
        root = ET.Element("problem")
        root.set("display_name", problem_data.get("assessment_title", comp.title or "Problem"))

        for q in problem_data.get("questions", []):
            qtype = q.get("type", "unknown")
            if qtype in ("multichoice", "single-select", "truefalse"):
                self._write_multiple_choice_data(root, q, multi_select=False)
            elif qtype in ("multiselect", "multi-select"):
                self._write_multiple_choice_data(root, q, multi_select=True)
            elif qtype in ("shortanswer", "text_input"):
                self._write_string_response(
                    root,
                    q.get("prompt", "Question"),
                    q.get("correct_answers", []),
                )
            elif qtype == "numerical":
                self._write_numerical_response(
                    root,
                    q.get("prompt", "Question"),
                    str(q.get("correct_answer", "")),
                )
            else:
                multiplechoiceresponse = ET.SubElement(root, "multiplechoiceresponse")
                label = ET.SubElement(multiplechoiceresponse, "label")
                label.text = f"{qtype}: {q.get('prompt', 'Question')} (not fully converted)"
                choicegroup = ET.SubElement(
                    multiplechoiceresponse,
                    "choicegroup",
                    type="MultipleChoice",
                )
                choice = ET.SubElement(choicegroup, "choice")
                choice.text = "Review required"
                choice.set("correct", "false")

        self._write_xml(self.work_dir / "problem" / f"{url_name}.xml", root)

    def _write_multiple_choice_data(
        self, root: ET.Element, question: Dict[str, Any], multi_select: bool
    ) -> None:
        """Write a choice response directly from a parsed problem-data dict."""
        options = question.get("answer_options", [])
        if question.get("type") == "truefalse" and not options:
            options = [
                {"text": "True", "is_correct": True},
                {"text": "False", "is_correct": False},
            ]

        if multi_select:
            response = ET.SubElement(root, "choiceresponse")
            ET.SubElement(response, "label").text = question.get("prompt", "")
            group = ET.SubElement(response, "checkboxgroup")
        else:
            response = ET.SubElement(root, "multiplechoiceresponse")
            ET.SubElement(response, "label").text = question.get("prompt", "")
            group = ET.SubElement(
                response, "choicegroup", type="MultipleChoice"
            )

        for idx, opt in enumerate(options):
            choice = ET.SubElement(group, "choice")
            choice.text = opt.get("text", "")
            choice.set("correct", "true" if opt.get("is_correct") else "false")
            choice.set("name", chr(97 + idx))

    def _write_placeholder_problem(self, comp: ContentNode):
        """
        Write a placeholder problem when assessment data is missing.
        
        Creates a problem.xml with a warning message for manual review.
        Located at: work_dir/problem/{url_name}.xml
        
        Args:
            comp: ContentNode with node_type=PROBLEM (no assessment linked)
        """
        url_name = self._get_url_name(comp.node_id)
        root = ET.Element("problem")
        root.set("display_name", comp.title or "Problem")
        
        multiplechoiceresponse = ET.SubElement(root, "multiplechoiceresponse")
        label = ET.SubElement(multiplechoiceresponse, "label")
        label.text = "This problem could not be converted automatically. Please review."
        
        choicegroup = ET.SubElement(multiplechoiceresponse, "choicegroup", type="MultipleChoice")
        choice = ET.SubElement(choicegroup, "choice")
        choice.text = "Review required"
        choice.set("correct", "false")
        
        self._write_xml(self.work_dir / "problem" / f"{url_name}.xml", root)

    def _write_video(self, comp: ContentNode):
        """
        Write video component xml.
        
        Handles three cases:
        1. YouTube videos (uses youtube_id attribute)
        2. Self-hosted video files (uses asset reference)
        3. Placeholder for unknown video types
        
        Args:
            comp: ContentNode with node_type=VIDEO and metadata
        """
        url_name = self._get_url_name(comp.node_id)
        metadata = comp.metadata
        root = ET.Element("video")                  
        
        root.set("display_name", comp.title or "video")
        root.set("url_name", url_name)
        
        activity_type = metadata.get("activity_type", "")
        
        if activity_type == "youtube":
            youtube_id = metadata.get("youtube_id", "")
            if youtube_id:
                root.set("youtube_id_1_0", youtube_id)
                root.set("youtube", f"1.00:{youtube_id}")
            else:
                root.set("youtube_id_1_0", "00000000000")
                root.set("youtube", "1.00:00000000000")
                
        elif activity_type == "video" or activity_type == "":
            asset_id = metadata.get("asset_id")
            asset_obj = None                        
            if self.course.assets:
                asset_obj = next(
                    (a for a in self.course.assets if a.asset_id == asset_id),
                    None                            
                )
            
            if asset_obj:
                source = ET.SubElement(root, "source")
                source.set("src", f"/static/{self._asset_static_path(asset_obj)}")
                root.set("download_video", "true")
            else:
                source = ET.SubElement(root, "source")
                source.set("src", metadata.get("video_url", ""))
        
        else:
            source = ET.SubElement(root, "source")    
            source.set("src", "")
        
        self._write_xml(self.work_dir / "video" / f"{url_name}.xml", root)

    def _write_scorm(self, comp: ContentNode):
        url_name = self._get_url_name(comp.node_id)
        metadata = comp.metadata
        scorm_settings = metadata.get("scorm_settings", {})
        asset_id = metadata.get("asset_id")

        scorm_asset = next((a for a in self.course.assets if a.asset_id == asset_id), None)
        if not scorm_asset:
            self._write_placeholder_scorm(comp)
            return

        version = scorm_settings.get("version", "")
        if "2004" in version:
            version = "SCORM_2004"
        else:
            version = "SCORM_12"

        # Create the SCORM XBlock XML structure
        root = ET.Element("scormxblock")
        root.set("display_name", comp.title or "SCORM Package")
        root.set("scorm_file", f"/static/{self._asset_static_path(scorm_asset)}")
        root.set("version_scorm", version)
        root.set("has_score", "true")  # Assuming it's graded
        root.set("weight", scorm_settings.get("maxgrade") or "1")

        self._write_xml(self.work_dir / "scormxblock" / f"{url_name}.xml", root)

    def _write_placeholder_scorm(self, comp: ContentNode):
        # Fallback for when the asset is missing
        url_name = self._get_url_name(comp.node_id)
        root = ET.Element("scormxblock")
        root.set("display_name", comp.title or "Missing SCORM Package")
        root.set("scorm_file", "")
        self._write_xml(self.work_dir / "scormxblock" / f"{url_name}.xml", root)

    def _copy_assets(self, source_extracted: Path):
        """
        Copy asset files from source extraction to Open edX static/ folder.
        
        Copies files referenced in course.assets from the source extraction 
        directory to the Open edX export's static folder for inclusion 
        in the final tarball.
        
        Args:
            source_extracted: Path to extracted source directory (e.g., Moodle backup)
        """
        asset_dir = self.work_dir / "static"

        for asset in self.course.assets:
            try:
                source = resolve_under(source_extracted, asset.path)
                dest = resolve_under(
                    asset_dir, self._asset_static_path(asset)
                )
            except ValueError:
                continue
            if not source.is_file():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())

    def _write_xml(self, path: Path, root: ET.Element):
        """
        Write an XML element tree to a file with UTF-8 encoding.
        
        Helper method for consistent XML writing across all component types.
        
        Args:
            path: Destination file path
            root: Root XML element to write
        """
        tree = ET.ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)

    def _write_openassessment(self, comp: ContentNode):
        """
        Write an Open edX openassessment (ORA) component.
        """
        url_name = self._get_url_name(comp.node_id)
        root = ET.Element("openassessment")
        root.set("display_name", comp.title or "Peer Assessment")
        root.set("submission_start", "2001-01-01T00:00:00+00:00")
        root.set("submission_due", "2029-01-01T00:00:00+00:00")
        root.set("text_response", "required")
        root.set("text_response_editor", "tinymce")
        root.set("allow_latex", "false")

        # Add the prompt (content_html)
        prompts = ET.SubElement(root, "prompts")
        prompt = ET.SubElement(prompts, "prompt")
        description = ET.SubElement(prompt, "description")
        description.text = comp.metadata.get("content_html", comp.title or "Peer assessment prompt")
        description.set("format", "html")

        # Add a simple rubric
        rubric = ET.SubElement(root, "rubric")
        criterion = ET.SubElement(rubric, "criterion")
        criterion.set("feedback", "optional")
        name = ET.SubElement(criterion, "name")
        name.text = "0"
        label = ET.SubElement(criterion, "label")
        label.text = "Quality"
        prompt_rubric = ET.SubElement(criterion, "prompt")
        prompt_rubric.text = "Evaluate the response based on clarity, evidence, and reasoning."

        self._write_xml(self.work_dir / "openassessment" / f"{url_name}.xml", root)

    def _write_discussion(self, comp: ContentNode):
        """Write an Open edX discussion component (forum)."""
        url_name = self._get_url_name(comp.node_id)
        root = ET.Element("discussion")
        root.set("discussion_id", url_name)
        root.set("display_name", comp.title or "Discussion")
        # The discussion component in OLX expects a <discussion> element with optional attributes.
        # To include a description, I will add a <description> sub-element.
        if comp.metadata.get("content_html"):
            desc = ET.SubElement(root, "description")
            desc.text = comp.metadata.get("content_html")
        self._write_xml(self.work_dir / "discussion" / f"{url_name}.xml", root)
