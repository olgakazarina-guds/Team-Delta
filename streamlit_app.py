import json
import tempfile
import streamlit as st
import os
from pathlib import Path
from core.ingest import IngestService
from core.migrate import MigrationService
from domain.entities import Course
from domain.enums import NodeType
from persistence.repositories import get_job, save_job, save_migration_job, init_db

# Page setup
st.set_page_config(page_title="LMS Converter", layout="wide")
st.title("LMS Converter")
st.markdown("Migrate courses between Open edX and Moodle")

# Session state initialization
if "inspection_result" not in st.session_state:
    st.session_state.inspection_result = None
if "inspection_path" not in st.session_state:
    st.session_state.inspection_path = None
if "migration_job_id" not in st.session_state:
    st.session_state.migration_job_id = None
if "report_job" not in st.session_state:
    st.session_state.report_job = None
if "report_format" not in st.session_state:
    st.session_state.report_format = None
if "output_directory" not in st.session_state:
    st.session_state.output_directory = str(Path.home())
if "show_report_dialog" not in st.session_state:
    st.session_state.show_report_dialog = False

# Helper: generate HTML report (same as CLI)
def count_node_type(nodes, target_type):
    count = 0
    for node in nodes:
        if node.node_type.value == target_type:
            count += 1
        count += count_node_type(node.children, target_type)
    return count

