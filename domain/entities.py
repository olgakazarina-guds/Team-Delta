from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from .enums import SourceSystem, NodeType, AssessmentType, Severity
from .raw_fragment import RawFragment

class ContentNode(BaseModel):
    node_id: str
    node_type: NodeType
    title: Optional[str] = None
    parent_id: Optional[str] = None
    position: int = 0
    children: List["ContentNode"] = []
    raw_fragment_ids: List[str] = []          # references to RawFragment
    metadata: Dict[str, Any] = {}

class Assessment(BaseModel):
    assessment_id: str
    course_id: str
    title: str
    assessment_type: AssessmentType
    max_score: Optional[float] = None
    raw_fragment_ids: List[str] = []
    metadata: Dict[str, Any] = {}

class Question(BaseModel):
    question_id: str
    assessment_id: str
    question_type: str
    prompt_text: Optional[str] = None
    points: float = 0.0
    raw_fragment_ids: List[str] = []
    metadata: Dict[str, Any] = {}

class AnswerOption(BaseModel):
    option_id: str
    question_id: str
    text: str
    is_correct: bool = False

class Asset(BaseModel):
    asset_id: str
    course_id: str
    path: str
    mime_type: Optional[str] = None
    checksum: Optional[str] = None
    raw_fragment_id: Optional[str] = None

class MappingNote(BaseModel):
    note_id: str
    severity: Severity
    code: str
    message: str
    source_fragment_id: Optional[str] = None
    target_ref: Optional[str] = None
    fallback_used: bool = False

class Course(BaseModel):
    course_id: str
    title: str
    source_system: SourceSystem
    content_nodes: List[ContentNode] = []
    assessments: List[Assessment] = []
    assets: List[Asset] = []
    raw_fragments: List[RawFragment] = []
    mapping_notes: List[MappingNote] = []
    metadata: Dict[str, Any] = {}
