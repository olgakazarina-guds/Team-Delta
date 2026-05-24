import tarfile
import os
import uuid
from pathlib import Path
from typing import Optional


class OpenEdxPackageReader:
    def extract(self, archive_path: str, target_dir: str) -> Path:
        """
        Extract tar.gz to target_dir.
        Returns the directory that contains the REAL course.xml.

        In some exports:  course.xml is at the root (minimal, just chapter refs)
        In others:       course/DemoCourse.xml has the full metadata.
        We prioritize course/DemoCourse.xml over root course.xml.
        """
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(target)

        # --- Priority 1: course/DemoCourse.xml (full metadata) ---
        course_subdir = target / "course"
        if course_subdir.exists():
            for xml_file in course_subdir.glob("*.xml"):
                # Usually named DemoCourse.xml, Course.xml, or {course_id}.xml
                if xml_file.name.lower().endswith("course.xml"):
                    return course_subdir

        # --- Priority 2: root course.xml ---
        if (target / "course.xml").exists():
            return target

        # --- Fallback: walk and find ANY course.xml ---
        for root, dirs, files in os.walk(target):
            if "course.xml" in files:
                return Path(root)

        raise FileNotFoundError("course.xml not found in extracted archive")

    # ------------------------------------------------------------------
    # Public API used by course_parser.py
    # ------------------------------------------------------------------
    def get_course_xml_path(self, extracted_dir: Path) -> Path:
        """Return the path to the course.xml we want to parse (full metadata)."""
        # 1. Look inside course/ subdir first
        course_subdir = extracted_dir / "course"
        if course_subdir.exists():
            for xml_file in course_subdir.glob("*.xml"):
                if xml_file.name.lower().endswith("course.xml"):
                    return xml_file

        # 2. Fall back to root
        root_course_xml = extracted_dir / "course.xml"
        if root_course_xml.exists():
            return root_course_xml

        raise FileNotFoundError("No course.xml found in extracted directory")

    def get_chapter_xml_path(self, extracted_dir: Path, chapter_url_name: str) -> Optional[Path]:
        """Resolve a chapter url_name to its XML file path."""
        return (extracted_dir / "chapter" / f"{chapter_url_name}.xml")

    def get_sequential_xml_path(self, extracted_dir: Path, sequential_url_name: str) -> Optional[Path]:
        return (extracted_dir / "sequential" / f"{sequential_url_name}.xml")

    def get_vertical_xml_path(self, extracted_dir: Path, vertical_url_name: str) -> Optional[Path]:
        return (extracted_dir / "vertical" / f"{vertical_url_name}.xml")

