"""
Transform Service – Converts parsed LMS data into normalized domain entities.

Transforms parsed Open edX or Moodle data into canonical domain entities:
- Course
- ContentNode (hierarchical: chapter -> sequential -> vertical -> component)
- Assessment
- Question
- AnswerOption
- Asset
- RawFragment
"""

import uuid
import logging
from typing import Dict, Any, List, Optional

from domain.entities import (
    Course,
    ContentNode,
    Assessment,
    Question,
    AnswerOption,
    Asset,
    RawFragment,
    MappingNote,
)
from domain.enums import SourceSystem, NodeType, AssessmentType, Severity
from adapters.openedx.problem_parser import parse_problem

logger = logging.getLogger(__name__)

class TransformService:
    """
    Service responsible for transforming parsed LMS data into normalized domain entities.

    Supports:
    - Open edX -> canonical Course
    - Moodle -> canonical Course

    Builds hierarchical content structures and extracts assessments/problems
    with their questions and answer options.
    """

    def transform(self, parsed: Dict[str, Any], source_type: str, job_id: str) -> Course:
        """
        Entry point for transformation logic.

        Routes to source-specific transformation methods based on the input type.

        Args:
            parsed: Parsed data dictionary from the source LMS
            source_type: Identifier for the source system ("openedx" or "moodle")
            job_id: Unique identifier for the transformation job/course

        Returns:
            Transformed Course domain object

        Raises:
            ValueError: If source_type is not supported
        """
        logger.info("Transforming %s parse output to canonical IR (job %s)", source_type, job_id)
        if source_type == "openedx":
            course = self._transform_openedx(parsed, job_id)
        elif source_type == "moodle":
            course = self._transform_moodle(parsed, job_id)
        else:
            logger.error("Unsupported source type: %s", source_type)
            raise ValueError(f"Unsupported source type: {source_type}")
        logger.debug("Built course '%s' with %d top-level nodes, %d assets",course.title, len(course.content_nodes), len(course.assets),)
        return course

    def _transform_openedx(self, parsed: Dict[str, Any], job_id: str) -> Course:
        """
        Transform parsed Open edX course data into domain entities.

        Builds a hierarchical content structure (Chapter -> Sequential -> Vertical -> Component)
        and extracts assessments/problems with their questions and answer options.

        Args:
            parsed: Parsed Open edX course data
            job_id: Unique course identifier

        Returns:
            Fully transformed Course object with all nested entities
        """
        # Step 1: Extract raw fragments for provenance and debugging
        raw_fragments = self._build_raw_fragments(parsed)

        # Step 2: Initialize containers for assessment-related entities
        assessments: List[Assessment] = []
        questions: List[Question] = []
        answer_options: List[AnswerOption] = []

        # Step 3: Build hierarchical content nodes
        content_nodes: List[ContentNode] = []
        node_id_map: Dict[str, str] = {}  # Maps url_name -> node_id

        for chapter_idx, chapter in enumerate(parsed.get("chapters", [])):
            # Create chapter node (top-level hierarchy)
            chapter_node = self._create_chapter_node(chapter, chapter_idx)
            node_id_map[chapter["url_name"]] = chapter_node.node_id
            content_nodes.append(chapter_node)

            # Process sequentials (children of chapter)
            for seq_idx, seq in enumerate(chapter.get("sequentials", [])):
                seq_node = self._create_sequential_node(seq, seq_idx, chapter_node.node_id)
                node_id_map[seq["url_name"]] = seq_node.node_id
                chapter_node.children.append(seq_node)

                # Process verticals (children of sequential)
                for vert_idx, vert in enumerate(seq.get("verticals", [])):
                    vert_node = self._create_vertical_node(vert, vert_idx, seq_node.node_id)
                    node_id_map[vert["url_name"]] = vert_node.node_id
                    seq_node.children.append(vert_node)

                    # Process components (children of vertical)
                    self._process_components(
                        vert_node,
                        vert.get("components", []),
                        assessments,
                        questions,
                        answer_options,
                        raw_fragments,
                    )

        # Step 4: Assemble and return the Course domain object
        return Course(
            course_id=job_id,
            title=parsed.get("course_title", "Unnamed Course"),
            source_system=SourceSystem.OPENEDX,
            content_nodes=content_nodes,
            assessments=assessments,
            questions=questions,
            answer_options=answer_options,
            raw_fragments=raw_fragments,
            metadata={
                "org": parsed.get("org"),
                "course_code": parsed.get("course_code"),
                "extracted_path": parsed.get("extracted_path"),
            },
        )

    def _build_raw_fragments(self, parsed: Dict[str, Any]) -> List[RawFragment]:
        """Build list of RawFragment entities from parsed data."""
        raw_fragments = []
        for frag in parsed.get("raw_fragments", []):
            raw_fragments.append(
                RawFragment(
                    fragment_id=frag["fragment_id"],
                    kind=frag["kind"],
                    source_location=frag["source_location"],
                    raw_text=frag.get("raw_text"),
                    raw_bytes_ref=frag.get("raw_bytes_ref"),
                    checksum=frag.get("checksum"),
                )
            )
        return raw_fragments

    def _create_chapter_node(self, chapter: Dict[str, Any], index: int) -> ContentNode:
        """Create a chapter ContentNode."""
        return ContentNode(
            node_id=str(uuid.uuid4()),
            node_type=NodeType.CHAPTER,
            title=chapter.get("title"),
            position=index,
            raw_fragment_ids=[chapter["raw_fragment_id"]]
            if chapter.get("raw_fragment_id")
            else [],
        )

    def _create_sequential_node(
        self, seq: Dict[str, Any], index: int, parent_id: str
    ) -> ContentNode:
        """Create a sequential ContentNode."""
        return ContentNode(
            node_id=str(uuid.uuid4()),
            node_type=NodeType.SEQUENTIAL,
            title=seq.get("title"),
            parent_id=parent_id,
            position=index,
            raw_fragment_ids=[seq["raw_fragment_id"]]
            if seq.get("raw_fragment_id")
            else [],
        )

    def _create_vertical_node(
        self, vert: Dict[str, Any], index: int, parent_id: str
    ) -> ContentNode:
        """Create a vertical ContentNode."""
        return ContentNode(
            node_id=str(uuid.uuid4()),
            node_type=NodeType.VERTICAL,
            title=vert.get("title"),
            parent_id=parent_id,
            position=index,
            raw_fragment_ids=[vert["raw_fragment_id"]]
            if vert.get("raw_fragment_id")
            else [],
        )

    def _process_components(
        self,
        vert_node: ContentNode,
        components: List[Dict[str, Any]],
        assessments: List[Assessment],
        questions: List[Question],
        answer_options: List[AnswerOption],
        raw_fragments: List[RawFragment],
    ) -> None:
        """
        Process all components within a vertical.

        Creates component ContentNodes and extracts assessments from problem components.
        """
        comp_type_map = {
            "html": NodeType.HTML,
            "video": NodeType.VIDEO,
            "problem": NodeType.PROBLEM,
            "openassessment": NodeType.OPENASSESSMENT,
            "lti": NodeType.LTI,
        }

        for comp_idx, comp in enumerate(components):
            node_type = comp_type_map.get(comp["type"], NodeType.UNKNOWN)

            # Prepare metadata
            metadata = self._build_component_metadata(comp, node_type)

            # Handle problem components: parse and extract assessments
            assessment_id = None
            if node_type == NodeType.PROBLEM and comp.get("raw_fragment_id"):
                assessment_id, new_questions, new_answer_options = (
                    self._extract_problem_assessment(comp, raw_fragments)
                )
                questions.extend(new_questions)
                answer_options.extend(new_answer_options)

            # Create component node
            comp_node = ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=node_type,
                title=comp.get("title", ""),
                parent_id=vert_node.node_id,
                position=comp_idx,
                raw_fragment_ids=[comp["raw_fragment_id"]]
                if comp.get("raw_fragment_id")
                else [],
                metadata=metadata,
            )

            if assessment_id:
                comp_node.assessment_id = assessment_id

            vert_node.children.append(comp_node)

    def _build_component_metadata(
        self, comp: Dict[str, Any], node_type: NodeType
    ) -> Dict[str, Any]:
        """Build metadata dictionary for a component node."""
        metadata = {}

        if comp.get("inline_xml"):
            metadata["inline_xml"] = comp["inline_xml"]

        if node_type == NodeType.HTML and comp.get("content_html"):
            metadata["content_html"] = comp["content_html"]

        return metadata

    def _extract_problem_assessment(
        self, comp: Dict[str, Any], raw_fragments: List[RawFragment]
    ) -> tuple:
        """
        Extract assessment, questions, and answer options from a problem component.

        Returns:
            Tuple of (assessment_id, questions_list, answer_options_list)
        """
        raw_frag = next(
            (f for f in raw_fragments if f.fragment_id == comp["raw_fragment_id"]),
            None,
        )

        if not raw_frag or not raw_frag.raw_text:
            return None, [], []

        # Parse the problem XML into structured data
        problem_data = parse_problem(raw_frag.raw_text, comp.get("url_name", ""))

        # Create assessment entity
        assessment_id = str(uuid.uuid4())
        assessment = Assessment(
            assessment_id=assessment_id,
            course_id="",  # Will be set by parent
            title=problem_data["assessment_title"],
            assessment_type=AssessmentType.QUIZ,
            max_score=sum(q.get("points", 0) for q in problem_data["questions"]),
            raw_fragment_ids=[comp["raw_fragment_id"]],
            metadata={
                "problem_url_name": comp.get("url_name"),
                "original_type": "problem",
            },
        )

        # Note: assessment is added by caller, we only return the ID and children
        questions = []
        answer_options = []

        for q_data in problem_data["questions"]:
            question = Question(
                question_id=q_data["question_id"],
                assessment_id=assessment_id,
                question_type=q_data["type"],
                prompt_text=q_data["prompt"],
                points=q_data.get("points", 1.0),
                raw_fragment_ids=[comp["raw_fragment_id"]],
                metadata={},
            )
            questions.append(question)

            for opt in q_data.get("answer_options", []):
                answer_option = AnswerOption(
                    option_id=str(uuid.uuid4()),
                    question_id=question.question_id,
                    text=opt["text"],
                    is_correct=opt["is_correct"],
                )
                answer_options.append(answer_option)

        return assessment_id, questions, answer_options

    def _transform_moodle(self, parsed: Dict[str, Any], job_id: str) -> Course:
        """
        Transform parsed Moodle course data into domain entities.

        Builds a hierarchical content structure (Section -> Content -> Activity -> Component)
        and extracts assessments/questions from quiz activities.

        Args:
            parsed: Parsed Moodle course data
            job_id: Unique course identifier

        Returns:
            Fully transformed Course object with all nested entities
        """
        # Step 1: Extract raw fragments
        raw_fragments = self._build_raw_fragments(parsed)

        # Step 2: Initialize containers
        content_nodes: List[ContentNode] = []
        assessments: List[Assessment] = []
        assets: List[Asset] = []
        questions: List[Question] = []
        answer_options: List[AnswerOption] = []

        # Step 3: Build question bank map (original_moodle_id -> question data)
        question_bank = self._build_question_bank(parsed)

        # Step 4: Create assessments per quiz activity
        quiz_activities = self._find_quiz_activities(parsed)
        self._create_quiz_assessments(
            quiz_activities, question_bank, assessments, questions, answer_options
        )

        # Step 5: Build hierarchical content nodes
        self._build_moodle_content_tree(
            parsed, quiz_activities, content_nodes, assessments
        )

        # Step 6: Build asset entities
        for a in parsed.get("assets", []):
            assets.append(
                Asset(
                    asset_id=a["asset_id"],
                    course_id=parsed.get("course_id") or job_id,
                    path=a.get("path", ""),
                    mime_type=a.get("mime_type"),
                    checksum=a.get("checksum"),
                )
            )

        # Step 7: Assemble and return the Course domain object
        return Course(
            course_id=parsed.get("course_id") or job_id,
            title=parsed.get("course_title", "Unnamed Course"),
            source_system=SourceSystem.MOODLE,
            content_nodes=content_nodes,
            assessments=assessments,
            questions=questions,
            answer_options=answer_options,
            assets=assets,
            raw_fragments=raw_fragments,
            metadata={
                "shortname": parsed.get("course_shortname"),
                "lang": parsed.get("lang"),
            },
        )

    def _build_question_bank(self, parsed: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Build a map from original Moodle question ID to its data.

        Returns:
            Dict mapping original_moodle_id -> question data
        """
        question_bank = {}
        for qa in parsed.get("questions_assessments", []):
            for q in qa["questions"]:
                orig_id = q.get("original_moodle_id")
                if orig_id:
                    question_bank[orig_id] = {
                        "question_id": q["question_id"],
                        "question_type": q["question_type"],
                        "prompt_text": q["prompt_text"],
                        "points": q["points"],
                        "answer_options": q.get("answer_options", []),
                    }
        return question_bank

    def _find_quiz_activities(self, parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find all quiz activities in parsed Moodle data."""
        quiz_activities = []
        for section in parsed.get("sections", []):
            for act in section.get("activities", []):
                if act.get("module_name") == "quiz":
                    quiz_activities.append(act)
        return quiz_activities

    def _create_quiz_assessments(
        self,
        quiz_activities: List[Dict[str, Any]],
        question_bank: Dict[str, Dict[str, Any]],
        assessments: List[Assessment],
        questions: List[Question],
        answer_options: List[AnswerOption],
    ) -> None:
        """
        Create Assessment and Question entities for each quiz activity.

        Groups all questions for a quiz into a single assessment.
        """
        for act in quiz_activities:
            qids = act.get("metadata", {}).get("question_ids", [])
            if not qids:
                continue

            # Get question data from the bank
            questions_for_quiz = [
                question_bank[qid] for qid in qids if qid in question_bank
            ]
            if not questions_for_quiz:
                continue

            # Create assessment
            assessment_id = str(uuid.uuid4())
            assessment = Assessment(
                assessment_id=assessment_id,
                course_id=parsed.get("course_id") or job_id,
                title=act.get("title", "Quiz"),
                assessment_type=AssessmentType.QUIZ,
                raw_fragment_ids=[],
                metadata={"quiz_activity_id": act.get("cmid")},
            )
            assessments.append(assessment)

            # Create Question entities
            for q_data in questions_for_quiz:
                question = Question(
                    question_id=q_data["question_id"],
                    assessment_id=assessment_id,
                    question_type=q_data["question_type"],
                    prompt_text=q_data["prompt_text"],
                    points=q_data["points"],
                    raw_fragment_ids=[],
                )
                questions.append(question)

                for opt in q_data.get("answer_options", []):
                    answer_options.append(
                        AnswerOption(
                            option_id=str(uuid.uuid4()),
                            question_id=question.question_id,
                            text=opt["text"],
                            is_correct=opt["is_correct"],
                        )
                    )

            # Link activity to assessment
            act["assessment_id"] = assessment_id

    def _build_moodle_content_tree(
        self,
        parsed: Dict[str, Any],
        quiz_activities: List[Dict[str, Any]],
        content_nodes: List[ContentNode],
        assessments: List[Assessment],
    ) -> None:
        """Build hierarchical content tree for Moodle (Section -> Content -> Activity -> Component)."""
        quiz_activity_map = {act.get("cmid"): act for act in quiz_activities}

        for section_idx, section in enumerate(parsed.get("sections", [])):
            # Create chapter node (section)
            chapter_node = ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.CHAPTER,
                title=section.get("title", f"Section {section_idx + 1}"),
                position=section_idx,
                raw_fragment_ids=[section["raw_fragment_id"]]
                if section.get("raw_fragment_id")
                else [],
                metadata={"moodle_section_id": section.get("section_id")},
            )
            content_nodes.append(chapter_node)

            # Create sequential node (Content container)
            seq_node = ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.SEQUENTIAL,
                title="Content",
                parent_id=chapter_node.node_id,
                position=0,
            )
            chapter_node.children.append(seq_node)

            # Process activities
            for act_idx, act in enumerate(section.get("activities", [])):
                vert_node = ContentNode(
                    node_id=str(uuid.uuid4()),
                    node_type=NodeType.VERTICAL,
                    title=act.get("title", f"Activity {act_idx + 1}"),
                    parent_id=seq_node.node_id,
                    position=act_idx,
                    raw_fragment_ids=[act["raw_fragment_id"]]
                    if act.get("raw_fragment_id")
                    else [],
                    metadata={"moodle_cmid": act.get("cmid")},
                )
                seq_node.children.append(vert_node)

                # Create component node based on module type
                comp = self._create_moodle_component(act)
                vert_node.children.append(comp)

    def _create_moodle_component(self, act: Dict[str, Any]) -> ContentNode:
        """Create a component ContentNode for a Moodle activity."""
        module = act.get("module_name", "")
        node_type_str = act.get("node_type", "")
        content_html = act.get("content_html", "")
        assessment_id = act.get("assessment_id")

        if module in ("page", "label") or node_type_str in ("page", "html"):
            return ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.HTML,
                title=act.get("title"),
                parent_id=-1,  # Will be set by caller
                position=0,
                metadata={"content_html": content_html},
            )

        if module == "quiz" or node_type_str == "quiz":
            return ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.PROBLEM,
                title=act.get("title"),
                parent_id=-1,
                position=0,
                assessment_id=assessment_id,
            )

        if node_type_str == "video":
            return ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.VIDEO,
                title=act.get("title"),
                parent_id=-1,
                position=0,
                metadata=act.get("metadata", {}),
            )

        # Unsupported activity -> HTML placeholder
        return ContentNode(
            node_id=str(uuid.uuid4()),
            node_type=NodeType.HTML,
            title=act.get("title", "Unknown"),
            parent_id=-1,
            position=0,
            metadata={"content_html": f"<p>Unsupported activity: {module}</p>"},
        )
