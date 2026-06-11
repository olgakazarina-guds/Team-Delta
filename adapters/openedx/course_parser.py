"""
Open edX Course Parser – Reads Open edX package XMLs and extracts course structure.

Parses Open edX .tar.gz course packages and extracts the hierarchical structure:
course → chapters → sequentials → verticals → components (html, video, problem, etc.)
Stores raw XML fragments for later domain entity mapping.
"""

import tarfile
import xml.etree.ElementTree as ET
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from .package_reader import OpenEdxPackageReader


class OpenEdxCourseParser:
    """
    Parses Open edX course packages into a canonical dictionary structure.

    This parser:
    Extracts Open edX .tar.gz packages
    Parses course.xml and nested component XMLs
    Stores raw XML fragments for auditing/reconstruction
    Extracts HTML content from html components
    Returns a structured dict with course metadata and hierarchy
    """

    def __init__(self):
        self.reader = OpenEdxPackageReader()
        self.fragments: List[Dict[str, Any]] = []

    def parse(self, archive_path: str, work_dir: str) -> Dict[str, Any]:
        """
        Extract the Open edX course export and return a structured dictionary.

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

        Raises:
            FileNotFoundError: If course.xml or course definition not found
            ValueError: If required attributes are missing
        """
        # Extract package and locate root course.xml
        extracted_root = self.reader.extract(archive_path, work_dir)
        root_course_xml = extracted_root / "course.xml"
        if not root_course_xml.exists():
            raise FileNotFoundError(f"course.xml not found at {root_course_xml}")

        # Parse root course.xml to get the actual course file name
        root_tree = ET.parse(root_course_xml)
        root = root_tree.getroot()
        url_name = root.attrib.get("url_name")
        org = root.attrib.get("org", "")
        course_code = root.attrib.get("course", "")

        if not url_name:
            raise ValueError("course.xml missing url_name attribute")

        # The actual course definition is in course/{url_name}.xml
        actual_course_xml = extracted_root / "course" / f"{url_name}.xml"
        if not actual_course_xml.exists():
            raise FileNotFoundError(f"Course definition not found: {actual_course_xml}")

        # Parse the actual course file to get course metadata
        tree = ET.parse(actual_course_xml)
        root = tree.getroot()
        course_title = root.attrib.get("display_name", "Unnamed Course")

        # Store raw fragment for the actual course file
        self._store_fragment(actual_course_xml, extracted_root)

        # Parse chapters from the course file
        chapters = self._parse_chapters(root, extracted_root)

        return {
            "course_title": course_title,
            "org": org,
            "course_code": course_code,
            "chapters": chapters,
            "raw_fragments": self.fragments,
            "extracted_path": str(extracted_root),
        }

    def _store_fragment(self, file_path: Path, extracted_root: Path) -> str:
        """
        Read XML file, store as raw fragment, and return fragment ID.

        Args:
            file_path: Path to the XML file
            extracted_root: Root of extracted package (for relative path)

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

    def _parse_chapters(self, root: ET.Element, extracted_root: Path) -> List[Dict[str, Any]]:
        """Parse all <chapter> elements from the course file."""
        chapters = []
        for chapter_elem in root.findall("chapter"):
            chapter_url = chapter_elem.attrib.get("url_name")
            if not chapter_url:
                continue

            chapter_file = extracted_root / "chapter" / f"{chapter_url}.xml"
            if not chapter_file.exists():
                continue

            chapter_data = self._parse_chapter(chapter_file, extracted_root)
            chapters.append(chapter_data)

        return chapters

    def _parse_chapter(self, chapter_file: Path, extracted_root: Path) -> Dict[str, Any]:
        """
        Parse a single chapter XML file.

        Returns chapter dict with title, url_name, raw_fragment_id, and sequentials.
        """
        tree = ET.parse(chapter_file)
        root = tree.getroot()
        title = root.attrib.get("display_name", "Untitled Chapter")

        # Store raw chapter XML fragment
        fragment_id = self._store_fragment(chapter_file, extracted_root)

        # Parse sequential children
        sequentials = []
        for seq_elem in root.findall("sequential"):
            seq_url = seq_elem.attrib.get("url_name")
            if not seq_url:
                continue

            seq_file = extracted_root / "sequential" / f"{seq_url}.xml"
            if not seq_file.exists():
                continue

            seq_data = self._parse_sequential(seq_file, extracted_root)
            sequentials.append(seq_data)

        return {
            "title": title,
            "url_name": chapter_file.stem,
            "raw_fragment_id": fragment_id,
            "sequentials": sequentials,
        }

    def _parse_sequential(self, seq_file: Path, extracted_root: Path) -> Dict[str, Any]:
        """
        Parse a single sequential XML file.

        Returns sequential dict with title, url_name, raw_fragment_id, and verticals.
        """
        tree = ET.parse(seq_file)
        root = tree.getroot()
        title = root.attrib.get("display_name", "Untitled Sequential")

        # Store raw sequential XML fragment
        fragment_id = self._store_fragment(seq_file, extracted_root)

        # Parse vertical children
        verticals = []
        for vert_elem in root.findall("vertical"):
            vert_url = vert_elem.attrib.get("url_name")
            if not vert_url:
                continue

            vert_file = extracted_root / "vertical" / f"{vert_url}.xml"
            if not vert_file.exists():
                continue

            vert_data = self._parse_vertical(vert_file, extracted_root)
            verticals.append(vert_data)

        return {
            "title": title,
            "url_name": seq_file.stem,
            "raw_fragment_id": fragment_id,
            "verticals": verticals,
        }

    def _parse_vertical(self, vert_file: Path, extracted_root: Path) -> Dict[str, Any]:
        tree = ET.parse(vert_file)
        root = tree.getroot()
        title = root.attrib.get("display_name", "Untitled Vertical")

        with open(vert_file, "r", encoding="utf-8") as f:
            raw_xml = f.read()
        fragment_id = str(uuid.uuid4())
        self.fragments.append({
            "fragment_id": fragment_id,
            "kind": "xml",
            "source_location": {"source_system": "openedx", "file_path": str(vert_file)},
            "raw_text": raw_xml,
            "checksum": None
        })

        components = []
        for comp in root:
            comp_tag = comp.tag
            comp_url = comp.attrib.get("url_name", "")
            comp_title = comp.attrib.get("display_name", "")

            # For components that have a separate XML file, try to get the display name from that file
            if comp_tag in ("html", "video", "problem"):
                if comp_tag == "html":
                    comp_file = extracted_root / "html" / f"{comp_url}.xml"
                elif comp_tag == "video":
                    comp_file = extracted_root / "video" / f"{comp_url}.xml"
                elif comp_tag == "problem":
                    comp_file = extracted_root / "problem" / f"{comp_url}.xml"
                else:
                    comp_file = None

                if comp_file and comp_file.exists():
                    try:
                        wrapper_tree = ET.parse(comp_file)
                        wrapper_root = wrapper_tree.getroot()
                        # Override title if the wrapper has a display_name
                        wrapper_title = wrapper_root.attrib.get("display_name", "")
                        if wrapper_title:
                            comp_title = wrapper_title
                    except Exception:
                        pass  # fallback to original title

            comp_raw_fragment_id = None
            # Store raw fragment for the component XML (if exists)
            if comp_tag in ("html", "video", "problem"):
                comp_file = extracted_root / comp_tag / f"{comp_url}.xml"
                if comp_file and comp_file.exists():
                    with open(comp_file, "r", encoding="utf-8") as f:
                        comp_raw = f.read()
                    cid = str(uuid.uuid4())
                    self.fragments.append({
                        "fragment_id": cid,
                        "kind": "xml",
                        "source_location": {"source_system": "openedx", "file_path": str(comp_file)},
                        "raw_text": comp_raw,
                        "checksum": None
                    })
                    comp_raw_fragment_id = cid

            components.append({
                "type": comp_tag,
                "title": comp_title,
                "url_name": comp_url,
                "raw_fragment_id": comp_raw_fragment_id,
                "inline_xml": ET.tostring(comp, encoding="unicode") if comp_tag == "openassessment" else None,
                "content_html": None  # To be filled later if needed
            })

        return {
            "title": title,
            "url_name": vert_file.stem,
            "raw_fragment_id": fragment_id,
            "components": components
        }

    def _parse_components(
        self, root: ET.Element, extracted_root: Path
    ) -> List[Dict[str, Any]]:
        """
        Parse all component elements within a vertical.

        Components include html, video, problem, etc.
        For html components, extracts the actual content from the .html file.

        Returns a list of component dicts with metadata, raw fragment, and content.
        """
        components = []
        for comp in root:
            comp_tag = comp.tag
            comp_url = comp.attrib.get("url_name", "")
            comp_title = comp.attrib.get("display_name", "")
            comp_raw_fragment_id = None
            content_html = None

            # Locate component XML file based on type
            comp_file = self._find_component_file(comp_tag, comp_url, extracted_root)

            # Store raw fragment for component XML (wrapper)
            if comp_file and comp_file.exists():
                comp_raw_fragment_id = self._store_fragment(comp_file, extracted_root)

                # For HTML components, extract actual content from .html file
                if comp_tag == "html":
                    content_html = self._extract_html_content(comp_file, extracted_root)

            components.append({
                "type": comp_tag,
                "title": comp_title,
                "url_name": comp_url,
                "raw_fragment_id": comp_raw_fragment_id,
                "inline_xml": (
                    ET.tostring(comp, encoding="unicode")
                    if comp_tag == "openassessment"
                    else None
                ),
                "content_html": content_html,
            })

        return components

    def _find_component_file(
        self, comp_tag: str, comp_url: str, extracted_root: Path
    ) -> Optional[Path]:
        """
        Locate component XML file based on tag type and url_name.

        Returns None if component type is not supported or file doesn't exist.
        """
        if comp_tag == "html":
            return extracted_root / "html" / f"{comp_url}.xml"
        if comp_tag == "video":
            return extracted_root / "video" / f"{comp_url}.xml"
        if comp_tag == "problem":
            return extracted_root / "problem" / f"{comp_url}.xml"
        return None

    def _extract_html_content(self, comp_file: Path, extracted_root: Path) -> Optional[str]:
        """
        Extract the actual HTML content from an html component.

        The XML wrapper contains a 'filename' attribute pointing to the .html file.
        Returns the HTML content as a string, or None if extraction fails.
        """
        try:
            wrapper_tree = ET.parse(comp_file)
            wrapper_root = wrapper_tree.getroot()
            html_filename = wrapper_root.get("filename")

            if not html_filename:
                return None

            html_path = extracted_root / "html" / html_filename
            if not html_path.exists():
                return None

            return html_path.read_text(encoding="utf-8")
        except Exception:
            # Fallback to None if extraction fails
            return None
