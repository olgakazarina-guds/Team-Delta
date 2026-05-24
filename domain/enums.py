from enum import Enum

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

class SourceSystem(str, Enum):
    OPENEDX = "openedx"
    MOODLE = "moodle"

class NodeType(str, Enum):
    COURSE = "course"
    CHAPTER = "chapter"
    SEQUENTIAL = "sequential"
    VERTICAL = "vertical"
    HTML = "html"
    VIDEO = "video"
    PROBLEM = "problem"
    OPENASSESSMENT = "openassessment"
    LTI = "lti"
    SECTION = "section"
    ACTIVITY = "activity"
    PAGE = "page"
    FORUM = "forum"
    QUIZ = "quiz"
    SCORM = "scorm"
    UNKNOWN = "unknown"

class AssessmentType(str, Enum):
    QUIZ = "quiz"
    OPENASSESSMENT = "openassessment"
    ASSIGNMENT = "assignment"

class FragmentKind(str, Enum):
    XML = "xml"
    HTML = "html"
    JSON = "json"
    TEXT = "text"
    BINARY = "binary"
