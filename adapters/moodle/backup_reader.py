"""
===============================================================================
File:        backup_reader.py
Institution: German University of Digital Science
Project:     GUDS Coding Camp I Capstone Project
Instructor:  Prof. Dr. Thomas Staubitz
Team:        Team Delta
Members:     Olga Kazarina, Augustine Atta Abrefa, Ronald K. Sebuhinja
Date:        27 May 2026

Description:
    This module is responsible for extracting and reading data from the .mbz archive
    and availing the data to the parsing module(s) in an appropriate format.

Usage:
    TBA

===============================================================================
"""

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional


class MoodleBackupReader:

    def extract_archive(self, mbz_path: str, workdir: str) -> Path:
        target_path = Path(workdir)
        target_path.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(mbz_path, 'r') as archive:
            archive.extractall(target_path)
        return target_path

    def read_manifest(self, extracted: Path) -> Dict[str, Any]:
        root = ET.parse(extracted / "moodle_backup.xml").getroot()
        information = root.find("information") or root

        course_information: Dict[str, Any] = {}
        course_element = information.find(".//contents/course")
        if course_element is not None:
            course_information["title"] = course_element.findtext("title", "")
            course_information["directory"] = course_element.findtext("directory", "course")

        activities: Dict[str, Any] = {}
        for activity in information.findall(".//contents/activities/activity"):
            cmid = activity.findtext("cmid") or activity.findtext("moduleid")  # cmid and moduleid are both used by Moodle
            if not cmid:
                continue

            activities[cmid] = {
                "cmid": cmid,
                "module_name": activity.findtext("module_name", ""),
                "title": activity.findtext("title", ""),
                "directory": activity.findtext("directory", ""),
                "section_id": activity.findtext("section_id", ""),
            }

        sections: List[Dict[str, Any]] = []
        for section in information.findall(".//contents/sections/section"):
            sections.append({
                "section_id": section.findtext("section_id", ""),
                "title": section.findtext("title", ""),
                "directory": section.findtext("directory", ""),
            })

        return {
            "course_information": course_information,
            "sections": sections,
            "activities": activities,
            "file_records": self.read_file_records(extracted),
        }

    # Parse files.xml
    def read_file_records(self, extracted: Path) -> Dict[str, Any]:
        files_xml = extracted / "files.xml"
        if not files_xml.exists():
            return {}

        root = ET.parse(files_xml).getroot()
        records: Dict[str, Any] = {}
        for record in root.findall("file"):
            file_id = record.findtext("id")
            if not file_id:
                continue

            records[file_id] = {
                "contenthash": record.findtext("contenthash", ""),
                "filename": record.findtext("filename", ""),
                "mimetype": record.findtext("mimetype", ""),
                "filepath": record.findtext("filepath", "/"),
            }
        return records

    def read_xml(self, extracted: Path, relative_path: str) -> Optional[ET.Element]:
        xml_path = extracted / relative_path
        if not xml_path.exists():
            return None
        try:
            return ET.parse(xml_path).getroot()
        except ET.ParseError:
            return None

    def read_raw_text(self, extracted: Path, relative_path: str) -> Optional[str]:
        xml_path = extracted / relative_path
        if not xml_path.exists():
            return None
        return xml_path.read_text(encoding="utf-8")

    def read_file_bytes(self, extracted: Path, contenthash: str) -> Optional[bytes]:
        if not contenthash or len(contenthash) < 2:
            return None
        try:
            return (extracted / "files" / contenthash[:2] / contenthash).read_bytes()
        except (FileNotFoundError, KeyError):
            return None

    def read_inforef(self, extracted: Path, activity_directory: str) -> List[str]:
        root = self.read_xml(extracted, f"{activity_directory}/inforef.xml")
        if root is None:
            return []
        return [
            fid for f in root.findall(".//file")
            if (fid := f.findtext("id", ""))
        ]







