"""
===============================================================================
File:        course_parser.py
Institution: German University of Digital Science
Project:     GUDS Coding Camp I Capstone Project
Instructor:  Prof. Dr. Thomas Staubitz
Team:        Team Delta
Members:     Olga Kazarina, Augustine Atta Abrefa, Ronald K. Sebuhinja
Date:        27 May 2026

Description:
    This module is responsible for processing the data extracted from the .mbz archive
    by producing a plain dictionary of the content that feeds into the transformation module.

Usage:
    TBA

===============================================================================
"""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from adapters.moodle.backup_reader import MoodleBackupReader
from domain.enums import NodeType


class MoodleCourseParser:

    def __init__(self):
        self.reader = MoodleBackupReader()
        self.fragments: List[Dict[str, Any]] = []

    def parse(self, mbz_path: str, work_dir: str) -> Dict[str, Any]:
        extracted = self.reader.extract_archive(mbz_path, work_dir)
        manifest = self.reader.read_manifest(extracted)

        course_title = manifest["course_info"].get("title", "Unnamed Course")
        course_shortname = ""
        lang = "en"
        course_id = ""

        course_root = self.reader.read_xml(extracted, "course/course.xml")
        if course_root is not None:
            course_title = course_root.findtext("fullname", course_title) or course_title
            course_shortname = course_root.findtext("shortname", "")
            lang = course_root.findtext("lang", "en")
            course_id = course_root.findtext("id", "")
            self._store_fragment(extracted, "course/course.xml")

        sections: List[Dict[str, Any]] = []
        assessments: List[Dict[str, Any]] = []
        assets: List[Dict[str, Any]] = []

        for pos, section_info in enumerate(manifest["sections"]):
            section_dict = self._parse_section(
                extracted, section_info, manifest, pos, assessments, assets
            )
            if section_dict is not None:
                sections.append(section_dict)

        return {
            "course_id": course_id,
            "course_title": course_title,
            "course_shortname": course_shortname,
            "lang": lang,
            "sections": sections,
            "assessments": assessments,
            "assets": assets,
            "raw_fragments": self.fragments,
        }

    # Section
    def _parse_section(
        self,
        extracted: Path,
        section_info: Dict[str, Any],
        manifest: Dict[str, Any],
        pos: int,
        assessments: List,
        assets: List,) -> Optional[Dict[str, Any]]:

        directory = section_info["directory"]
        section_xml_path = f"{directory}/section.xml"

        root = self.reader.read_xml(extracted, section_xml_path)
        if root is None:
            return None

        raw_name = root.findtext("name", "")
        title = "" if raw_name == "$@NULL@$" else raw_name
        if not title:
            title = f"Section {pos + 1}"

        section_id = root.findtext("id", section_info.get("section_id", ""))
        sequence_text = root.findtext("sequence", "")
        cmids = [c.strip() for c in sequence_text.split(",") if c.strip() and c.strip() != "0"]

        frag_id = self._store_fragment(extracted, section_xml_path)

        activities: List[Dict[str, Any]] = []
        for cmid in cmids:
            activity_information = manifest["activities"].get(cmid)
            if not activity_information:
                continue
            activity_dict = self._parse_activity(extracted, activity_information, manifest, assessments, assets)
            if activity_dict is not None:
                activities.append(activity_dict)

        return {
            "section_id": section_id,
            "title": title,
            "position": pos,
            "raw_fragment_id": frag_id,
            "activities": activities,
        }


    def _parse_activity(
        self,
        extracted: Path,
        activity_info: Dict[str, Any],
        manifest: Dict[str, Any],
        assessments: List,
        assets: List,) -> Optional[Dict[str, Any]]:
        module_name = activity_info["module_name"]
        directory = activity_info["directory"]
        activity_xml_path = f"{directory}/{module_name}.xml"

        root = self.reader.read_xml(extracted, activity_xml_path)
        frag_id = self._store_fragment(extracted, activity_xml_path) if root is not None else None

        base: Dict[str, Any] = {
            "cmid": activity_info["cmid"],
            "module_name": module_name,
            "title": activity_info.get("title", ""),
            "raw_fragment_id": frag_id,
        }

        dispatch = {
            "page":     self._parse_page,
            "label":    self._parse_label,
            "url":      self._parse_url,
            "forum":    self._parse_forum,
            "quiz":     self._parse_quiz,
            "resource": self._parse_resource,
            "scorm":    self._parse_scorm,
        }

        if root is None or module_name not in dispatch:
            base["node_type"] = NodeType.UNKNOWN.value
            return base

        try:
            result = dispatch[module_name](root, activity_info, extracted, manifest, assessments, assets)
        except Exception:
            base["node_type"] = NodeType.UNKNOWN.value
            return base

        if result is None:
            base["node_type"] = NodeType.UNKNOWN.value
            return base

        base.update(result)
        return base


    # Activity parsers — return None on failure
    def _parse_page(self, root, activity_info, extracted, manifest, assessments, assets):
        inner = root.find("page") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        intro = inner.findtext("intro", "")
        content = inner.findtext("content", "")
        return {
            "title": title,
            "node_type": NodeType.PAGE.value,
            "content_html": _join_html(intro, content),
        }

    def _parse_label(self, root, activity_info, extracted, manifest, assessments, assets):
        inner = root.find("label") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        intro = inner.findtext("intro", "")
        return {
            "title": title,
            "node_type": NodeType.HTML.value,
            "content_html": intro,
        }

    def _parse_url(self, root, activity_info, extracted, manifest, assessments, assets):
        inner = root.find("url") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        url = inner.findtext("externalurl", "")
        return {
            "title": title,
            "node_type": NodeType.ACTIVITY.value,
            "metadata": {"activity_type": "url", "externalurl": url},
        }

    def _parse_forum(self, root, activity_info, extracted, manifest, assessments, assets):
        inner = root.find("forum") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        intro = inner.findtext("intro", "")
        return {
            "title": title,
            "node_type": NodeType.FORUM.value,
            "content_html": intro,
        }

    def _parse_quiz(self, root, activity_info, extracted, manifest, assessments, assets):
        inner = root.find("quiz") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        intro = inner.findtext("intro", "")
        assessment_id = str(uuid.uuid4())

        questions = []
        for qi in inner.findall(".//question_instance"):
            questions.append({
                "question_id": str(uuid.uuid4()),
                "assessment_id": assessment_id,
                "question_type": "unknown",
                "prompt_text": None,
                "points": float(qi.findtext("maxmark", "1") or "1"),
            })

        assessments.append({
            "assessment_id": assessment_id,
            "title": title,
            "assessment_type": "quiz",
            "questions": questions,
        })

        return {
            "title": title,
            "node_type": NodeType.QUIZ.value,
            "assessment_id": assessment_id,
            "content_html": intro,
        }

    def _parse_resource(self, root, activity_info, extracted, manifest, assessments, assets):
        inner = root.find("resource") or root
        title = inner.findtext("name", activity_info.get("title", ""))

        file_ids = self.reader.read_inforef(extracted, activity_info["directory"])
        asset_id = None
        for fid in file_ids:
            record = manifest["file_records"].get(fid)
            if not record:
                continue
            contenthash = record.get("contenthash", "")
            filename = record.get("filename", "")
            if not contenthash or not filename or filename == ".":
                continue
            asset_id = str(uuid.uuid4())
            filepath = record.get("filepath", "/").lstrip("/")
            assets.append({
                "asset_id": asset_id,
                "path": filepath + filename,
                "mime_type": record.get("mimetype"),
                "checksum": contenthash,
            })
            break  # primary file only

        return {
            "title": title,
            "node_type": NodeType.ACTIVITY.value,
            "metadata": {"activity_type": "resource", "asset_id": asset_id},
        }

    def _parse_scorm(self, root, activity_info, extracted, manifest, assessments, assets):
        inner = root.find("scorm") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        return {
            "title": title,
            "node_type": NodeType.SCORM.value,
            "metadata": {"activity_type": "scorm"},
        }

    # Fragment helpers
    def _store_fragment(self, extracted: Path, relative_path: str) -> Optional[str]:
        raw_text = self.reader.read_raw_text(extracted, relative_path)
        if raw_text is None:
            return None
        fragment_id = str(uuid.uuid4())
        self.fragments.append({
            "fragment_id": fragment_id,
            "kind": "xml",
            "source_location": {
                "source_system": "moodle",
                "package_path": relative_path,
                "file_path": str(extracted / relative_path),
            },
            "raw_text": raw_text,
            "checksum": None,
        })
        return fragment_id


def _join_html(*parts: str) -> str:
    return "\n".join(p for p in parts if p and p.strip())


