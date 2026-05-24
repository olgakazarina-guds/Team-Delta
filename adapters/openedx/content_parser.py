import xml.etree.ElementTree as ET
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from .package_reader import OpenEdxPackageReader

class OpenEdxCourseParser:
    def __init__(self):
        self.reader = OpenEdxPackageReader()
        self.fragments = []  # store raw fragments as dicts

    def parse(self, archive_path: str, work_dir: str) -> Dict[str, Any]:
        extracted = self.reader.extract(archive_path, work_dir)
        course_xml_path = self.reader.find_course_xml(extracted)
        tree = ET.parse(course_xml_path)
        root = tree.getroot()

        ''' Get course title from <course> attribute or fallback '''
        course_title = root.attrib.get("display_name", "Unnamed Course")
        org = root.attrib.get("org", "")
        course_code = root.attrib.get("course", "")

        ''' Store raw fragment for course.xml '''
        with open(course_xml_path, "r", encoding="utf-8") as f:
            raw_xml = f.read()
        fragment_id = str(uuid.uuid4())
        self.fragments.append({
            "fragment_id": fragment_id,
            "kind": "xml",
            "source_location": {
                "source_system": "openedx",
                "package_path": str(course_xml_path.relative_to(extracted)),
                "file_path": str(course_xml_path)
            },
            "raw_text": raw_xml,
            "checksum": None
        })

        # Parse chapters
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

        return {
            "course_title": course_title,
            "org": org,
            "course_code": course_code,
            "chapters": chapters,
            "raw_fragments": self.fragments,
            "extracted_path": str(extracted)
        }

    def _parse_chapter(self, chapter_file: Path, extracted: Path) -> Dict[str, Any]:
        tree = ET.parse(chapter_file)
        root = tree.getroot()
        title = root.attrib.get("display_name", "Untitled Chapter")

        # Store raw chapter XML
        with open(chapter_file, "r", encoding="utf-8") as f:
            raw_xml = f.read()
        fragment_id = str(uuid.uuid4())
        self.fragments.append({
            "fragment_id": fragment_id,
            "kind": "xml",
            "source_location": {
                "source_system": "openedx",
                "file_path": str(chapter_file)
            },
            "raw_text": raw_xml,
            "checksum": None
        })

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
            "sequentials": sequentials
        }

    def _parse_sequential(self, seq_file: Path, extracted: Path) -> Dict[str, Any]:
        tree = ET.parse(seq_file)
        root = tree.getroot()
        title = root.attrib.get("display_name", "Untitled Sequential")

        with open(seq_file, "r", encoding="utf-8") as f:
            raw_xml = f.read()
        fragment_id = str(uuid.uuid4())
        self.fragments.append({
            "fragment_id": fragment_id,
            "kind": "xml",
            "source_location": {"source_system": "openedx", "file_path": str(seq_file)},
            "raw_text": raw_xml,
            "checksum": None
        })

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
            "verticals": verticals
        }

    def _parse_vertical(self, vert_file: Path, extracted: Path) -> Dict[str, Any]:
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
            # For now, just record existence; actual content will be loaded from respective subfolder
            comp_file = None
            if comp_tag == "html":
                comp_file = extracted / "html" / f"{comp_url}.xml"
            elif comp_tag == "video":
                comp_file = extracted / "video" / f"{comp_url}.xml"
            elif comp_tag == "problem":
                comp_file = extracted / "problem" / f"{comp_url}.xml"
            elif comp_tag == "openassessment":
                # openassessment data is inline, not a separate file
                comp_file = None
            else:
                comp_file = None

            comp_raw_fragment_id = None
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
                "inline_xml": ET.tostring(comp, encoding="unicode") if comp_tag == "openassessment" else None
            })

        return {
            "title": title,
            "url_name": vert_file.stem,
            "raw_fragment_id": fragment_id,
            "components": components
        }
