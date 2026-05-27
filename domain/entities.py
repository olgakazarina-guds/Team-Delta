from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from .enums import SourceSystem, NodeType, AssessmentType, Severity
from .raw_fragment import RawFragment

# ============================================================
# Content structure
# ============================================================
class ContentNode(BaseModel):
    node_id: str
    node_type: NodeType
    title: Optional[str] = None
    parent_id: Optional[str] = None
    position: int = 0
    children: List["ContentNode"] = []
    assessment_id: Optional[str] = None          # link to an Assessment (if this node contains a quiz/problem)
    raw_fragment_ids: List[str] = []             # references to RawFragment
    metadata: Dict[str, Any] = {}

# ============================================================
# Assessment & questions (canonical quiz/problem representation)
# ============================================================
class Assessment(BaseModel):
    assessment_id: str
    course_id: str
    title: str
    assessment_type: AssessmentType               # e.g., "quiz", "openassessment", "assignment"
    max_score: Optional[float] = None
    raw_fragment_ids: List[str] = []
    metadata: Dict[str, Any] = {}

class Question(BaseModel):
    question_id: str
    assessment_id: str
    question_type: str                            # "multichoice", "text_input", "numerical", "code", etc.
    prompt_text: Optional[str] = None
    points: float = 0.0
    raw_fragment_ids: List[str] = []
    metadata: Dict[str, Any] = {}

class AnswerOption(BaseModel):
    option_id: str
    question_id: str
    text: str
    is_correct: bool = False

# ============================================================
# Assets (files, images, etc.)
# ============================================================
class Asset(BaseModel):
    asset_id: str
    course_id: str
    path: str
    mime_type: Optional[str] = None
    checksum: Optional[str] = None
    raw_fragment_id: Optional[str] = None

# ============================================================
# Migration notes (loss tracking)
# ============================================================
class MappingNote(BaseModel):
    note_id: str
    severity: Severity
    code: str
    message: str
    source_fragment_id: Optional[str] = None
    target_ref: Optional[str] = None
    fallback_used: bool = False

# ============================================================
# LTI (external tools) 
# ============================================================
class LtiToolLink(BaseModel):
    link_id: str
    course_id: str
    content_node_id: str                          # which node launches this tool
    tool_name: str
    launch_url: str
    custom_params: Dict[str, str] = {}
    is_graded: bool = False
    raw_fragment_id: Optional[str] = None

# ============================================================
# Course root
# ============================================================
class Course(BaseModel):
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
