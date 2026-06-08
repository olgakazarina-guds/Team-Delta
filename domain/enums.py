"""
Domain Enums – Type-safe enumerations for the course migration system.

Defines all enum types used across domain entities:
- Severity: For mapping notes and validation
- SourceSystem: For tracking origin LMS
- NodeType: For content hierarchy
- AssessmentType: For assessment categories
- FragmentKind: For raw fragment content types
"""

from enum import Enum


class Severity(str, Enum):
    """
    Severity levels for mapping notes and validation messages.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SourceSystem(str, Enum):
    """
    Source LMS platforms that can be migrated from.
    """

    OPENEDX = "openedx"
    MOODLE = "moodle"


class NodeType(str, Enum):
    """
    Content node types in the course hierarchy.

    Hierarchical structure:
    - COURSE → CHAPTER → SEQUENTIAL → VERTICAL → COMPONENT (HTML, VIDEO, PROBLEM, etc.)
    """

    COURSE = "course"
    CHAPTER = "chapter"
    SEQUENTIAL = "sequential"
    VERTICAL = "vertical"
    HTML = "html"
    VIDEO = "video"
    PROBLEM = "problem"
    OPENASSESSMENT = "openassessment"
    LTI = "lti"
    SECTION = "section"  # Moodle-specific
    ACTIVITY = "activity"  # Moodle-specific
    PAGE = "page"  # Moodle-specific
    FORUM = "forum"
    QUIZ = "quiz"  # Moodle-specific
    SCORM = "scorm"
    UNKNOWN = "unknown"


class AssessmentType(str, Enum):
    """
    Assessment categories in the canonical model.
    """

    QUIZ = "quiz"
    OPENASSESSMENT = "openassessment"
    ASSIGNMENT = "assignment"


class FragmentKind(str, Enum):
    """
    Content types for raw fragments (source XML fragments).
    """

    XML = "xml"
    HTML = "html"
    JSON = "json"
    TEXT = "text"
    BINARY = "binary"
