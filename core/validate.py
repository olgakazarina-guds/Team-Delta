from domain.entities import Course, MappingNote
from domain.enums import Severity
import uuid

class ValidationService:
    def validate(self, course: Course) -> list:
        notes = []
        
        # Check if course has any content nodes
        if not course.content_nodes:
            notes.append(MappingNote(
                note_id=str(uuid.uuid4()),
                severity=Severity.ERROR,
                code="EMPTY_COURSE",
                message="Course has no content nodes (chapters/sequentials/verticals). Migration will produce empty export.",
                source_fragment_id=None,
                fallback_used=False
            ))
            return notes  # Nothing else to validate
        
        # Check for chapter → sequential → vertical hierarchy
        chapters = [n for n in course.content_nodes if n.node_type.value == "chapter"]
        if not chapters:
            notes.append(MappingNote(
                note_id=str(uuid.uuid4()),
                severity=Severity.WARNING,
                code="NO_CHAPTERS",
                message="Course has no chapter nodes. Content may not organize properly in target LMS.",
                source_fragment_id=None,
                fallback_used=False
            ))
        
        # Check for unsupported node types
        unsupported = []
        for node in self._iterate_nodes(course.content_nodes):
            if node.node_type.value == "unknown":
                unsupported.append(node.node_type.value)
        if unsupported:
            notes.append(MappingNote(
                note_id=str(uuid.uuid4()),
                severity=Severity.WARNING,
                code="UNSUPPORTED_NODES",
                message=f"Found {len(unsupported)} nodes with type 'unknown'. These will be converted as placeholders.",
                source_fragment_id=None,
                fallback_used=False
            ))
        
        # Check for assessments without questions
        assessments_without_questions = [
            a for a in course.assessments 
            if not any(q.assessment_id == a.assessment_id for q in course.questions)
        ]
        if assessments_without_questions:
            notes.append(MappingNote(
                note_id=str(uuid.uuid4()),
                severity=Severity.WARNING,
                code="EMPTY_ASSESSMENT",
                message=f"{len(assessments_without_questions)} assessment(s) have no questions linked. They will be converted as empty problems.",
                source_fragment_id=None,
                fallback_used=False
            ))
        
        # Check for_problem nodes without assessment_id
        problems_without_assessment = [
            n for n in self._iterate_nodes(course.content_nodes)
            if n.node_type.value == "problem" and not n.assessment_id
        ]
        if problems_without_assessment:
            notes.append(MappingNote(
                note_id=str(uuid.uuid4()),
                severity=Severity.WARNING,
                code="PROBLEM_NO_ASSESSMENT",
                message=f"{len(problems_without_assessment)} problem component(s) have no assessment linked. They will be converted as placeholders.",
                source_fragment_id=None,
                fallback_used=False
            ))
        
        # Check for video nodes (will be converted with placeholder if no video data)
        videos = [
            n for n in self._iterate_nodes(course.content_nodes)
            if n.node_type.value == "video"
        ]
        if videos:
            videos_with_metadata = [
                v for v in videos 
                if v.metadata and ("youtube_id" in v.metadata or "asset_id" in v.metadata)
            ]
            videos_without_metadata = len(videos) - len(videos_with_metadata)
            if videos_without_metadata > 0:
                notes.append(MappingNote(
                    note_id=str(uuid.uuid4()),
                    severity=Severity.WARNING,
                    code="VIDEO_NO_SOURCE",
                    message=f"{videos_without_metadata}/{len(videos)} video(s) have no source (YouTube ID or asset). They will be converted as placeholders.",
                    source_fragment_id=None,
                    fallback_used=False
                ))
        
        # Check for assets that may not be copied (self-hosted videos)
        if course.assets:
            video_assets = [a for a in course.assets if hasattr(a, 'metadata') and a.metadata.get('is_video')]
            if video_assets:
                notes.append(MappingNote(
                    note_id=str(uuid.uuid4()),
                    severity=Severity.INFO,
                    code="VIDEO_ASSETS_FOUND",
                    message=f"Found {len(video_assets)} video file(s) in source. These will be copied to asset/ folder.",
                    source_fragment_id=None,
                    fallback_used=False
                ))
        
        # Check for question types that may not fully convert
        unsupported_question_types = []
        for q in course.questions:
            if q.question_type not in ("multichoice", "truefalse", "shortanswer", "numerical", "essay", "description"):
                unsupported_question_types.append(q.question_type)
            elif q.question_type in ("essay", "description"):
                notes.append(MappingNote(
                    note_id=str(uuid.uuid4()),
                    severity=Severity.INFO,
                    code="ESSAY_QUESTION",
                    message=f"Question '{q.question_id}' is an essay/description type. It will be converted as a placeholder requiring manual review.",
                    source_fragment_id=q.raw_fragment_ids[0] if q.raw_fragment_ids else None,
                    fallback_used=True
                ))
        
        if unsupported_question_types:
            notes.append(MappingNote(
                note_id=str(uuid.uuid4()),
                severity=Severity.WARNING,
                code="UNSUPPORTED_QUESTION_TYPE",
                message=f"Found {len(unsupported_question_types)} question(s) with unsupported types: {list(set(unsupported_question_types))}. They will be converted as placeholders.",
                source_fragment_id=None,
                fallback_used=False
            ))
        
        # Check for HTML content with embedded videos (not extracted)
        html_nodes = [
            n for n in self._iterate_nodes(course.content_nodes)
            if n.node_type.value == "html" and n.metadata.get("content_html")
        ]
        html_with_video_tags = [
            h for h in html_nodes 
            if h.metadata.get("content_html") and "<video" in h.metadata.get("content_html", "")
        ]
        if html_with_video_tags:
            notes.append(MappingNote(
                note_id=str(uuid.uuid4()),
                severity=Severity.WARNING,
                code="EMBEDDED_VIDEO_IN_HTML",
                message=f"{len(html_with_video_tags)} HTML component(s) contain embedded <video> tags. These videos are not extracted separately and may not play in target LMS.",
                source_fragment_id=None,
                fallback_used=False
            ))
        
        # Check for external URLs (YouTube, Vimeo, etc.)
        url_nodes = [
            n for n in self._iterate_nodes(course.content_nodes)
            if n.node_type.value == "activity" and n.metadata.get("activity_type") == "url"
        ]
        if url_nodes:
            notes.append(MappingNote(
                note_id=str(uuid.uuid4()),
                severity=Severity.INFO,
                code="EXTERNAL_URLS",
                message=f"Found {len(url_nodes)} external URL(s). YouTube videos will be converted; other URLs become activity links.",
                source_fragment_id=None,
                fallback_used=False
            ))
        
        # Summary statistics
        notes.append(MappingNote(
            note_id=str(uuid.uuid4()),
            severity=Severity.INFO,
            code="MIGRATION_SUMMARY",
            message=(
                f"Course: {course.title} | "
                f"Chapters: {len(chapters)} | "
                f"Assessments: {len(course.assessments)} | "
                f"Questions: {len(course.questions)} | "
                f"Assets: {len(course.assets)} | "
                f"Warnings: {sum(1 for n in notes if n.severity == Severity.WARNING)} | "
                f"Errors: {sum(1 for n in notes if n.severity == Severity.ERROR)}"
            ),
            source_fragment_id=None,
            fallback_used=False
        ))
        
        return notes

    def _iterate_nodes(self, nodes):
        for node in nodes:
            yield node
            yield from self._iterate_nodes(node.children)
