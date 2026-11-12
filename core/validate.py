"""Canonical course validation and target-readiness analysis."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from core.errors import UnsupportedTargetError
from core.identity import stable_id
from domain.entities import ContentNode, Course, MappingNote
from domain.enums import NodeType, Severity

logger = logging.getLogger(__name__)

_TARGETS = {"openedx", "moodle"}

_TARGET_NODE_SUPPORT = {
    "openedx": {
        NodeType.CHAPTER,
        NodeType.SEQUENTIAL,
        NodeType.VERTICAL,
        NodeType.HTML,
        NodeType.PAGE,
        NodeType.VIDEO,
        NodeType.PROBLEM,
        NodeType.OPENASSESSMENT,
        NodeType.FORUM,
        NodeType.LTI,
        NodeType.SCORM,
        NodeType.ACTIVITY,
    },
    "moodle": {
        NodeType.CHAPTER,
        NodeType.SEQUENTIAL,
        NodeType.VERTICAL,
        NodeType.HTML,
        NodeType.PAGE,
        NodeType.VIDEO,
        NodeType.PROBLEM,
        NodeType.OPENASSESSMENT,
        NodeType.FORUM,
        NodeType.LTI,
        NodeType.SCORM,
        NodeType.ACTIVITY,
    },
}


class ValidationService:
    """Validate structural integrity and conversion readiness."""

    def validate(self, course: Course, target: str | None = None) -> list[MappingNote]:
        logger.info("Validating course '%s'", course.title)
        target_name = self._normalise_target(target)
        notes: list[MappingNote] = []

        if not course.content_nodes:
            notes.append(
                self._note(
                    course,
                    "EMPTY_COURSE",
                    Severity.ERROR,
                    "Course has no content nodes (chapters/sequentials/verticals). "
                    "Migration will produce an empty export.",
                    target_name,
                )
            )
            logger.info("Validation found no content")
            return notes

        chapters = [n for n in course.content_nodes if n.node_type == NodeType.CHAPTER]
        if not chapters:
            notes.append(
                self._note(
                    course,
                    "NO_CHAPTERS",
                    Severity.WARNING,
                    "Course has no chapter nodes. Content may not organize properly in target LMS.",
                    target_name,
                )
            )

        unsupported_nodes = [
            n for n in self._iterate_nodes(course.content_nodes) if n.node_type == NodeType.UNKNOWN
        ]
        if unsupported_nodes:
            notes.append(
                self._note(
                    course,
                    "UNSUPPORTED_NODES",
                    Severity.WARNING,
                    f"Found {len(unsupported_nodes)} nodes with type 'unknown'. "
                    "These will be converted as placeholders.",
                    target_name,
                )
            )

        if target_name:
            allowed = _TARGET_NODE_SUPPORT[target_name]
            target_unsupported = [
                n for n in self._iterate_nodes(course.content_nodes) if n.node_type not in allowed
            ]
            if target_unsupported:
                notes.append(
                    self._note(
                        course,
                        "TARGET_UNSUPPORTED_NODES",
                        Severity.WARNING,
                        f"{len(target_unsupported)} node(s) are not natively supported "
                        f"by {target_name} and will be mapped to a fallback.",
                        target_name,
                        "target",
                    )
                )

        assessments_without_questions = [
            a
            for a in course.assessments
            if not any(q.assessment_id == a.assessment_id for q in course.questions)
        ]
        if assessments_without_questions:
            notes.append(
                self._note(
                    course,
                    "EMPTY_ASSESSMENT",
                    Severity.WARNING,
                    f"{len(assessments_without_questions)} assessment(s) have no questions "
                    "linked. They will be converted as empty problems.",
                    target_name,
                )
            )

        problems_without_assessment = [
            n
            for n in self._iterate_nodes(course.content_nodes)
            if n.node_type == NodeType.PROBLEM and not n.assessment_id
        ]
        if problems_without_assessment:
            notes.append(
                self._note(
                    course,
                    "PROBLEM_NO_ASSESSMENT",
                    Severity.WARNING,
                    f"{len(problems_without_assessment)} problem component(s) have no "
                    "assessment linked. They will be converted as placeholders.",
                    target_name,
                )
            )

        videos = [
            n for n in self._iterate_nodes(course.content_nodes) if n.node_type == NodeType.VIDEO
        ]
        videos_without_source = [
            v
            for v in videos
            if not (
                v.metadata.get("youtube_id")
                or v.metadata.get("asset_id")
                or v.metadata.get("video_url")
            )
        ]
        if videos_without_source:
            notes.append(
                self._note(
                    course,
                    "VIDEO_NO_SOURCE",
                    Severity.WARNING,
                    f"{len(videos_without_source)}/{len(videos)} video(s) have no source "
                    "(YouTube ID or asset). They will be converted as placeholders.",
                    target_name,
                )
            )

        video_assets = [a for a in course.assets if a.metadata.get("is_video")]
        if video_assets:
            notes.append(
                self._note(
                    course,
                    "VIDEO_ASSETS_FOUND",
                    Severity.INFO,
                    f"Found {len(video_assets)} video file(s) in source. These will be "
                    "copied to the target course.",
                    target_name,
                )
            )

        unsupported_question_types: list[str] = []
        for q in course.questions:
            if q.question_type not in (
                "multichoice",
                "multiselect",
                "truefalse",
                "shortanswer",
                "numerical",
                "essay",
                "description",
            ):
                unsupported_question_types.append(q.question_type)
            elif q.question_type in ("essay", "description"):
                notes.append(
                    self._note(
                        course,
                        "ESSAY_QUESTION",
                        Severity.INFO,
                        f"Question '{q.question_id}' is an essay/description type. "
                        "It will be converted as a placeholder requiring manual review.",
                        target_name,
                        q.question_id,
                        q.raw_fragment_ids[0] if q.raw_fragment_ids else None,
                    )
                )

        if unsupported_question_types:
            notes.append(
                self._note(
                    course,
                    "UNSUPPORTED_QUESTION_TYPE",
                    Severity.WARNING,
                    f"Found {len(unsupported_question_types)} question(s) with unsupported "
                    f"types: {sorted(set(unsupported_question_types))}. "
                    "They will be converted as placeholders.",
                    target_name,
                )
            )

        html_nodes = [
            n
            for n in self._iterate_nodes(course.content_nodes)
            if n.node_type == NodeType.HTML and n.metadata.get("content_html")
        ]
        html_with_video_tags = [
            h for h in html_nodes if "<video" in h.metadata.get("content_html", "").lower()
        ]
        if html_with_video_tags:
            notes.append(
                self._note(
                    course,
                    "EMBEDDED_VIDEO_IN_HTML",
                    Severity.WARNING,
                    f"{len(html_with_video_tags)} HTML component(s) contain embedded "
                    "<video> tags. These videos are not extracted separately and may not "
                    "play in target LMS.",
                    target_name,
                )
            )

        url_nodes = [
            n
            for n in self._iterate_nodes(course.content_nodes)
            if n.node_type == NodeType.ACTIVITY and n.metadata.get("activity_type") == "url"
        ]
        if url_nodes:
            notes.append(
                self._note(
                    course,
                    "EXTERNAL_URLS",
                    Severity.INFO,
                    f"Found {len(url_nodes)} external URL(s). YouTube videos will be "
                    "converted; other URLs become activity links.",
                    target_name,
                )
            )

        for message in course.integrity_errors():
            notes.append(
                self._note(course, "INTEGRITY_ERROR", Severity.ERROR, message, target_name)
            )

        notes.append(
            self._note(
                course,
                "MIGRATION_SUMMARY",
                Severity.INFO,
                self._summary(course, chapters, notes, target_name),
                target_name,
            )
        )

        course.mapping_notes = notes
        logger.debug("Validation produced %d note(s)", len(notes))
        return notes

    @staticmethod
    def _normalise_target(target: str | None) -> str | None:
        if target is None or not str(target).strip():
            return None
        name = str(target).strip().lower()
        if name not in _TARGETS:
            raise UnsupportedTargetError(f"Unsupported validation target: {target}")
        return name

    @staticmethod
    def _note(
        course: Course,
        code: str,
        severity: Severity,
        message: str,
        target: str | None,
        *identity_parts: object,
        target_ref: str | None = None,
    ) -> MappingNote:
        note_id = stable_id(
            "note",
            course.course_id,
            target or "canonical",
            code,
            message,
            *identity_parts,
        )
        return MappingNote(
            note_id=note_id,
            severity=severity,
            code=code,
            message=message,
            source_fragment_id=None,
            target_ref=target_ref or target,
            fallback_used=severity != Severity.INFO,
        )

    @staticmethod
    def _summary(
        course: Course,
        chapters: list[ContentNode],
        notes: list[MappingNote],
        target: str | None,
    ) -> str:
        warnings = sum(1 for n in notes if n.severity == Severity.WARNING)
        errors = sum(1 for n in notes if n.severity == Severity.ERROR)
        target_text = f" | Target: {target}" if target else ""
        return (
            f"Course: {course.title} | Chapters: {len(chapters)} | "
            f"Assessments: {len(course.assessments)} | "
            f"Questions: {len(course.questions)} | Assets: {len(course.assets)} | "
            f"Warnings: {warnings} | Errors: {errors}{target_text}"
        )

    def _iterate_nodes(self, nodes: Iterable[ContentNode]):
        for node in nodes:
            yield node
            yield from self._iterate_nodes(node.children)
