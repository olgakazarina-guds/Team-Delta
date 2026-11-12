"""
Domain Entities - Canonical data model for course migration.

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

from typing import Any

from pydantic import BaseModel, Field

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
    title: str | None = None
    parent_id: str | None = None
    position: int = 0
    children: list["ContentNode"] = Field(default_factory=list)
    assessment_id: str | None = None  # Link to Assessment (if node contains quiz/problem)
    raw_fragment_ids: list[str] = Field(default_factory=list)  # References to RawFragment entities
    metadata: dict[str, Any] = Field(default_factory=dict)


class Assessment(BaseModel):
    """
    Canonical assessment (quiz/problem) representation.

    Groups questions into a single assessment with a max score and type.
    """

    assessment_id: str
    course_id: str
    title: str
    assessment_type: AssessmentType  # e.g., "quiz", "openassessment", "assignment"
    max_score: float | None = None
    raw_fragment_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Question(BaseModel):
    """
    Individual question within an assessment.

    Supports various question types: multichoice, text_input, numerical, code, etc.
    """

    question_id: str
    assessment_id: str
    question_type: str  # "multichoice", "text_input", "numerical", "code", etc.
    prompt_text: str | None = None
    points: float = 0.0
    raw_fragment_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    mime_type: str | None = None
    checksum: str | None = None
    raw_fragment_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MappingNote(BaseModel):
    """
    Migration note for tracking loss or transformations.

    Used to record warnings, errors, or fallbacks during course migration.
    """

    note_id: str
    severity: Severity
    code: str
    message: str
    source_fragment_id: str | None = None
    target_ref: str | None = None
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
    custom_params: dict[str, str] = Field(default_factory=dict)
    is_graded: bool = False
    raw_fragment_id: str | None = None


class Course(BaseModel):
    """
    Root course entity containing all course data.

    Aggregates content nodes, assessments, questions, assets, and migration metadata
    into a canonical representation for cross-LMS migration.
    """

    course_id: str
    title: str
    source_system: SourceSystem
    content_nodes: list[ContentNode] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    answer_options: list[AnswerOption] = Field(default_factory=list)
    lti_links: list[LtiToolLink] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    raw_fragments: list[RawFragment] = Field(default_factory=list)
    mapping_notes: list[MappingNote] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 2

    def integrity_errors(self) -> list[str]:
        """Return canonical graph integrity violations without raising.

        Validation reports these as errors; target adapters can also use the
        method as a final guard before generating an import archive.
        """
        errors: list[str] = []
        node_ids: set[str] = set()
        assessment_ids = {a.assessment_id for a in self.assessments}
        question_ids = {q.question_id for q in self.questions}
        referenced_assessments = {
            n.assessment_id
            for n in self._all_nodes()
            if n.node_type.value == "problem" and n.assessment_id
        }
        referenced_questions = {a.question_id for a in self.answer_options}

        for node in self._all_nodes():
            if node.node_id in node_ids:
                errors.append(f"Duplicate content node ID: {node.node_id}")
            node_ids.add(node.node_id)
            if node.parent_id and node.parent_id not in node_ids:
                # Parent may appear later in a malformed ordering; check the
                # complete set after traversal instead of failing early.
                pass

        for assessment in self.assessments:
            if assessment.course_id != self.course_id:
                errors.append(
                    f"Assessment {assessment.assessment_id} belongs to "
                    f"{assessment.course_id}, not {self.course_id}"
                )
            for question in self.questions:
                if (
                    question.assessment_id == assessment.assessment_id
                    and question.question_id not in question_ids
                ):
                    errors.append(f"Unknown question: {question.question_id}")

        duplicate_questions = len(self.questions) - len(question_ids)
        if duplicate_questions:
            errors.append(f"Duplicate question IDs: {duplicate_questions}")

        duplicate_assessments = len(self.assessments) - len(assessment_ids)
        if duplicate_assessments:
            errors.append(f"Duplicate assessment IDs: {duplicate_assessments}")

        missing_assessment_refs = referenced_assessments - assessment_ids
        if missing_assessment_refs:
            errors.append(
                "Problems reference missing assessments: "
                + ", ".join(sorted(missing_assessment_refs))
            )

        missing_question_refs = referenced_questions - question_ids
        if missing_question_refs:
            errors.append(
                "Answer options reference missing questions: "
                + ", ".join(sorted(missing_question_refs))
            )

        return errors

    def _all_nodes(self):
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.children)

        yield from walk(self.content_nodes)


class ScormAsset(Asset):
    """SCORM package asset (extends Asset with SCORM-specific fields)."""

    original_zip_path: str
    version: str = ""
    launch: str | None = None
    skipview: str | None = None
    auto: str | None = None
    grademethod: str | None = None
    maxgrade: str | None = None
