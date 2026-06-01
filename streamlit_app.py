import json
import tempfile
import streamlit as st
from core.ingest import IngestService

# ------------------------------------------------------------
# Page setup
# ------------------------------------------------------------
st.set_page_config(page_title="LMS Converter", layout="wide")
st.title("LMS Converter")
st.markdown("Migrate courses between Open edX and Moodle")


# ------------------------------------------------------------
# Session state initialization
# ------------------------------------------------------------
if "inspection_result" not in st.session_state:
    st.session_state.inspection_result = None

if "inspection_path" not in st.session_state:
    st.session_state.inspection_path = None


# ------------------------------------------------------------
# Utility: convert Pydantic/models/nested objects into JSON-safe data
# ------------------------------------------------------------
def make_serializable(obj):
    if hasattr(obj, "model_dump"):
        return make_serializable(obj.model_dump())
    if hasattr(obj, "dict"):
        return make_serializable(obj.dict())
    if hasattr(obj, "value"):
        return obj.value
    if isinstance(obj, list):
        return [make_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: make_serializable(value) for key, value in obj.items()}
    return obj


# ------------------------------------------------------------
# UI render helpers
# ------------------------------------------------------------
def render_content_node(node, level=0):
    """Render one content node and its children recursively."""
    indent = "  " * level
    node_type = str(node.node_type.value if hasattr(node.node_type, 'value') else node.node_type).split(".")[-1]
    title = node.title or "Untitled"
    assessment_id = node.assessment_id

    if assessment_id:
        title += f" (Assessment: {assessment_id[:8]}...)"

    st.text(f"{indent}📁 {node_type}: {title}")

    for child in node.children:
        render_content_node(child, level + 1)


def render_structure(course):
    st.subheader("Course Content Hierarchy")
    content_nodes = course.content_nodes

    if not content_nodes:
        st.info("No content nodes found.")
        return

    for node in content_nodes:
        render_content_node(node)


def render_warnings(report):
    if not report:
        st.success("No validation issues found.")
        return

    for note in report:
        severity = str(getattr(note.severity, 'value', note.severity)).split(".")[-1].lower()
        code = getattr(note, "code", "UNKNOWN")
        message = getattr(note, "message", "")

        if severity == "warning":
            st.warning(f"{code}: {message}")
        elif severity == "error":
            st.error(f"{code}: {message}")
        else:
            st.info(f"{code}: {message}")


def render_assessments(course):
    assessments = course.assessments
    questions = course.questions

    if not assessments:
        st.info("No assessments found.")
        return

    st.write(f"Total assessments: {len(assessments)}")

    for ass in assessments[:10]:
        title = ass.title or "Untitled assessment"
        assessment_id = ass.assessment_id or "unknown"

        with st.expander(f"{title} (ID: {assessment_id})"):
            assessment_type = getattr(ass.assessment_type, 'value', ass.assessment_type) if ass.assessment_type else "N/A"
            st.write(f"Type: {assessment_type}")
            st.write(f"Max Score: {ass.max_score if ass.max_score else 'N/A'}")

            linked_questions = [
                q for q in questions
                if q.assessment_id == assessment_id
            ]
            st.write(f"Questions: {len(linked_questions)}")


def render_fragments(course):
    fragments = course.raw_fragments

    if not fragments:
        st.info("No raw fragments stored.")
        return

    st.write(f"Total raw fragments: {len(fragments)} (first 5 shown)")

    for frag in fragments[:5]:
        kind = getattr(frag.kind, 'value', frag.kind) if frag.kind else "unknown"
        source_loc = frag.source_location or {}
        file_path = getattr(source_loc, 'file_path', None) or "Unknown"

        with st.expander(f"{kind} - {file_path}"):
            raw_text = frag.raw_text or ""
            if raw_text:
                st.text(raw_text[:500] + ("..." if len(raw_text) > 500 else ""))
            else:
                st.text("No raw text content (may be stored as binary reference).")


def render_inspection(result):
    """Render the full inspection view from session state."""
    course = result["course"]
    report = result.get("report", [])
    raw_fragments_count = result.get("raw_fragments_count", 0)

    source_system = getattr(course.source_system, 'value', course.source_system) if course.source_system else "Unknown"
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Course Title", course.title or "Unknown")
    col2.metric("Source System", str(source_system).split(".")[-1])
    col3.metric("Raw Fragments", raw_fragments_count)
    col4.metric("Assessments", len(course.assessments))
    col5.metric("Questions", len(course.questions))

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Course Structure", "Validation Warnings", "Assessments", "Raw Fragments (Sample)"]
    )

    with tab1:
        render_structure(course)

    with tab2:
        render_warnings(report)

    with tab3:
        render_assessments(course)

    with tab4:
        render_fragments(course)

    # Prepare JSON report for download.
    serializable_result = make_serializable(result)
    json_str = json.dumps(serializable_result, indent=2, default=str)

    st.download_button(
        label="Download Full Report (JSON)",
        data=json_str,
        file_name="inspection_report.json",
        mime="application/json",
        on_click="ignore",
        key="download_inspection_report",
    )


# ------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------
with st.sidebar:
    st.header("Configuration")
    source_lms = st.selectbox("Source LMS", ["openedx", "moodle"])
    st.markdown("---")
    st.markdown("### About")
    st.markdown(
        "Upload a course export file (`.tar.gz` for Open edX, `.mbz` for Moodle) "
        "to inspect its structure and prepare for migration."
    )


# ------------------------------------------------------------
# File upload
# ------------------------------------------------------------
uploaded_file = st.file_uploader(
    f"Upload {source_lms.upper()} course export",
    type=["mbz", "tar.gz"]
)

if uploaded_file is None:
    st.info("Please upload a course export file to begin.")
    st.stop()


# ------------------------------------------------------------
# Save upload to a temporary file
# ------------------------------------------------------------
suffix = ".tar.gz" if uploaded_file.name.endswith(".tar.gz") else f".{uploaded_file.name.split('.')[-1]}"

with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
    tmp_file.write(uploaded_file.getvalue())
    tmp_path = tmp_file.name


# ------------------------------------------------------------
# Inspect action
# ------------------------------------------------------------
if st.button("🔍 Inspect Course", type="primary"):
    with st.spinner("Inspecting course... This may take a few seconds."):
        try:
            service = IngestService()
            result = service.inspect(
                tmp_path,
                source_type=source_lms,
                work_dir="data/extracted",
            )

            st.session_state.inspection_result = result
            st.session_state.inspection_path = tmp_path
            st.success("Inspection complete!")

        except Exception as e:
            st.error(f"Inspection failed: {e}")
            st.exception(e)


# ------------------------------------------------------------
# Render inspection view whenever a result exists
# ------------------------------------------------------------
if st.session_state.inspection_result:
    render_inspection(st.session_state.inspection_result)
