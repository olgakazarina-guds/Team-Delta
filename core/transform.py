from domain.entities import Course, ContentNode, Assessment, Question, AnswerOption, Asset, RawFragment, MappingNote
from domain.enums import SourceSystem, NodeType, AssessmentType, Severity   # added AssessmentType
from adapters.openedx.problem_parser import parse_problem
import uuid

class TransformService:
    def transform(self, parsed: dict, source_type: str, job_id: str) -> Course:
        if source_type == "openedx":
            return self._transform_openedx(parsed, job_id)
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

    def _transform_openedx(self, parsed: dict, job_id: str) -> Course:
        # Create raw fragments list
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

        # Prepare containers for assessments, questions, answer_options
        assessments = []
        questions = []
        answer_options = []

        # Create content nodes (chapters -> sequentials -> verticals -> components)
        content_nodes = []
        node_id_map = {}  # url_name -> node_id for linking

        for chapter_idx, chapter in enumerate(parsed.get("chapters", [])):
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
                        comp_type_map = {
                            "html": NodeType.HTML,
                            "video": NodeType.VIDEO,
                            "problem": NodeType.PROBLEM,
                            "openassessment": NodeType.OPENASSESSMENT,
                            "lti": NodeType.LTI
                        }
                        node_type = comp_type_map.get(comp["type"], NodeType.UNKNOWN)
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

                        # --- Handle problem components ---
                        if node_type == NodeType.PROBLEM and comp.get("raw_fragment_id"):
                            raw_frag = next((f for f in raw_fragments if f.fragment_id == comp["raw_fragment_id"]), None)
                            if raw_frag and raw_frag.raw_text:
                                problem_data = parse_problem(raw_frag.raw_text, comp.get("url_name", ""))
                                
                                # Create assessment
                                assessment_id = str(uuid.uuid4())
                                assessment = Assessment(
                                    assessment_id=assessment_id,
                                    course_id=job_id,      # temporary, will be replaced later
                                    title=problem_data["assessment_title"],
                                    assessment_type=AssessmentType.QUIZ,   # using enum
                                    max_score=sum(q.get("points", 0) for q in problem_data["questions"]),
                                    raw_fragment_ids=[comp["raw_fragment_id"]],
                                    metadata={
                                        "problem_url_name": comp.get("url_name"),
                                        "original_type": "problem"
                                    }
                                )
                                assessments.append(assessment)
                                
                                # Link the content node to this assessment
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

        # Build the Course object
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
