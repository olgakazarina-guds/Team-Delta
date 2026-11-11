from __future__ import annotations

from core.report import render_html_report
from domain.entities import Course, MappingNote
from domain.enums import Severity, SourceSystem


def test_html_report_escapes_course_and_note_text():
    course = Course(
        course_id="course-xss",
        title="<script>alert(1)</script>",
        source_system=SourceSystem.OPENEDX,
    )
    note = MappingNote(
        note_id="note-xss",
        severity=Severity.WARNING,
        code="TEST",
        message="<img src=x onerror=alert(1)>",
    )
    html = render_html_report(
        "job-xss",
        {
            "source_type": "openedx",
            "target_type": "moodle",
            "status": "inspected",
            "created_at": "now",
            "updated_at": "now",
        },
        course,
        [note],
    )

    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x" in html