def generate_html_report(job_id, job, course, report_items):
    chapters = count_node_type(course.content_nodes, "chapter")
    sequentials = count_node_type(course.content_nodes, "sequential")
    verticals = count_node_type(course.content_nodes, "vertical")
    html_components = count_node_type(course.content_nodes, "html")
    problem_components = count_node_type(course.content_nodes, "problem")
    video_components = count_node_type(course.content_nodes, "video")

    unsupported_types = set()
    for note in report_items:
        if note.get("code") == "UNSUPPORTED_NODES":
            unsupported_types.add(note.get("message", ""))
        elif note.get("code") == "UNSUPPORTED_QUESTION_TYPE":
            unsupported_types.add("question_type")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>LMS Converter Report - {job_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 2rem; }}
        h1, h2 {{ color: #2c3e50; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .warning {{ background-color: #fff3cd; }}
        .error {{ background-color: #f8d7da; }}
        .info {{ background-color: #d1ecf1; }}
        .summary {{ background-color: #e9ecef; }}
    </style>
</head>
<body>
    <h1>LMS Converter Report</h1>
    <p><strong>Job ID:</strong> {job_id}</p>
    <p><strong>Created:</strong> {job['created_at']}</p>
    <p><strong>Source LMS:</strong> {job['source_type']}</p>
    <p><strong>Target LMS:</strong> {job['target_type'] or 'N/A'}</p>
    <h2>Course Summary</h2>
    <table class="summary">
        <tr><th>Property</th><th>Value</th></tr>
        <tr><td>Title</td><td>{course.title}</td></tr>
        <tr><td>Content Nodes</td><td>{len(course.content_nodes)}</td></tr>
        <tr><td>Chapters</td><td>{chapters}</td></tr>
        <tr><td>Sequentials</td><td>{sequentials}</td></tr>
        <tr><td>Verticals</td><td>{verticals}</td></tr>
        <tr><td>HTML Components</td><td>{html_components}</td></tr>
        <tr><td>Problem Components</td><td>{problem_components}</td></tr>
        <tr><td>Video Components</td><td>{video_components}</td></tr>
        <tr><td>Assessments</td><td>{len(course.assessments)}</td></tr>
        <tr><td>Questions</td><td>{len(course.questions)}</td></tr>
        <tr><td>Answer Options</td><td>{len(course.answer_options)}</td></tr>
        <tr><td>Assets</td><td>{len(course.assets)}</td></tr>
    </table>
"""
    if course.assets:
        html += """    <h2>Assets</h2>
    <table>
        <tr><th>Asset ID</th><th>Path</th></tr>
"""
        for a in course.assets[:20]:
            html += f"""        <tr><td>{a.asset_id}</td><td>{a.path}</td></tr>
"""
        if len(course.assets) > 20:
            html += f"""        <tr><td colspan="2">... and {len(course.assets)-20} more</td></tr>
"""
        html += "    </table>\n"

    if unsupported_types:
        html += """    <h2>Unsupported Features</h2>
    <ul>
"""
        for u in unsupported_types:
            html += f"        <li>{u}</li>\n"
        html += "    </ul>\n"

    html += """    <h2>Validation Warnings & Errors</h2>
    <table>
        <tr><th>Severity</th><th>Code</th><th>Message</th></tr>
"""
    for note in report_items:
        severity = note.get("severity", "info")
        css_class = {"warning": "warning", "error": "error", "info": "info"}.get(severity, "")
        html += f"""        <tr class="{css_class}">
            <td>{severity}</td>
            <td>{note.get('code', '')}</td>
            <td>{note.get('message', '')}</td>
        </tr>
"""
    html += """    </table>
</body>
</html>"""
    return html

# Utility: convert objects to JSON-serializable
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

# UI render helpers (work with both Pydantic models and dicts)
def render_content_node(node, level=0):
    indent = "  " * level
    if hasattr(node, "node_type"):
        node_type = node.node_type.value
        title = node.title or "Untitled"
        assessment_id = node.assessment_id
        children = node.children
    else:
        node_type = str(node.get("node_type", "unknown")).split(".")[-1]
        title = node.get("title") or "Untitled"
        assessment_id = node.get("assessment_id")
        children = node.get("children", [])
    if assessment_id:
        title += f" (Assessment: {assessment_id[:8]}...)"
    st.text(f"{indent}📁 {node_type}: {title}")
    for child in children:
        render_content_node(child, level + 1)

def render_structure(course):
    st.subheader("Course Content Hierarchy")
    content_nodes = course.content_nodes if hasattr(course, "content_nodes") else course.get("content_nodes", [])
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
        if hasattr(note, "severity"):
            severity = note.severity.value if hasattr(note.severity, "value") else str(note.severity)
            code = note.code
            message = note.message
        else:
            severity = str(note.get("severity", "")).split(".")[-1].lower()
            code = note.get("code", "UNKNOWN")
            message = note.get("message", "")
        if severity == "warning":
            st.warning(f"{code}: {message}")
        elif severity == "error":
            st.error(f"{code}: {message}")
        else:
            st.info(f"{code}: {message}")

def render_assessments(course):
    assessments = course.assessments if hasattr(course, "assessments") else course.get("assessments", [])
    questions = course.questions if hasattr(course, "questions") else course.get("questions", [])
    if not assessments:
        st.info("No assessments found.")
        return
    st.write(f"Total assessments: {len(assessments)}")
    for ass in assessments[:10]:
        if hasattr(ass, "title"):
            title = ass.title
            assessment_id = ass.assessment_id
            assessment_type = ass.assessment_type.value if hasattr(ass.assessment_type, "value") else str(ass.assessment_type)
            max_score = ass.max_score
        else:
            title = ass.get("title", "Untitled assessment")
            assessment_id = ass.get("assessment_id", "unknown")
            assessment_type = ass.get("assessment_type", "N/A")
            max_score = ass.get("max_score", "N/A")
        with st.expander(f"{title} (ID: {assessment_id})"):
            st.write(f"Type: {assessment_type}")
            st.write(f"Max Score: {max_score}")
            linked_questions = [q for q in questions if (hasattr(q, "assessment_id") and q.assessment_id == assessment_id) or q.get("assessment_id") == assessment_id]
            st.write(f"Questions: {len(linked_questions)}")

def render_fragments(course):
    fragments = course.raw_fragments if hasattr(course, "raw_fragments") else course.get("raw_fragments", [])
    if not fragments:
        st.info("No raw fragments stored.")
        return
    st.write(f"Total raw fragments: {len(fragments)} (first 5 shown)")
    for frag in fragments[:5]:
        if hasattr(frag, "kind"):
            kind = frag.kind
            source_loc = frag.source_location
            file_path = source_loc.file_path if source_loc else "Unknown"
            raw_text = frag.raw_text
        else:
            kind = frag.get("kind", "unknown")
            source_loc = frag.get("source_location", {})
            file_path = source_loc.get("file_path", "Unknown")
            raw_text = frag.get("raw_text", "")
        with st.expander(f"{kind} - {file_path}"):
            if raw_text:
                st.text(raw_text[:500] + ("..." if len(raw_text) > 500 else ""))
            else:
                st.text("No raw text content (may be stored as binary reference).")

def render_inspection(result):
    course = result["course"]
    report = result.get("report", [])
    raw_fragments_count = result.get("raw_fragments_count", 0)
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Course Title", course.title if hasattr(course, "title") else course.get("title", "Unknown"))
    source_sys = course.source_system if hasattr(course, "source_system") else course.get("source_system", "")
    col2.metric("Source System", source_sys.value if hasattr(source_sys, "value") else str(source_sys).split(".")[-1])
    col3.metric("Raw Fragments", raw_fragments_count)
    col4.metric("Assessments", len(course.assessments if hasattr(course, "assessments") else course.get("assessments", [])))
    col5.metric("Questions", len(course.questions if hasattr(course, "questions") else course.get("questions", [])))
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

# Sidebar
with st.sidebar:
    st.header("Configuration")
    fallback_lms = st.selectbox("Fallback Source LMS (if file extension unknown)", ["openedx", "moodle"], key="fallback_lms")
    st.markdown("---")
    st.markdown("### Report")
    job_id_input = st.text_input("Job ID", placeholder="Enter job ID to view report", key="job_id_input")
    report_format = st.selectbox("Report format", ["json", "html"], key="report_format_selector")
    if st.button("Generate Report", key="generate_report_btn"):
        if job_id_input:
            init_db()
            job = get_job(job_id_input)
            if job:
                st.session_state.report_job = job
                st.session_state.report_format = report_format
                st.session_state.show_report_dialog = True
            else:
                st.error("Job ID not found")
        else:
            st.warning("Please enter a Job ID")
    if st.button("Clear Report", key="clear_report_btn"):
        for key in ["report_job", "report_format", "show_report_dialog", "report_html"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

# Report Dialog
@st.dialog("Report for Job")
def report_dialog():
    job = st.session_state.report_job
    fmt = st.session_state.report_format
    job_id = st.session_state.get("job_id_input", "")
    st.write(f"**Source:** {job['source_type']} → **Target:** {job['target_type']}")
    st.write(f"**Created:** {job['created_at']}")
    if fmt == "html":
        try:
            course = Course.model_validate_json(job["course_json"])
            report_items = json.loads(job["report_json"])
            html_content = generate_html_report(job_id, job, course, report_items)
            st.components.v1.html(html_content, height=600, scrolling=True)
            st.download_button(
                label="Download HTML Report",
                data=html_content,
                file_name=f"report_{job_id}.html",
                mime="text/html",
                key="download_html_report_dialog"
            )
        except Exception as e:
            st.error(f"Error generating HTML report: {e}")
            st.exception(e)
    else:  # json
        try:
            course_data = json.loads(job["course_json"])
            st.json(course_data)
            json_str = json.dumps(course_data, indent=2)
            st.download_button(
                label="Download JSON Report",
                data=json_str,
                file_name=f"report_{job_id}.json",
                mime="application/json",
                key="download_json_report_dialog"
            )
        except Exception as e:
            st.error(f"Report data not available: {e}")
    if st.button("Close Report", key="close_report_dialog"):
        st.session_state.show_report_dialog = False
        st.rerun()

if st.session_state.get("show_report_dialog") and st.session_state.get("report_job"):
    report_dialog()

# File upload and source detection
uploaded_file = st.file_uploader(
    "Upload course export (.mbz or .tar.gz)",
    type=["mbz", "tar.gz"],
    key="course_uploader"
)

if uploaded_file is None:
    st.info("Please upload a course export file to begin.")
    st.stop()

# Auto-detect source from file extension
if uploaded_file.name.endswith(".mbz"):
    source_lms = "moodle"
elif uploaded_file.name.endswith(".tar.gz"):
    source_lms = "openedx"
else:
    source_lms = fallback_lms

st.caption(f"Detected source LMS: **{source_lms.upper()}**")

# Save upload to temporary file
suffix = ".tar.gz" if uploaded_file.name.endswith(".tar.gz") else f".{uploaded_file.name.split('.')[-1]}"
with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
    tmp_file.write(uploaded_file.getvalue())
    tmp_path = tmp_file.name

# Migration dialog
def run_migration():
    target_lms = st.session_state.get("target_lms", "openedx")
    output_filename = st.session_state.get("output_filename", "export.tar.gz")
    output_directory = st.session_state.get("output_directory", str(Path.home()))
    detailed = st.session_state.get("detailed", False)
    output_path = os.path.join(output_directory, output_filename)
    inspection = st.session_state.inspection_result
    if not inspection:
        st.error("No inspection result available. Please inspect first.")
        return

    course = inspection["course"]
    extracted_path = inspection.get("extracted_path")

    migrator = MigrationService()
    try:
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        if target_lms == "openedx":
            with st.spinner("Converting to Open edX format..."):
                output_file = migrator.migrate_to_openedx(course, output_path, source_extracted_path=extracted_path)
        elif target_lms == "moodle":
            with st.spinner("Converting to Moodle format..."):
                output_file = migrator.migrate_to_moodle(course, output_path, source_extracted_path=extracted_path)

        else:
            st.error(f"Unsupported target: {target_lms}")
            return
        st.success("Migration completed!")
        st.write(f"Output file saved to: **{output_file}**")
        st.session_state.migration_job_id = course.course_id if hasattr(course, "course_id") else course.get("course_id")
        st.info(f"Job ID: {st.session_state.migration_job_id}")
        # Save migration report
        reports_dir = Path("data/reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        migration_json_path = reports_dir / f"migration_{st.session_state.migration_job_id}.json"
        serializable_course = make_serializable(course)
        with open(migration_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "course": serializable_course,
                "target_lms": target_lms,
                "output_file": output_file,
                "source_extracted_path": extracted_path
            }, f, indent=2)
        st.info(f"Migration report saved to: {migration_json_path}")
    except Exception as e:
        st.error(f"Migration failed: {e}")

    save_migration_job(
        st.session_state.migration_job_id,
        course.source_system.value if hasattr(course.source_system, 'value') else str(course.source_system),
        target_lms,
        course,
        [],
        extracted_path
    )

@st.dialog("Migrate Course")
def migrate_dialog():
    st.markdown("### Migration Settings")
    target_lms = st.selectbox("Target LMS", ["openedx", "moodle"], key="dialog_target_lms")
    default_filename = "export.tar.gz" if target_lms == "openedx" else "export.mbz"
    output_filename = st.text_input("Output filename", value=default_filename, key="dialog_output_filename",
                                    help="Name of the output file (e.g., export.tar.gz)")
    st.markdown("### Output Directory")
    current_dir = st.session_state.get("output_directory", str(Path.home()))
    output_directory = st.text_input("Directory path", value=current_dir, key="dialog_output_directory",
                                     help="Full directory path where the file will be saved")
    if output_directory:
        if Path(output_directory).is_dir():
            st.success(f"✓ Directory exists: {output_directory}")
        else:
            st.warning(f"⚠ Directory does not exist. It will be created automatically.")
    detailed = st.checkbox("Show detailed progress", value=False, key="dialog_detailed")
    if st.button("Start Migration", key="start_migration_btn"):
        st.session_state.target_lms = target_lms
        st.session_state.output_filename = output_filename
        st.session_state.output_directory = output_directory
        st.session_state.detailed = detailed
        st.rerun()

# Inspect and migrate buttons
col_inspect, col_migrate = st.columns(2)
with col_inspect:
    if st.button("Inspect Course", type="primary", key="inspect_btn"):
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
        st.button("Migrate", disabled=True, help="Inspect a course first", key="migrate_btn_disabled")

# Run migration after dialog closes
if st.session_state.get("target_lms") is not None:
    run_migration()
    del st.session_state.target_lms
    del st.session_state.output_filename
    del st.session_state.output_directory
    del st.session_state.detailed

# Render inspection result if available
if st.session_state.inspection_result:
    render_inspection(st.session_state.inspection_result)
