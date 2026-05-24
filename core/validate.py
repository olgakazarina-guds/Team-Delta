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
                severity=Severity.WARNING,
                code="EMPTY_COURSE",
                message="Course has no content nodes (chapters/sequentials/verticals).",
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
                message=f"Found unsupported node types: {list(set(unsupported))}",
                source_fragment_id=None,
                fallback_used=False
            ))
        return notes

    def _iterate_nodes(self, nodes):
        for node in nodes:
            yield node
            yield from self._iterate_nodes(node.children)
