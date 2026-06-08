"""
Open edX Course Parser – Reads Open edX package XMLs and extracts course structure.

Parses Open edX .tar.gz course packages and extracts the hierarchical structure:
course → chapters → sequentials → verticals → components (html, video, problem, etc.)
Stores raw XML fragments for later domain entity mapping.
"""

import xml.etree.ElementTree as ET
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from .package_reader import OpenEdxPackageReader


class OpenEdxCourseParser:
    """
    Parses Open edX course packages into a canonical dictionary structure.

    This parser:
    - Extracts Open edX .tar.gz packages
    - Parses course.xml and nested component XMLs
    - Stores raw XML fragments for auditing/reconstruction
    - Returns a structured dict with course metadata and hierarchy
    """

    def __init__(self):
        self.reader = OpenEdxPackageReader()
        self.fragments: List[Dict[str, Any]] = []

    def parse(self, archive_path: str, work_dir: str) -> Dict[str, Any]:
        """
        Parse an Open edX course package and extract its structure.

        Args:
            archive_path: Path to the .tar.gz Open edX course package
            work_dir: Directory to extract the package to

        Returns:
            Dictionary with course structure:
            {
                "course_title": str,
                "org": str,
                "course_code": str,
                "chapters": [...],
                "raw_fragments": [...],
                "extracted_path": str
            }
        """
        # Extract package and locate course.xml
        extracted = self.reader.extract(archive_path, work_dir)
        course_xml_path = self.reader.find_course_xml(extracted)
        tree = ET.parse(course_xml_path)
        root = tree.getroot()

        # Extract course metadata from <course> element attributes
        course_title = root.attrib.get("display_name", "Unnamed Course")
        org = root.attrib.get("org", "")
        course_code = root.attrib.get("course", "")

        # Store raw course.xml fragment for later reference
        self._store_fragment(
            course_xml_path,
            extracted,
            "course.xml",
        )

        # Parse chapter hierarchy
        chapters = self._parse_chapters(root, extracted)

        return {
            "course_title": course_title,
            "org": org,
            "course_code": course_code,
            "chapters": chapters,
            "raw_fragments": self.fragments,
            "extracted_path": str(extracted),
        }

    def _store_fragment(
        self, file_path: Path, extracted_root: Path, description: str = ""
    ) -> str:
        """
        Read XML file, store as raw fragment, and return fragment ID.

        Args:
            file_path: Path to the XML file
            extracted_root: Root of extracted package (for relative path)
            description: Optional description of the fragment

        Returns:
            Generated fragment_id
        """
        with open(file_path, "r", encoding="utf-8") as f:
            raw_xml = f.read()

        fragment_id = str(uuid.uuid4())
        self.fragments.append({
            "fragment_id": fragment_id,
            "kind": "xml",
            "source_location": {
                "source_system": "openedx",
                "package_path": str(file_path.relative_to(extracted_root)),
                "file_path": str(file_path),
            },
            "raw_text": raw_xml,
            "checksum": None,
        })

        return fragment_id

    def _parse_chapters(self, root: ET.Element, extracted: Path) -> List[Dict[str, Any]]:
        """Parse all <chapter> elements from course.xml."""
        chapters = []
        for chapter_elem in root.findall("chapter"):
            chapter_url = chapter_elem.attrib.get("url_name")
            if not chapter_url:
                continue

            chapter_file = extracted / "chapter" / f"{chapter_url}.xml"
            if not chapter_file.exists():
                continue

            chapter_data = self._parse_chapter(chapter_file, extracted)
            chapters.append(chapter_data)

        return chapters

    def _parse_chapter(self, chapter_file: Path, extracted: Path) -> Dict[str, Any]:
        """
        Parse a single chapter XML file.

        Returns chapter dict with title, url_name, raw_fragment_id, and sequentials.
        """
        tree = ET.parse(chapter_file)
        root = tree.getroot()
        title = root.attrib.get("display_name", "Untitled Chapter")

        # Store raw chapter XML fragment
        fragment_id = self._store_fragment(chapter_file, extracted, "chapter")

        # Parse sequential children
        sequentials = []
        for seq_elem in root.findall("sequential"):
            seq_url = seq_elem.attrib.get("url_name")
            if not seq_url:
                continue

            seq_file = extracted / "sequential" / f"{seq_url}.xml"
            if not seq_file.exists():
                continue

            seq_data = self._parse_sequential(seq_file, extracted)
            sequentials.append(seq_data)

        return {
            "title": title,
            "url_name": chapter_file.stem,
            "raw_fragment_id": fragment_id,
            "sequentials": sequentials,
        }

    def _parse_sequential(self, seq_file: Path, extracted: Path) -> Dict[str, Any]:
        """
        Parse a single sequential XML file.

        Returns sequential dict with title, url_name, raw_fragment_id, and verticals.
        """
        tree = ET.parse(seq_file)
        root = tree.getroot()
        title = root.attrib.get("display_name", "Untitled Sequential")

        # Store raw sequential XML fragment
        fragment_id = self._store_fragment(seq_file, extracted, "sequential")

        # Parse vertical children
        verticals = []
        for vert_elem in root.findall("vertical"):
            vert_url = vert_elem.attrib.get("url_name")
            if not vert_url:
                continue

            vert_file = extracted / "vertical" / f"{vert_url}.xml"
            if not vert_file.exists():
                continue

            vert_data = self._parse_vertical(vert_file, extracted)
            verticals.append(vert_data)

        return {
            "title": title,
            "url_name": seq_file.stem,
            "raw_fragment_id": fragment_id,
            "verticals": verticals,
        }

    def _parse_vertical(self, vert_file: Path, extracted: Path) -> Dict[str, Any]:
        """
        Parse a single vertical XML file.

        Returns vertical dict with title, url_name, raw_fragment_id, and components.
        """
        tree = ET.parse(vert_file)
        root = tree.getroot()
        title = root.attrib.get("display_name", "Untitled Vertical")

        # Store raw vertical XML fragment
        fragment_id = self._store_fragment(vert_file, extracted, "vertical")

        # Parse component children (html, video, problem, etc.)
        components = self._parse_components(root, extracted)

        return {
            "title": title,
            "url_name": vert_file.stem,
            "raw_fragment_id": fragment_id,
            "components": components,
        }

    def _parse_components(self, root: ET.Element, extracted: Path) -> List[Dict[str, Any]]:
        """
        Parse all component elements within a vertical.

        Components include html, video, problem, openassessment, etc.
        Returns a list of component dicts with metadata and optional raw fragment.
        """
        components = []
        for comp in root:
            comp_tag = comp.tag
            comp_url = comp.attrib.get("url_name", "")
            comp_title = comp.attrib.get("display_name", "")

            # Locate component XML file based on type
            comp_file = self._find_component_file(comp_tag, comp_url, extracted)

            # Store raw component XML if file exists
            comp_raw_fragment_id = None
            if comp_file and comp_file.exists():
                comp_raw_fragment_id = self._store_fragment(
                    comp_file, extracted, f"component {comp_tag}"
                )

                # Try to get better title from component XML
                if not comp_title:
                    comp_tree = ET.parse(comp_file)
                    comp_root = comp_tree.getroot()
                    comp_title = comp_root.attrib.get("display_name")
                    if not comp_title:
                        comp_title = comp_url

            # Include inline XML only for openassessment
            inline_xml = (
                ET.tostring(comp, encoding="unicode") if comp_tag == "openassessment" else None
            )

            components.append({
                "type": comp_tag,
                "title": comp_title,
                "url_name": comp_url,
                "raw_fragment_id": comp_raw_fragment_id,
                "inline_xml": inline_xml,
            })

        return components

    def _find_component_file(
        self, comp_tag: str, comp_url: str, extracted: Path
    ) -> Optional[Path]:
        """
        Locate component XML file based on tag type and url_name.

        Returns None if component type is not supported or file doesn't exist.
        """
        if comp_tag == "html":
            comp_file = extracted / "html" / f"{comp_url}.xml"
        elif comp_tag == "video":
            comp_file = extracted / "video" / f"{comp_url}.xml"
        elif comp_tag == "problem":
            comp_file = extracted / "problem" / f"{comp_url}.xml"
        elif comp_tag == "openassessment":
            # openassessment files may be in a different location or handled separately
            comp_file = None
        else:
            comp_file = None

        return comp_file
