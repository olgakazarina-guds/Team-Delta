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
from .backup_reader import MoodleBackupReader
from domain.enums import NodeType

class MoodleCourseParser:
    """
    Two-phase Moodle source adapter for parsing .mbz backup files.
    
    Parses Moodle course backups into a canonical dictionary representation
    that can be transformed into Open edX format. Extracts course metadata,
    sections, activities, assessments, questions, and assets.
    """
    
    def __init__(self):
        """Initialize the parser with a MoodleBackupReader and empty fragments list."""
        self.reader = MoodleBackupReader()
        self.fragments: List[Dict[str, Any]] = []

    def parse(self, mbz_path: str, work_dir: str) -> Dict[str, Any]:
        """
        Parse a Moodle .mbz backup file into a canonical course dictionary.
        
        Extracts the archive, reads the manifest, parses course metadata from
        course/course.xml, and walks all sections and activities to build a
        complete course representation.
        
        Args:
            mbz_path: Path to the .mbz backup file
            work_dir: Temporary directory for extracted archive contents
            
        Returns:
            Dictionary containing:
            - course_id: Moodle internal course ID (string)
            - course_title: Full display name
            - course_shortname: Short identifier from Moodle URLs
            - lang: Two-letter language code (e.g., 'en')
            - sections: Ordered list of section dicts (see _parse_section)
            - questions_assessments: Question bank assessments from questions.xml
            - assessments: List of quiz assessment dicts from activities
            - assets: List of resource file asset dicts
            - raw_fragments: All XML fragment dicts collected during parsing
            
        Example:
            >>> parser = MoodleCourseParser()
            >>> course_dict = parser.parse("course.mbz", "/tmp/extract")
            >>> print(course_dict["course_title"])
            "History of Russia in Revolution"
        """
        # -------------------------------------------------------------------------
        # Step 1: Extract archive and read manifest
        # -------------------------------------------------------------------------
        extracted = self.reader.extract_archive(mbz_path, work_dir)
        manifest = self.reader.read_manifest(extracted)

        # Initialize course metadata with manifest defaults
        course_title = manifest["course_info"].get("title", "Unnamed Course")
        course_shortname = ""
        lang = "en"
        course_id = ""

        # -------------------------------------------------------------------------
        # Step 2: Read course/course.xml for authoritative metadata
        # -------------------------------------------------------------------------
        # The manifest header snapshot may be stale if the course was renamed 
        # after backup, so course/course.xml is the authoritative source.
        course_root = self.reader.read_xml(extracted, "course/course.xml")
        if course_root is not None:
            course_title = course_root.findtext("fullname", course_title) or course_title
            course_shortname = course_root.findtext("shortname", "")
            lang = course_root.findtext("lang", "en")
            course_id = course_root.findtext("id", "")
            self._store_fragment(extracted, "course/course.xml")

        # -------------------------------------------------------------------------
        # Step 3: Initialize containers for course data
        # -------------------------------------------------------------------------
        sections: List[Dict[str, Any]] = []
        assessments: List[Dict[str, Any]] = []
        assets: List[Dict[str, Any]] = []
        
        # -------------------------------------------------------------------------
        # Step 4: Load question bank assessments from questions.xml
        # -------------------------------------------------------------------------
        questions_assessments = self._load_questions(extracted)

        # -------------------------------------------------------------------------
        # Step 5: Parse all sections and their activities
        # -------------------------------------------------------------------------
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
            "questions_assessments": questions_assessments,
            "assessments": assessments,
            "assets": assets,
            "raw_fragments": self.fragments,
        }

    def _parse_section(
        self,
        extracted: Path,
        section_info: Dict[str, Any],
        manifest: Dict[str, Any],
        pos: int,
        assessments: List,
        assets: List,
    ) -> Optional[Dict[str, Any]]:
        """
        Parse one Moodle section directory into a section dictionary.
        
        Parses section.xml to extract section metadata and resolves all
        activities referenced in the <sequence> field using the manifest
        activity lookup table.
        
        Moodle uses '$@NULL@$' for numbered topics with no custom title.
        These are treated as empty and receive a positional fallback title.
        
        Args:
            extracted: Path to extracted .mbz directory
            section_info: Section metadata from manifest
            manifest: Full parsed manifest with activities and file_records
            pos: Zero-based section position (preserves manifest order)
            assessments: Shared list to append quiz assessments to
            assets: Shared list to append resource assets to
            
        Returns:
            Section dictionary with:
            - section_id: Moodle internal section ID
            - title: Display name (or "Section N" for numbered topics)
            - position: Zero-based index
            - raw_fragment_id: ID of stored section.xml fragment
            - activities: Ordered list of activity dicts for this section
            
            Returns None if section.xml is missing or unreadable.
        """
        directory = section_info["directory"]
        section_xml_path = f"{directory}/section.xml"

        root = self.reader.read_xml(extracted, section_xml_path)
        if root is None:
            return None

        # Handle Moodle's NULL placeholder for numbered topics
        raw_name = root.findtext("name", "")
        title = "" if raw_name == "$@NULL@$" else raw_name
        if not title:
            title = f"Section {pos + 1}"

        section_id = root.findtext("id", section_info.get("section_id", ""))
        
        # Parse comma-separated cmids from <sequence> field
        sequence_text = root.findtext("sequence", "")
        cmids = [c.strip() for c in sequence_text.split(",") if c.strip() and c.strip() != "0"]

        frag_id = self._store_fragment(extracted, section_xml_path)

        # Parse all activities referenced in this section
        activities: List[Dict[str, Any]] = []
        for cmid in cmids:
            activity_information = manifest["activities"].get(cmid)
            if not activity_information:
                continue
            activity_dict = self._parse_activity(
                extracted, activity_information, manifest, assessments, assets
            )
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
        assets: List,
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a Moodle activity by delegating to module-specific parsers.
        
        Resolves an activity by module type (page, label, quiz, etc.) and
        calls the appropriate parser. Returns a dict with at minimum:
        cmid, module_name, title, raw_fragment_id, node_type.
        
        Type-specific parsers add further keys (content_html, assessment_id,
        metadata, etc.). If the XML is missing, module is unrecognized, or
        the parser raises an exception, returns NodeType.UNKNOWN rather than
        propagating the error — this ensures one malformed activity doesn't
        abort the entire course parse.
        
        Args:
            extracted: Path to extracted .mbz directory
            activity_info: Activity metadata from manifest
            manifest: Full parsed manifest
            assessments: Shared list to append quiz assessments to
            assets: Shared list to append resource assets to
            
        Returns:
            Activity dictionary with module-specific fields, or None on failure
        """
        module_name = activity_info["module_name"]
        directory = activity_info["directory"]
        activity_xml_path = f"{directory}/{module_name}.xml"

        root = self.reader.read_xml(extracted, activity_xml_path)
        frag_id = self._store_fragment(extracted, activity_xml_path) if root is not None else None

        # Base activity dict (always included)
        base: Dict[str, Any] = {
            "cmid": activity_info["cmid"],
            "module_name": module_name,
            "title": activity_info.get("title", ""),
            "raw_fragment_id": frag_id,
        }

        # Dispatch table for module-specific parsers
        dispatch = {
            "page": self._parse_page,
            "label": self._parse_label,
            "url": self._parse_url,
            "forum": self._parse_forum,
            "quiz": self._parse_quiz,
            "resource": self._parse_resource,
            "scorm": self._parse_scorm,
            "videofile": self._parse_video,
        }

        # Handle missing XML or unrecognized module type
        if root is None or module_name not in dispatch:
            base["node_type"] = NodeType.UNKNOWN.value
            return base

        # Call module-specific parser with graceful error handling
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

    # -------------------------------------------------------------------------
    # Activity Parsers — return None on failure
    # -------------------------------------------------------------------------

    def _parse_page(
        self, root, activity_info, extracted, manifest, assessments, assets
    ):
        """
        Parse a Moodle 'page' activity.
        
        Pages have two HTML fields: intro (shown in course outline) and content
        (full page body). Both are joined into a single content_html string.
        
        Note: ElementTree automatically unescapes HTML entities in CDATA sections,
        so do not call html.unescape() again or entities will be double-decoded.
        
        Args:
            root: Parsed XML root element
            activity_info: Activity metadata from manifest
            extracted, manifest, assessments, assets: Unused but required for interface consistency
            
        Returns:
            Dictionary with title, node_type=PAGE, and content_html
        """
        inner = root.find("page") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        intro = inner.findtext("intro", "")
        content = inner.findtext("content", "")
        return {
            "title": title,
            "node_type": NodeType.PAGE.value,
            "content_html": _join_html(intro, content),
        }

    def _parse_label(
        self, root, activity_info, extracted, manifest, assessments, assets
    ):
        """
        Parse a Moodle 'label' activity.
        
        Labels are inline HTML snippets embedded directly in the course outline.
        Unlike pages, they have only an intro field and no separate content body.
        
        Args:
            root: Parsed XML root element
            activity_info: Activity metadata from manifest
            
        Returns:
            Dictionary with title, node_type=HTML, and content_html (intro only)
        """
        inner = root.find("label") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        intro = inner.findtext("intro", "")
        return {
            "title": title,
            "node_type": NodeType.HTML.value,
            "content_html": intro,
        }

    def _parse_url(
        self, root, activity_info, extracted, manifest, assessments, assets
    ):
        """
        Parse a Moodle 'url' activity.
        
        External URLs are stored in the <externalurl> element. If the URL points
        to YouTube, we extract the video ID and mark it as a VIDEO component.
        
        Args:
            root: Parsed XML root element
            activity_info: Activity metadata from manifest
            
        Returns:
            Dictionary with title, node_type (VIDEO or ACTIVITY), and metadata
        """
        import re
        inner = root.find("url") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        url = inner.findtext("externalurl", "")
        
        # Detect YouTube URLs and extract video ID
        youtube_id = None
        youtube_patterns = [
            r"(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})",
            r"(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})",
        ]
        
        for pattern in youtube_patterns:
            match = re.search(pattern, url)
            if match:
                youtube_id = match.group(1)
                break
        
        if youtube_id:
            return {
                "title": title,
                "node_type": NodeType.VIDEO.value,
                "metadata": {
                    "activity_type": "youtube",
                    "youtube_id": youtube_id,
                    "externalurl": url,
                },
            }
        
        return {
            "title": title,
            "node_type": NodeType.ACTIVITY.value,
            "metadata": {"activity_type": "url", "externalurl": url},
        }


    def _parse_forum(
        self, root, activity_info, extracted, manifest, assessments, assets
    ):
        """
        Parse a Moodle 'forum' activity.
        
        For MVP conversion purposes, only the forum name and intro HTML are captured.
        Individual posts and threads are not included in a standard .mbz backup.
        
        Args:
            root: Parsed XML root element
            activity_info: Activity metadata from manifest
            
        Returns:
            Dictionary with title, node_type=FORUM, and content_html (intro only)
        """
        inner = root.find("forum") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        intro = inner.findtext("intro", "")
        return {
            "title": title,
            "node_type": NodeType.FORUM.value,
            "content_html": intro,
        }

    def _parse_quiz(
        self, root, activity_info, extracted, manifest, assessments, assets
    ):
        """
        Parse a Moodle 'quiz' activity.
        
        Creates an assessment dict and appends it to the shared assessments list
        so TransformService can build an Assessment domain object. The activity
        node stores an assessment_id reference to link the two.
        
        Question instances are captured as lightweight stubs with point values.
        Full question content (prompt text, answer options) lives in the question
        bank and is parsed in _load_questions (Phase 2 concern).
        
        Args:
            root: Parsed XML root element
            activity_info: Activity metadata from manifest
            
        Returns:
            Dictionary with title, node_type=QUIZ, assessment_id, content_html,
            and metadata.question_ids (list of question IDs from question bank)
        """
        inner = root.find("quiz") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        intro = inner.findtext("intro", "")
        assessment_id = str(uuid.uuid4())

        # Parse question instances (lightweight stubs)
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

        # Collect question IDs for linking to question bank
        question_ids = []
        for qi in inner.findall(".//question_instance"):
            qid = qi.findtext("questionid")
            if qid:
                question_ids.append(qid)

        return {
            "title": title,
            "node_type": NodeType.QUIZ.value,
            "assessment_id": assessment_id,
            "content_html": intro,
            "metadata": {
                "question_ids": question_ids,
                "quiz_id": inner.findtext("id"),
            },
        }

    def _parse_resource(
        self, root, activity_info, extracted, manifest, assessments, assets
    ):
        """
        Parse a Moodle 'resource' activity (downloadable file).
        
        Resolution chain:
          1. Read inforef.xml to get file ID(s) for this activity
          2. Look up each ID in manifest.file_records to get contenthash
          3. Create an asset dict for the first valid file found
        
        Only the primary content file is captured. Files with filename '.' are
        directory sentinel entries and are skipped. If the physical file is
        absent from files/ (draft or deleted), the asset still records the
        contenthash — read_file_bytes handles missing bytes gracefully.
        
        Args:
            root: Parsed XML root element
            activity_info: Activity metadata from manifest
            
        Returns:
            Dictionary with title, node_type=ACTIVITY, and metadata.asset_id
        """
        inner = root.find("resource") or root
        title = inner.findtext("name", activity_info.get("title", ""))

        file_ids = self.reader.read_inforef(extracted, activity_info["directory"])
        asset_id = None
        is_video = False
        for fid in file_ids:
            record = manifest["file_records"].get(fid)
            if not record:
                continue
            contenthash = record.get("contenthash", "")
            filename = record.get("filename", "")
            mimetype = record.get("mimetype", "")
            if not contenthash or not filename or filename == ".":
                continue

            # Check if this is a video file
            if mimetype and "video" in mimetype.lower():
                is_video = True
            elif not mimetype:
                # Fallback: check file extension
                ext = filename.lower().split(".")[-1] if "." in filename else ""
                if ext in ("mp4", "webm", "ogg", "mov", "avi"):
                    is_video = True

            asset_id = str(uuid.uuid4())
            filepath = record.get("filepath", "/").lstrip("/")
            assets.append({
                "asset_id": asset_id,
                "path": filepath + filename,
                "mime_type": record.get("mimetype"),
                "checksum": contenthash,
                "is_video": is_video,
            })
            break  # primary file only

        return {
            "title": title,
            "node_type": NodeType.VIDEO.value if is_video else NodeType.ACTIVITY.value,
            "metadata": {
                "activity_type": "video" if is_video else "resource", 
                "asset_id": asset_id,
            },
        }

    def _parse_scorm(
        self, root, activity_info, extracted, manifest, assessments, assets
    ):
        """
        Parse a Moodle 'SCORM' activity.
        
        SCORM packages contain their own internal manifest and assets. For MVP
        purposes, only the activity name is captured. Full SCORM unpacking is
        slated for Phase 2.
        
        Args:
            root: Parsed XML root element
            activity_info: Activity metadata from manifest
            
        Returns:
            Dictionary with title, node_type=SCORM, and metadata.activity_type
        """
        inner = root.find("scorm") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        return {
            "title": title,
            "node_type": NodeType.SCORM.value,
            "metadata": {"activity_type": "scorm"},
        }

    def _parse_video(
        self, root, activity_info, extracted, manifest, assessments, assets
    ):
        """
        Parse a Moodle 'video' activity (if using mod_videofile plugin) 
        or extract video from resource/url activities.
        
        For video files (.mp4, .webm, .ogg), creates an asset and returns
        metadata with video URL.
        
        Args:
            root: Parsed XML root element
            activity_info: Activity metadata from manifest
            
        Returns:
            Dictionary with title, node_type=VIDEO, and metadata.asset_id
        """
        inner = root.find("videofile") or root.find("resource") or root
        title = inner.findtext("name", activity_info.get("title", ""))
        
        # Get file IDs from inforef.xml
        file_ids = self.reader.read_inforef(extracted, activity_info["directory"])
        asset_id = None
        video_url = None
        
        for fid in file_ids:
            record = manifest["file_records"].get(fid)
            if not record:
                continue
            contenthash = record.get("contenthash", "")
            filename = record.get("filename", "")
            mimetype = record.get("mimetype", "")
            
            # Check if this is a video file
            if not contenthash or not filename:
                continue
            if mimetype and "video" in mimetype.lower():
                asset_id = str(uuid.uuid4())
                filepath = record.get("filepath", "/").lstrip("/")
                assets.append({
                    "asset_id": asset_id,
                    "path": filepath + filename,
                    "mime_type": mimetype,
                    "checksum": contenthash,
                    "is_video": True,
                })
                video_url = filepath + filename
                break
        
        return {
            "title": title,
            "node_type": NodeType.VIDEO.value,
            "metadata": {
                "activity_type": "video",
                "asset_id": asset_id,
                "video_url": video_url,
            },
        }

    # -------------------------------------------------------------------------
    # Fragment Helpers
    # -------------------------------------------------------------------------

    def _store_fragment(self, extracted: Path, relative_path: str) -> Optional[str]:
        """
        Store a file as a raw XML fragment and return its fragment_id.
        
        Reads the file as raw text (not parsed XML) to preserve the original
        formatting exactly — important for accuracy and debugging. The fragment
        is appended to self.fragments for later inclusion in the course dict.
        
        Returns None if the file does not exist, so callers can treat a missing
        fragment_id as an expected absence rather than an error.
        
        Args:
            extracted: Path to extracted .mbz directory
            relative_path: Path relative to extracted directory (e.g., "course/course.xml")
            
        Returns:
            Fragment ID string, or None if file doesn't exist
        """
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

    # -------------------------------------------------------------------------
    # Question Bank Parsing
    # -------------------------------------------------------------------------

    def _load_questions(self, extracted: Path) -> List[Dict[str, Any]]:
        """
        Load and parse questions.xml from the Moodle backup.
        
        Moodle stores question bank data in a separate questions.xml file at
        the root of the extracted archive. This method parses that file and
        returns a list of question assessment dicts with full question data
        (prompt text, answer options, etc.).
        
        The returned structure is passed to TransformService._transform_moodle
        where it becomes Question and AnswerOption domain objects.
        
        Args:
            extracted: Path to extracted .mbz directory
            
        Returns:
            List of question assessment dicts with structure:
            [
                {
                    "assessment_id": str,
                    "title": str,
                    "original_question_ids": [str, ...],
                    "questions": [
                        {
                            "question_id": str,
                            "question_type": str,
                            "prompt_text": str,
                            "points": float,
                            "answer_options": [{"text": str, "is_correct": bool}, ...]
                        },
                        ...
                    ]
                },
                ...
            ]
            
            Returns empty list if questions.xml doesn't exist or can't be parsed.
        """
        questions_xml = extracted / "questions.xml"
        if not questions_xml.exists():
            return []
        
        from .question_parser import parse_questions
        return parse_questions(str(questions_xml))


# -------------------------------------------------------------------------
# Module-Level Helpers
# -------------------------------------------------------------------------

def _join_html(*parts: str) -> str:
    """
    Join non-empty HTML strings with a newline separator.
    
    Used by _parse_page and _parse_label to combine intro and content HTML.
    
    Args:
        *parts: HTML strings to join
        
    Returns:
        Joined string with non-empty parts separated by newlines
    """
    return "\n".join(p for p in parts if p and p.strip())
