"""
Domain Entities – Canonical data model for course migration.

Core entities:
- Course: Root entity containing all course data
- ContentNode: Hierarchical content structure (chapter -> sequential -> vertical -> component)
- Assessment: Quiz/problem representation
- Question: Individual question within an assessment
- AnswerOption: Possible answer for a question
- Asset: Files, images, and other media
- RawFragment: Source XML fragments for provenance
- MappingNote: Migration loss tracking
- LtiToolLink: External tool integrations (LTI)
"""

from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from .enums import AssessmentType, NodeType, Severity, SourceSystem
from .raw_fragment import RawFragment


class ContentNode(BaseModel):
    """
    Hierarchical content node in a course.

    Represents any node in the course structure: chapter, sequential, vertical,
    or component (html, video, problem, etc.).
    """

    node_id: str
    node_type: NodeType
    title: Optional[str] = None
    parent_id: Optional[str] = None
    position: int = 0
    children: List["ContentNode"] = []
    assessment_id: Optional[str] = None  # Link to Assessment (if node contains quiz/problem)
    raw_fragment_ids: List[str] = []  # References to RawFragment entities
    metadata: Dict[str, Any] = {}


class Assessment(BaseModel):
    """
    Canonical assessment (quiz/problem) representation.

    Groups questions into a single assessment with a max score and type.
    """

    assessment_id: str
    course_id: str
    title: str
    assessment_type: AssessmentType  # e.g., "quiz", "openassessment", "assignment"
    max_score: Optional[float] = None
    raw_fragment_ids: List[str] = []
    metadata: Dict[str, Any] = {}


class Question(BaseModel):
    """
    Individual question within an assessment.

    Supports various question types: multichoice, text_input, numerical, code, etc.
    """

    question_id: str
    assessment_id: str
    question_type: str  # "multichoice", "text_input", "numerical", "code", etc.
    prompt_text: Optional[str] = None
    points: float = 0.0
    raw_fragment_ids: List[str] = []
    metadata: Dict[str, Any] = {}


class AnswerOption(BaseModel):
    """
    Possible answer option for a question.

    Used for multiple-choice, true/false, and similar question types.
    """

    option_id: str
    question_id: str
    text: str
    is_correct: bool = False


class Asset(BaseModel):
    """
    File asset (images, videos, documents, etc.).

    Tracks file path, MIME type, checksum, and optional source fragment.
    """

    asset_id: str
    course_id: str
    path: str
    mime_type: Optional[str] = None
    checksum: Optional[str] = None
    raw_fragment_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


class MappingNote(BaseModel):
    """
    Migration note for tracking loss or transformations.

    Used to record warnings, errors, or fallbacks during course migration.
    """

    note_id: str
    severity: Severity
    code: str
    message: str
    source_fragment_id: Optional[str] = None
    target_ref: Optional[str] = None
    fallback_used: bool = False


class LtiToolLink(BaseModel):
    """
    LTI (Learning Tools Interoperability) external tool integration.

    Represents links to external tools like publishers, simulators, or grading systems.
    """

    link_id: str
    course_id: str
    content_node_id: str  # ContentNode this link is associated with
    tool_name: str
    launch_url: str
    custom_params: Dict[str, str] = {}
    is_graded: bool = False
    raw_fragment_id: Optional[str] = None


class Course(BaseModel):
    """
    Root course entity containing all course data.

    Aggregates content nodes, assessments, questions, assets, and migration metadata
    into a canonical representation for cross-LMS migration.
    """

    course_id: str
    title: str
    source_system: SourceSystem
    content_nodes: List[ContentNode] = []
    assessments: List[Assessment] = []
    questions: List[Question] = []
    answer_options: List[AnswerOption] = []
    lti_links: List[LtiToolLink] = []
    assets: List[Asset] = []
    raw_fragments: List[RawFragment] = []
    mapping_notes: List[MappingNote] = []
    metadata: Dict[str, Any] = {}
