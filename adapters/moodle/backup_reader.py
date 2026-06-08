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

import tarfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional
import os


class MoodleBackupReader:

    def extract_archive(self, mbz_path: str, workdir: str) -> Path:
        """
        Extract the .mbz archive (which can be .tar.gz or .zip) into work_dir
        and return the Path to the directory containing moodle_backup.xml.

        .mbz files are typically gzip-compressed tar archives, but Moodle can
        also produce zip-based backups. This method detects the format by
        reading the first two bytes (gzip magic 0x1F 0x8B) and uses the
        appropriate extractor.
        """
        target_path = Path(workdir)
        target_path.mkdir(parents=True, exist_ok=True)

        # Detect archive type by reading magic bytes
        with open(mbz_path, 'rb') as f:
            header = f.read(2)
            is_gzip = (header == b'\x1f\x8b')

        if is_gzip:
            with tarfile.open(mbz_path, 'r:gz') as tar:
                tar.extractall(target_path)
        else:
            with zipfile.ZipFile(mbz_path, 'r') as zf:
                zf.extractall(target_path)

        # Locate the directory containing moodle_backup.xml
        for root, dirs, files in os.walk(target_path):
            if "moodle_backup.xml" in files:
                return Path(root)

        raise FileNotFoundError("moodle_backup.xml not found in extracted archive")

    def read_manifest(self, extracted: Path) -> Dict[str, Any]:
        """
        Parse moodle_backup.xml and return a structured manifest dict with:
        - course_info:   basic course title and directory from the manifest header
        - sections:      ordered list of {section_id, title, directory}
        - activities:    dict keyed by cmid -> {cmid, module_name, title, directory, section_id}
        - file_records:  dict keyed by file id -> {contenthash, filename, mimetype, filepath}
                         (populated by read_file_records)

        Note: <moduleid> and <cmid> are both used across Moodle versions for the same thing.
        We try moduleid first and fall back to cmid so both variants are handled.
        """
        root = ET.parse(extracted / "moodle_backup.xml").getroot()
        information = root.find("information") or root

        course_information: Dict[str, Any] = {}
        course_element = information.find(".//contents/course")
        if course_element is not None:
            course_information["title"] = course_element.findtext("title", "")
            course_information["directory"] = course_element.findtext("directory", "course")

        activities: Dict[str, Any] = {}
        for activity in information.findall(".//contents/activities/activity"):
            cmid = activity.findtext("moduleid") or activity.findtext("cmid")
            if not cmid:
                continue

            activities[cmid] = {
                "cmid": cmid,
                "module_name": activity.findtext("modulename", "") or activity.findtext("module_name", ""),
                "title": activity.findtext("title", ""),
                "directory": activity.findtext("directory", ""),
                "section_id": activity.findtext("sectionid", "") or activity.findtext("section_id", ""),
            }

        sections: List[Dict[str, Any]] = []
        for section in information.findall(".//contents/sections/section"):
            sections.append({
                "section_id": section.findtext("section_id", ""),
                "title": section.findtext("title", ""),
                "directory": section.findtext("directory", ""),
            })

        return {
            "course_info": course_information,
            "sections": sections,
            "activities": activities,
            "file_records": self.read_file_records(extracted),
        }

    # Parse files.xml
    def read_file_records(self, extracted: Path) -> Dict[str, Any]:
        """
        Parse files.xml (the global file table at the backup root) and return a dict
        keyed by file id -> {contenthash, filename, mimetype, filepath}.

        files.xml is separate from moodle_backup.xml and lists every file that was
        included in the backup, including drafts and deleted items.  Some records will
        not have a corresponding entry under files/ on disk - that is handled gracefully
        in read_file_bytes.

        Returns an empty dict if files.xml does not exist.
        """
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
        """
        Parse an XML file within the extracted archive and return its root Element.

        Returns None rather than raising if the file does not exist or is malformed.
        This allows callers to handle missing activities gracefully without try/except
        boilerplate at every call site.
        """
        xml_path = extracted / relative_path
        if not xml_path.exists():
            return None
        try:
            return ET.parse(xml_path).getroot()
        except ET.ParseError:
            return None

    def read_raw_text(self, extracted: Path, relative_path: str) -> Optional[str]:
        """
        Read an XML file as a raw UTF-8 string and return it unchanged.

        Used for fragment storage rather than ET.tostring() so that the original
        byte-for-byte content is preserved (ET serialisation can reorder attributes
        and strip the XML declaration).  Returns None if the file does not exist.
        """
        xml_path = extracted / relative_path
        if not xml_path.exists():
            return None
        return xml_path.read_text(encoding="utf-8")

    def read_file_bytes(self, extracted: Path, contenthash: str) -> Optional[bytes]:
        """
        Read a content file from the content-addressed store at files/HH/FULLHASH.

        Moodle uses the first two hex characters of the SHA-1 hash as a subdirectory
        to avoid putting thousands of files in a single flat directory.

        Returns None rather than raising if the file is absent - this is the normal
        case for draft or deleted file records that appear in files.xml but were not
        included in the backup payload.
        """
        if not contenthash or len(contenthash) < 2:
            return None
        try:
            return (extracted / "files" / contenthash[:2] / contenthash).read_bytes()
        except (FileNotFoundError, KeyError):
            return None

    def read_inforef(self, extracted: Path, activity_directory: str) -> List[str]:
        """
        Return the list of file IDs referenced by an activity's inforef.xml.

        inforef.xml acts as a join table between an activity and the global file
        records in files.xml.  The IDs returned here are looked up in the
        file_records dict to obtain the contenthash needed for read_file_bytes.

        Returns an empty list if inforef.xml is absent or contains no file entries.
        """
        root = self.read_xml(extracted, f"{activity_directory}/inforef.xml")
        if root is None:
            return []
        return [
            fid for f in root.findall(".//file")
            if (fid := f.findtext("id", ""))
        ]

