"""
Open edX Target Adapter – Converts canonical Course domain objects into 
Open edX export format (.tar.gz).

This adapter handles:
- Full course hierarchy (Chapter → Sequential → Vertical → Components)
- Assessments with questions and answer options
- Asset file copying from Moodle backups
- XML generation for all Open edX components (html, problem, video, etc.)
"""

import os
import tarfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional

from domain.entities import Course, ContentNode, Assessment, Question, AnswerOption
from domain.enums import NodeType


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
        self.node_id_map: Dict[str, str] = {}  # node_id → url_name mapping

    def generate_export(
        self, 
        course: Course, 
        output_path: str, 
        moodle_extracted_path: Optional[str] = None
    ) -> str:
        """
        Generate an Open edX course export tarball from a canonical Course.
        
        Creates the full directory structure, generates all XML files for 
        course hierarchy and components, copies assets if available, and 
        packages everything into a .tar.gz archive.
        
        Args:
            course: The canonical Course domain object to export
            output_path: Destination path for the .tar.gz file
            moodle_extracted_path: Optional path to Moodle extract for copying assets
            
        Returns:
            Absolute path to the generated .tar.gz export file
            
        Example:
            >>> adapter = OpenEdxTargetAdapter()
            >>> output = adapter.generate_export(course, "output/course.tar.gz")
            "/path/to/output/course.tar.gz"
        """
        # -------------------------------------------------------------------------
        # Step 1: Initialize working directory and course state
        # -------------------------------------------------------------------------
        self.course = course
        self.work_dir = Path("data/openedx_export") / uuid.uuid4().hex
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # -------------------------------------------------------------------------
        # Step 2: Create Open edX directory structure
        # -------------------------------------------------------------------------
        for subdir in ["chapter", "sequential", "vertical", "html", "problem", "video", "course", "asset"]:
            (self.work_dir / subdir).mkdir(exist_ok=True)

        # -------------------------------------------------------------------------
        # Step 3: Generate root course.xml (course settings)
        # -------------------------------------------------------------------------
        self._write_root_course_xml()

        # -------------------------------------------------------------------------
        # Step 4: Generate actual course definition (course/{url_name}.xml)
        # -------------------------------------------------------------------------
        self._write_actual_course_xml()

        # -------------------------------------------------------------------------
        # Step 5: Process content nodes and generate XML for each hierarchy level
        # -------------------------------------------------------------------------
        for node in course.content_nodes:
            if node.node_type == NodeType.CHAPTER:
                self._write_chapter(node)

        # -------------------------------------------------------------------------
        # Step 6: Copy asset files from Moodle backup if provided
        # -------------------------------------------------------------------------
        if moodle_extracted_path:
            self._copy_assets(Path(moodle_extracted_path))

        # -------------------------------------------------------------------------
        # Step 7: Package everything into a tar.gz archive
        # -------------------------------------------------------------------------
        output_path = Path(output_path)
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(self.work_dir, arcname="course")
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

    def _write_chapter(self, node: ContentNode):
        """
        Write XML for a chapter (Chapter → Sequential hierarchy).
        
        Creates chapter.xml with sequential references and recursively 
        processes all sequential children.
        Located at: work_dir/chapter/{url_name}.xml
        
        Args:
            node: ContentNode with node_type=CHAPTER
        """
        url_name = self._get_url_name(node.node_id)
        root = ET.Element("chapter")
        root.set("display_name", node.title or "Chapter")
        
        for child in node.children:
            if child.node_type == NodeType.SEQUENTIAL:
                seq = ET.SubElement(root, "sequential")
                seq.set("url_name", self._get_url_name(child.node_id))
        
        self._write_xml(self.work_dir / "chapter" / f"{url_name}.xml", root)
        
        # Recursively process sequential children
        for child in node.children:
            if child.node_type == NodeType.SEQUENTIAL:
                self._write_sequential(child)

    def _write_sequential(self, node: ContentNode):
        """
        Write XML for a sequential (Sequential → Vertical hierarchy).
        
        Creates sequential.xml with vertical references and recursively 
        processes all vertical children.
        Located at: work_dir/sequential/{url_name}.xml
        
        Args:
            node: ContentNode with node_type=SEQUENTIAL
        """
        url_name = self._get_url_name(node.node_id)
        root = ET.Element("sequential")
        root.set("display_name", node.title or "Sequential")
        
        for child in node.children:
            if child.node_type == NodeType.VERTICAL:
                vert = ET.SubElement(root, "vertical")
                vert.set("url_name", self._get_url_name(child.node_id))
        
        self._write_xml(self.work_dir / "sequential" / f"{url_name}.xml", root)
        
        # Recursively process vertical children
        for child in node.children:
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
        
        for comp in node.children:
            if comp.node_type == NodeType.HTML:
                # HTML component
                elem = ET.SubElement(root, "html")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_html(comp)
                
            elif comp.node_type == NodeType.PROBLEM:
                # Problem component with assessment
                elem = ET.SubElement(root, "problem")
                elem.set("url_name", self._get_url_name(comp.node_id))
                
                # Find the assessment linked to this component
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
                else:
                    # Fallback: write a placeholder problem
                    self._write_placeholder_problem(comp)
                    
            elif comp.node_type == NodeType.VIDEO:
                # Video component
                elem = ET.SubElement(root, "video")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_video(comp)
        
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
        
        # Write .xml wrapper (references the html file)
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
        
        Creates a problem.xml with choiceresponse sections for each 
        question. Supports multichoice and truefalse question types.
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

        # Create one <choiceresponse> per question
        for q in questions:
            if q.question_type in ("multichoice", "truefalse"):
                choiceresponse = ET.SubElement(root, "choiceresponse")
                label = ET.SubElement(choiceresponse, "label")
                label.text = q.prompt_text or "Question"
                
                checkboxgroup = ET.SubElement(choiceresponse, "checkboxgroup")
                for opt in answer_options:
                    if opt.question_id == q.question_id:
                        choice = ET.SubElement(checkboxgroup, "choice")
                        choice.text = opt.text
                        choice.set("correct", "true" if opt.is_correct else "false")
        
        self._write_xml(self.work_dir / "problem" / f"{url_name}.xml", root)

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
        
        choiceresponse = ET.SubElement(root, "choiceresponse")
        label = ET.SubElement(choiceresponse, "label")
        label.text = "This problem could not be converted automatically. Please review."
        
        self._write_xml(self.work_dir / "problem" / f"{url_name}.xml", root)

    def _write_video(self, comp: ContentNode):
        """
        Write video component XML with placeholder YouTube ID.
        
        Creates a video.xml with a placeholder youtube_id. In production, 
        this should be replaced with actual video IDs.
        Located at: work_dir/video/{url_name}.xml
        
        Args:
            comp: ContentNode with node_type=VIDEO
        """
        url_name = self._get_url_name(comp.node_id)
        root = ET.Element("video")
        root.set("display_name", comp.title or "Video")
        root.set("youtube_id", "0" * 11)  # placeholder; replace with actual ID
        self._write_xml(self.work_dir / "video" / f"{url_name}.xml", root)

    def _copy_assets(self, moodle_extracted: Path):
        """
        Copy asset files from Moodle backup to Open edX asset/ folder.
        
        Copies files referenced in course.assets from the Moodle extract 
        directory to the Open edX export's asset folder for inclusion 
        in the final tarball.
        
        Args:
            moodle_extracted: Path to extracted Moodle backup directory
        """
        asset_dir = self.work_dir / "asset"
        for asset in self.course.assets:
            # asset.path is like "files/3a/3ac87b9b..."
            source = moodle_extracted / asset.path
            if source.exists():
                dest = asset_dir / source.name
                dest.write_bytes(source.read_bytes())
                # Note: HTML links to assets would need rewriting to match 
                # the new asset paths (not implemented here)

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
