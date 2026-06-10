import json
import tempfile
import streamlit as st
from core.ingest import IngestService
from pathlib import Path
from core.migrate import MigrationService
from persistence.repositories import get_job, save_job, save_migration_job, init_db

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
if "migration_job_id" not in st.session_state:
    st.session_state.migration_job_id = None
if "report_html" not in st.session_state:
    st.session_state.report_html = None


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
    content_nodes = course.get("content_nodes", [])
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
    assessments = course.get("assessments", [])
    questions = course.get("questions", [])
    if not assessments:
        st.info("No assessments found.")
        return
    st.write(f"Total assessments: {len(assessments)}")
    for ass in assessments[:10]:
        title = ass.get("title", "Untitled assessment")
        assessment_id = ass.get("assessment_id", "unknown")
        with st.expander(f"{title} (ID: {assessment_id})"):
            st.write(f"Type: {ass.get('assessment_type', 'N/A')}")
            st.write(f"Max Score: {ass.get('max_score', 'N/A')}")
            linked_questions = [q for q in questions if q.get("assessment_id") == assessment_id]
            st.write(f"Questions: {len(linked_questions)}")

def render_fragments(course):
    fragments = course.get("raw_fragments", [])
    if not fragments:
        st.info("No raw fragments stored.")
        return
    st.write(f"Total raw fragments: {len(fragments)} (first 5 shown)")
    for frag in fragments[:5]:
        kind = frag.get("kind", "unknown")
        source_loc = frag.get("source_location", {})
        file_path = source_loc.get("file_path", "Unknown")
        with st.expander(f"{kind} - {file_path}"):
            raw_text = frag.get("raw_text", "")
            if raw_text:
                st.text(raw_text[:500] + ("..." if len(raw_text) > 500 else ""))
            else:
                st.text("No raw text content (may be stored as binary reference).")

def render_inspection(result):
    course = result["course"]
    report = result.get("report", [])
    raw_fragments_count = result.get("raw_fragments_count", 0)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Course Title", course.get("title", "Unknown"))
    col2.metric("Source System", str(course.get("source_system", "")).split(".")[-1])
    col3.metric("Raw Fragments", raw_fragments_count)
    col4.metric("Assessments", len(course.get("assessments", [])))
    col5.metric("Questions", len(course.get("questions", [])))
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
    # Download inspection JSON
    serializable_result = make_serializable(result)
    json_str = json.dumps(serializable_result, indent=2, default=str)
    st.download_button(
        label="Download Inspection Report (JSON)",
        data=json_str,
        file_name="inspection_report.json",
        mime="application/json",
        key="download_inspection"
    )

# ------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------
with st.sidebar:
    st.header("Configuration")
    source_lms = st.selectbox("Source LMS", ["openedx", "moodle"])
    st.markdown("---")
    st.markdown("### Report")
    job_id_input = st.text_input("Job ID", placeholder="Enter job ID to view report")
    if st.button("Generate Report"):
        if job_id_input:
            init_db()
            job = get_job(job_id_input)
            if job:
                # Display report (simple HTML preview)
                st.session_state.report_html = job.get("report_html")
                # We'll show a preview and download options
            else:
                st.error("Job ID not found")
        else:
            st.warning("Please enter a Job ID")

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
# Save upload to temporary file
# ------------------------------------------------------------
suffix = ".tar.gz" if uploaded_file.name.endswith(".tar.gz") else f".{uploaded_file.name.split('.')[-1]}"
with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
    tmp_file.write(uploaded_file.getvalue())
    tmp_path = tmp_file.name

# ------------------------------------------------------------
# Migration dialog
# ------------------------------------------------------------
def run_migration():
    # Get migration parameters from session state
    target_lms = st.session_state.get("target_lms", "openedx")
    output_path = st.session_state.get("output_path", "export.tar.gz")
    detailed = st.session_state.get("detailed", False)

    # We already have the inspection result (course object) from session state
    inspection = st.session_state.inspection_result
    if not inspection:
        st.error("No inspection result available. Please inspect first.")
        return

    course = inspection["course"]
    extracted_path = inspection.get("extracted_path")

    migrator = MigrationService()
    try:
        if target_lms == "openedx":
            with st.spinner("Converting to Open edX format..."):
                output_file = migrator.migrate_to_openedx(
                    course, output_path, source_extracted_path=extracted_path
                )
        elif target_lms == "moodle":
            with st.spinner("Converting to Moodle format..."):
                output_file = migrator.migrate_to_moodle(
                    course, output_path, source_extracted_path=extracted_path
                )
        else:
            st.error(f"Unsupported target: {target_lms}")
            return
        st.success("Migration completed!")
        st.write(f"Output file: {output_file}")
        # Store job ID (migration jobs are also stored in database)
        # For simplicity, we'll use the course.course_id as job ID (from inspection)
        st.session_state.migration_job_id = course.get("course_id")
        st.info(f"Job ID: {st.session_state.migration_job_id}")
    except Exception as e:
        st.error(f"Migration failed: {e}")

@st.dialog("Migrate Course")
def migrate_dialog():
    st.markdown("### Migration Settings")
    target_lms = st.selectbox("Target LMS", ["openedx", "moodle"])
    output_path = st.text_input("Output file path", value="export.tar.gz")
    detailed = st.checkbox("Show detailed progress", value=False)
    if st.button("Start Migration"):
        # Store parameters in session state and close dialog
        st.session_state.target_lms = target_lms
        st.session_state.output_path = output_path
        st.session_state.detailed = detailed
        st.rerun()

# ------------------------------------------------------------
# Inspect and migrate buttons
# ------------------------------------------------------------
col_inspect, col_migrate = st.columns(2)
with col_inspect:
    if st.button("🔍 Inspect Course", type="primary"):
        with st.spinner("Inspecting course..."):
            try:
                service = IngestService()
                result = service.inspect(tmp_path, source_type=source_lms, work_dir="data/extracted")
                st.session_state.inspection_result = result
                st.session_state.inspection_path = tmp_path
                st.success("Inspection complete!")
            except Exception as e:
                st.error(f"Inspection failed: {e}")
                st.exception(e)

with col_migrate:
    if st.session_state.inspection_result is not None:
        if st.button("Migrate", type="secondary"):
            migrate_dialog()
    else:
        st.button("Migrate", disabled=True, help="Inspect a course first")

# ------------------------------------------------------------
# Run migration after dialog closes
# ------------------------------------------------------------
if st.session_state.get("target_lms") is not None:
    run_migration()
    # Clear the migration parameters after run to avoid re-running on rerender
    del st.session_state.target_lms
    del st.session_state.output_path
    del st.session_state.detailed

# ------------------------------------------------------------
# Render inspection result if available
# ------------------------------------------------------------
if st.session_state.inspection_result:
    render_inspection(st.session_state.inspection_result)

# ------------------------------------------------------------
# Render report preview if job ID entered in sidebar
# ------------------------------------------------------------
if "job_id_input" in locals() and job_id_input:
    init_db()
    job = get_job(job_id_input)
    if job:
        st.subheader(f"Report for Job {job_id_input}")
        st.write(f"Source: {job['source_type']} → Target: {job['target_type']}")
        st.write(f"Created: {job['created_at']}")
        # Try to display HTML report
        if job.get("report_html"):
            st.components.v1.html(job["report_html"], height=600, scrolling=True)
        else:
            # Fallback: show JSON
            course = json.loads(job["course_json"])
            st.json(course)
    else:
        st.error("Job not found")
 