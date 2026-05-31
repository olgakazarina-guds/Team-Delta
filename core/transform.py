from domain.entities import Course, ContentNode, Assessment, Question, AnswerOption, Asset, RawFragment, MappingNote
from domain.enums import SourceSystem, NodeType, AssessmentType, Severity   # Added AssessmentType enum for type safety
from adapters.openedx.problem_parser import parse_problem
import uuid


class TransformService:
    """
    Service responsible for transforming parsed LMS data (Open edX, Moodle) 
    into normalized domain entities (Course, ContentNode, Assessment, etc.).
    """
    
    def transform(self, parsed: dict, source_type: str, job_id: str) -> Course:
        """
        Entry point for transformation logic. Routes to source-specific 
        transformation methods based on the input type.
        
        Args:
            parsed: Parsed data dictionary from the source LMS
            source_type: Identifier for the source system ("openedx" or "moodle")
            job_id: Unique identifier for the transformation job/course
            
        Returns:
            Transformed Course domain object
            
        Raises:
            ValueError: If source_type is not supported
        """
        if source_type == "openedx":
            return self._transform_openedx(parsed, job_id)
        elif source_type == "moodle":
            return self._transform_moodle(parsed, job_id)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

    def _transform_openedx(self, parsed: dict, job_id: str) -> Course:
        """
        Transforms parsed Open edX course data into domain entities.
        
        Builds a hierarchical content structure (Chapter → Sequential → Vertical → Component)
        and extracts assessments/problems with their questions and answer options.
        
        Args:
            parsed: Parsed Open edX course data
            job_id: Unique course identifier
            
        Returns:
            Fully transformed Course object with all nested entities
        """
        # -------------------------------------------------------------------------
        # Step 1: Extract raw fragments for provenance and debugging
        # -------------------------------------------------------------------------
        raw_fragments = []
        for frag in parsed.get("raw_fragments", []):
            raw_fragments.append(RawFragment(
                fragment_id=frag["fragment_id"],
                kind=frag["kind"],
                source_location=frag["source_location"],
                raw_text=frag.get("raw_text"),
                raw_bytes_ref=frag.get("raw_bytes_ref"),
                checksum=frag.get("checksum")
            ))

        # -------------------------------------------------------------------------
        # Step 2: Initialize containers for assessment-related entities
        # -------------------------------------------------------------------------
        assessments = []
        questions = []
        answer_options = []

        # -------------------------------------------------------------------------
        # Step 3: Build hierarchical content nodes (Chapter → Sequential → Vertical → Component)
        # -------------------------------------------------------------------------
        content_nodes = []
        node_id_map = {}  # Maps url_name → node_id for cross-referencing

        for chapter_idx, chapter in enumerate(parsed.get("chapters", [])):
            # Create chapter node (top-level hierarchy)
            chapter_node = ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.CHAPTER,
                title=chapter.get("title"),
                position=chapter_idx,
                raw_fragment_ids=[chapter["raw_fragment_id"]] if chapter.get("raw_fragment_id") else []
            )
            node_id_map[chapter["url_name"]] = chapter_node.node_id
            content_nodes.append(chapter_node)

            for seq_idx, seq in enumerate(chapter.get("sequentials", [])):
                # Create sequential node (child of chapter)
                seq_node = ContentNode(
                    node_id=str(uuid.uuid4()),
                    node_type=NodeType.SEQUENTIAL,
                    title=seq.get("title"),
                    parent_id=chapter_node.node_id,
                    position=seq_idx,
                    raw_fragment_ids=[seq["raw_fragment_id"]] if seq.get("raw_fragment_id") else []
                )
                node_id_map[seq["url_name"]] = seq_node.node_id
                chapter_node.children.append(seq_node)

                for vert_idx, vert in enumerate(seq.get("verticals", [])):
                    # Create vertical node (child of sequential)
                    vert_node = ContentNode(
                        node_id=str(uuid.uuid4()),
                        node_type=NodeType.VERTICAL,
                        title=vert.get("title"),
                        parent_id=seq_node.node_id,
                        position=vert_idx,
                        raw_fragment_ids=[vert["raw_fragment_id"]] if vert.get("raw_fragment_id") else []
                    )
                    node_id_map[vert["url_name"]] = vert_node.node_id
                    seq_node.children.append(vert_node)

                    for comp_idx, comp in enumerate(vert.get("components", [])):
                        # Map component type to node type
                        comp_type_map = {
                            "html": NodeType.HTML,
                            "video": NodeType.VIDEO,
                            "problem": NodeType.PROBLEM,
                            "openassessment": NodeType.OPENASSESSMENT,
                            "lti": NodeType.LTI
                        }
                        node_type = comp_type_map.get(comp["type"], NodeType.UNKNOWN)
                        
                        # Create component node (child of vertical)
                        comp_node = ContentNode(
                            node_id=str(uuid.uuid4()),
                            node_type=node_type,
                            title=comp.get("title", ""),
                            parent_id=vert_node.node_id,
                            position=comp_idx,
                            raw_fragment_ids=[comp["raw_fragment_id"]] if comp.get("raw_fragment_id") else [],
                            metadata={"inline_xml": comp.get("inline_xml")} if comp.get("inline_xml") else {}
                        )
                        vert_node.children.append(comp_node)

                        # -------------------------------------------------------------------------
                        # Step 4: Handle problem components — parse and extract assessments
                        # -------------------------------------------------------------------------
                        if node_type == NodeType.PROBLEM and comp.get("raw_fragment_id"):
                            raw_frag = next(
                                (f for f in raw_fragments if f.fragment_id == comp["raw_fragment_id"]), 
                                None
                            )
                            if raw_frag and raw_frag.raw_text:
                                # Parse the problem XML into structured data
                                problem_data = parse_problem(raw_frag.raw_text, comp.get("url_name", ""))
                                
                                # Create assessment entity
                                assessment_id = str(uuid.uuid4())
                                assessment = Assessment(
                                    assessment_id=assessment_id,
                                    course_id=job_id,      # Temporary; will be replaced during persistence
                                    title=problem_data["assessment_title"],
                                    assessment_type=AssessmentType.QUIZ,
                                    max_score=sum(q.get("points", 0) for q in problem_data["questions"]),
                                    raw_fragment_ids=[comp["raw_fragment_id"]],
                                    metadata={
                                        "problem_url_name": comp.get("url_name"),
                                        "original_type": "problem"
                                    }
                                )
                                assessments.append(assessment)
                                
                                # Link content node to its assessment
                                comp_node.assessment_id = assessment_id
                                
                                # Create questions and answer options
                                for q_data in problem_data["questions"]:
                                    question = Question(
                                        question_id=q_data["question_id"],
                                        assessment_id=assessment_id,
                                        question_type=q_data["type"],
                                        prompt_text=q_data["prompt"],
                                        points=q_data.get("points", 1.0),
                                        raw_fragment_ids=[comp["raw_fragment_id"]],
                                        metadata={}
                                    )
                                    questions.append(question)
                                    
                                    for opt in q_data.get("answer_options", []):
                                        answer_option = AnswerOption(
                                            option_id=str(uuid.uuid4()),
                                            question_id=question.question_id,
                                            text=opt["text"],
                                            is_correct=opt["is_correct"]
                                        )
                                        answer_options.append(answer_option)

        # -------------------------------------------------------------------------
        # Step 5: Assemble and return the Course domain object
        # -------------------------------------------------------------------------
        course = Course(
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
                "extracted_path": parsed.get("extracted_path")
            }
        )
        return course

    def _transform_moodle(self, parsed: dict, job_id: str) -> Course:
        """
        Transforms parsed Moodle course data into domain entities.
        
        Maps Moodle sections → activities → components, with special handling for
        question bank assessments and quiz activity linking.
        
        Args:
            parsed: Parsed Moodle course data
            job_id: Unique course identifier
            
        Returns:
            Fully transformed Course object with assessments, questions, and assets
        """
        # -------------------------------------------------------------------------
        # Step 1: Extract raw fragments for provenance and debugging
        # -------------------------------------------------------------------------
        raw_fragments = []
        for frag in parsed.get("raw_fragments", []):
            raw_fragments.append(RawFragment(
                fragment_id=frag["fragment_id"],
                kind=frag["kind"],
                source_location=frag["source_location"],
                raw_text=frag.get("raw_text"),
                raw_bytes_ref=frag.get("raw_bytes_ref"),
                checksum=frag.get("checksum")
            ))

        # -------------------------------------------------------------------------
        # Step 2: Initialize entity containers
        # -------------------------------------------------------------------------
        content_nodes = []
        assessments = []
        assets = []
        questions = []
        answer_options = []

        # -------------------------------------------------------------------------
        # Step 3: Process question bank assessments and build question-to-assessment mapping
        # -------------------------------------------------------------------------
        question_id_to_assessment = {}

        # Create assessments from the Moodle question bank
        for qa in parsed.get("questions_assessments", []):
            assessment = Assessment(
                assessment_id=qa["assessment_id"],
                course_id=parsed.get("course_id") or job_id,
                title=qa["title"],
                assessment_type=AssessmentType.QUIZ,
                raw_fragment_ids=[],
                metadata={
                    "from_question_bank": True, 
                    "original_question_ids": qa.get("original_question_ids", [])
                }
            )
            assessments.append(assessment)
            
            # Map each original question ID to its assessment for later linking
            for orig_id in qa.get("original_question_ids", []):
                question_id_to_assessment[orig_id] = assessment.assessment_id
            
            # Create question entities and their answer options
            for q in qa["questions"]:
                question = Question(
                    question_id=q["question_id"],
                    assessment_id=assessment.assessment_id,
                    question_type=q["question_type"],
                    prompt_text=q["prompt_text"],
                    points=q["points"],
                    raw_fragment_ids=[],
                )
                questions.append(question)
                
                for opt in q.get("answer_options", []):
                    answer_options.append(AnswerOption(
                        option_id=str(uuid.uuid4()),
                        question_id=question.question_id,
                        text=opt["text"],
                        is_correct=opt["is_correct"],
                    ))

        # -------------------------------------------------------------------------
        # Step 4: Link quiz activities to their corresponding assessments
        # -------------------------------------------------------------------------
        for section in parsed.get("sections", []):
            for act in section.get("activities", []):
                # Check if this is a quiz activity with referenced question IDs
                if act.get("module_name") == "quiz" and act.get("metadata", {}).get("question_ids"):
                    qids = act["metadata"]["question_ids"]
                    
                    # Look for existing assessment tied to this quiz activity
                    existing_assessments = [
                        a for a in assessments 
                        if a.metadata.get("quiz_activity_id") == act.get("cmid")
                    ]
                    
                    if existing_assessments:
                        assessment_id = existing_assessments[0].assessment_id
                    else:
                        # Create a new assessment to group questions from this quiz
                        assessment_id = str(uuid.uuid4())
                        new_assessment = Assessment(
                            assessment_id=assessment_id,
                            course_id=parsed.get("course_id") or job_id,
                            title=act.get("title", "Quiz"),
                            assessment_type=AssessmentType.QUIZ,
                            metadata={"quiz_activity_id": act.get("cmid")}
                        )
                        assessments.append(new_assessment)
                        
                        # Link to question bank assessment if questions exist there
                        for qid in qids:
                            if qid in question_id_to_assessment:
                                assessment_id = question_id_to_assessment[qid]
                                break
                    
                    # Store the assessment_id in the activity for component linking
                    act["assessment_id"] = assessment_id

        # -------------------------------------------------------------------------
        # Step 5: Build hierarchical content nodes (Section → Sequential → Vertical → Component)
        # -------------------------------------------------------------------------
        for section_idx, section in enumerate(parsed.get("sections", [])):
            # Chapter = Moodle section
            chapter_node = ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.CHAPTER,
                title=section.get("title", f"Section {section_idx+1}"),
                position=section_idx,
                raw_fragment_ids=[section["raw_fragment_id"]] if section.get("raw_fragment_id") else [],
                metadata={"moodle_section_id": section.get("section_id")},
            )
            content_nodes.append(chapter_node)

            # Create a Sequential wrapper (required by Open edX hierarchy)
            seq_node = ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.SEQUENTIAL,
                title="Content",
                parent_id=chapter_node.node_id,
                position=0,
            )
            chapter_node.children.append(seq_node)

            # Process activities — each becomes a Vertical with components
            for act_idx, act in enumerate(section.get("activities", [])):
                vert_node = ContentNode(
                    node_id=str(uuid.uuid4()),
                    node_type=NodeType.VERTICAL,
                    title=act.get("title", f"Activity {act_idx+1}"),
                    parent_id=seq_node.node_id,
                    position=act_idx,
                    raw_fragment_ids=[act["raw_fragment_id"]] if act.get("raw_fragment_id") else [],
                    metadata={"moodle_cmid": act.get("cmid")},
                )
                seq_node.children.append(vert_node)

                # Determine component type based on Moodle module
                module = act.get("module_name", "")
                node_type_str = act.get("node_type", "")
                content_html = act.get("content_html", "")
                assessment_id = act.get("assessment_id")

                if module == "page" or node_type_str == "page":
                    # Page activity → HTML component
                    comp = ContentNode(
                        node_id=str(uuid.uuid4()),
                        node_type=NodeType.HTML,
                        title=act.get("title"),
                        parent_id=vert_node.node_id,
                        position=0,
                        metadata={"content_html": content_html},
                    )
                    vert_node.children.append(comp)
                    
                elif module == "label" or node_type_str == "html":
                    # Label activity → HTML component
                    comp = ContentNode(
                        node_id=str(uuid.uuid4()),
                        node_type=NodeType.HTML,
                        title=act.get("title"),
                        parent_id=vert_node.node_id,
                        position=0,
                        metadata={"content_html": content_html},
                    )
                    vert_node.children.append(comp)
                    
                elif module == "quiz" or node_type_str == "quiz":
                    # Quiz activity → Problem component with assessment link
                    comp = ContentNode(
                        node_id=str(uuid.uuid4()),
                        node_type=NodeType.PROBLEM,
                        title=act.get("title"),
                        parent_id=vert_node.node_id,
                        position=0,
                        assessment_id=assessment_id,
                    )
                    vert_node.children.append(comp)
                    
                else:
                    # Unsupported activity → HTML placeholder with warning
                    comp = ContentNode(
                        node_id=str(uuid.uuid4()),
                        node_type=NodeType.HTML,
                        title=act.get("title", "Unknown"),
                        parent_id=vert_node.node_id,
                        position=0,
                        metadata={"content_html": f"<p>Unsupported activity: {module}</p>"},
                    )
                    vert_node.children.append(comp)

        # -------------------------------------------------------------------------
        # Step 6: Build asset entities (files, media, etc.)
        # -------------------------------------------------------------------------
        for a in parsed.get("assets", []):
            assets.append(Asset(
                asset_id=a["asset_id"],
                course_id=parsed.get("course_id") or job_id,
                path=a.get("path", ""),
                mime_type=a.get("mime_type"),
                checksum=a.get("checksum"),
            ))

        # -------------------------------------------------------------------------
        # Step 7: Assemble and return the Course domain object
        # -------------------------------------------------------------------------
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
