import os
import tarfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional
from domain.entities import Course, ContentNode
from domain.enums import NodeType

class OpenEdxTargetAdapter:
    def __init__(self):
        self.work_dir: Optional[Path] = None
        self.course: Optional[Course] = None
        self.node_id_map: Dict[str, str] = {}  # node_id -> url_name

    def generate_export(self, course: Course, output_path: str) -> str:
        self.course = course
        self.work_dir = Path("data/openedx_export") / uuid.uuid4().hex
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Create directories
        for subdir in ["chapter", "sequential", "vertical", "html", "problem", "video", "course", "asset"]:
            (self.work_dir / subdir).mkdir(exist_ok=True)

        # Write root course.xml
        self._write_root_course_xml()

        # Write actual course definition (course/{url_name}.xml)
        self._write_actual_course_xml()

        # Process content nodes
        for node in course.content_nodes:
            if node.node_type == NodeType.CHAPTER:
                self._write_chapter(node)

        # Create tar.gz
        output_path = Path(output_path)
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(self.work_dir, arcname="course")
        return str(output_path)

    def _safe_name(self, name: str, max_len=32) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in "._-")
        return safe[:max_len] if safe else "item"

    def _get_url_name(self, node_id: str) -> str:
        if node_id not in self.node_id_map:
            self.node_id_map[node_id] = self._safe_name(node_id)
        return self.node_id_map[node_id]

    def _write_root_course_xml(self):
        root = ET.Element("course")
        root.set("url_name", self._safe_name(self.course.title, 32))
        root.set("org", self.course.metadata.get("org", "Org"))
        root.set("course", self.course.metadata.get("course_code", "Course"))
        self._write_xml(self.work_dir / "course.xml", root)

    def _write_actual_course_xml(self):
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
        url_name = self._get_url_name(node.node_id)
        root = ET.Element("chapter")
        root.set("display_name", node.title or "Chapter")
        for child in node.children:
            if child.node_type == NodeType.SEQUENTIAL:
                seq = ET.SubElement(root, "sequential")
                seq.set("url_name", self._get_url_name(child.node_id))
        self._write_xml(self.work_dir / "chapter" / f"{url_name}.xml", root)
        for child in node.children:
            if child.node_type == NodeType.SEQUENTIAL:
                self._write_sequential(child)

    def _write_sequential(self, node: ContentNode):
        url_name = self._get_url_name(node.node_id)
        root = ET.Element("sequential")
        root.set("display_name", node.title or "Sequential")
        for child in node.children:
            if child.node_type == NodeType.VERTICAL:
                vert = ET.SubElement(root, "vertical")
                vert.set("url_name", self._get_url_name(child.node_id))
        self._write_xml(self.work_dir / "sequential" / f"{url_name}.xml", root)
        for child in node.children:
            if child.node_type == NodeType.VERTICAL:
                self._write_vertical(child)

    def _write_vertical(self, node: ContentNode):
        url_name = self._get_url_name(node.node_id)
        root = ET.Element("vertical")
        root.set("display_name", node.title or "Vertical")
        for comp in node.children:
            if comp.node_type == NodeType.HTML:
                elem = ET.SubElement(root, "html")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_html(comp)
            elif comp.node_type == NodeType.PROBLEM:
                elem = ET.SubElement(root, "problem")
                elem.set("url_name", self._get_url_name(comp.node_id))
                self._write_problem(comp)
            elif comp.node_type == NodeType.VIDEO:
                elem = ET.SubElement(root, "video")
                elem.set("url_name", self._get_url_name(comp.node_id))
                # minimal video stub
                self._write_video(comp)
        self._write_xml(self.work_dir / "vertical" / f"{url_name}.xml", root)

    def _write_html(self, comp: ContentNode):
        url_name = self._get_url_name(comp.node_id)
        content = comp.metadata.get("content_html", comp.title or "")
        # Write .html file
        html_path = self.work_dir / "html" / f"{url_name}.html"
        html_path.write_text(content, encoding="utf-8")
        # Write .xml wrapper
        root = ET.Element("html")
        root.set("display_name", comp.title or "HTML")
        root.set("filename", f"{url_name}.html")
        self._write_xml(self.work_dir / "html" / f"{url_name}.xml", root)

    def _write_problem(self, comp: ContentNode):
        url_name = self._get_url_name(comp.node_id)
        # If we have an assessment_id, we could fetch details, but for now create placeholder
        root = ET.Element("problem")
        root.set("display_name", comp.title or "Problem")
        # Add a simple multiple choice stub
        choiceresponse = ET.SubElement(root, "choiceresponse")
        label = ET.SubElement(choiceresponse, "label")
        label.text = comp.title or "Question"
        checkboxgroup = ET.SubElement(choiceresponse, "checkboxgroup")
        choice = ET.SubElement(checkboxgroup, "choice")
        choice.text = "Option 1"
        choice.set("correct", "true")
        self._write_xml(self.work_dir / "problem" / f"{url_name}.xml", root)

    def _write_video(self, comp: ContentNode):
        url_name = self._get_url_name(comp.node_id)
        root = ET.Element("video")
        root.set("display_name", comp.title or "Video")
        root.set("youtube_id", "0"*11)  # placeholder
        self._write_xml(self.work_dir / "video" / f"{url_name}.xml", root)

    def _write_xml(self, path: Path, root: ET.Element):
        tree = ET.ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)
