import os
from pathlib import Path
from typing import Optional

from core.archive_utils import safe_extract_tar


class OpenEdxPackageReader:
    def extract(self, archive_path: str, target_dir: str) -> Path:
        """
        Extract a tar.gz archive and return the directory containing the root
        ``course.xml``.

        Exports produced by this project place the export payload under a
        top-level ``course/`` directory, so that directory is returned when it
        contains ``course.xml``. Source exports usually keep ``course.xml`` at
        the archive root; in that case the extraction root is returned.
        """
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)

        safe_extract_tar(archive_path, target)

        nested_root = target / "course" / "course.xml"
        if nested_root.exists():
            return target / "course"

        if (target / "course.xml").exists():
            return target

        for root, _dirs, files in os.walk(target):
            if "course.xml" in files:
                return Path(root)

        raise FileNotFoundError("course.xml not found in extracted archive")

    def get_course_xml_path(self, extracted_dir: Path) -> Path:
        """Return the path to the course XML containing the course definition."""
        course_subdir = extracted_dir / "course"
        if course_subdir.exists():
            for xml_file in course_subdir.glob("*.xml"):
                if xml_file.name.lower().endswith("course.xml"):
                    return xml_file

        root_course_xml = extracted_dir / "course.xml"
        if root_course_xml.exists():
            return root_course_xml

        raise FileNotFoundError("No course.xml found in extracted directory")

    def get_chapter_xml_path(self, extracted_dir: Path, chapter_url_name: str) -> Optional[Path]:
        """Resolve a chapter url_name to its XML file path."""
        return extracted_dir / "chapter" / f"{chapter_url_name}.xml"

    def get_sequential_xml_path(self, extracted_dir: Path, sequential_url_name: str) -> Optional[Path]:
        return extracted_dir / "sequential" / f"{sequential_url_name}.xml"

    def get_vertical_xml_path(self, extracted_dir: Path, vertical_url_name: str) -> Optional[Path]:
        return extracted_dir / "vertical" / f"{vertical_url_name}.xml"
