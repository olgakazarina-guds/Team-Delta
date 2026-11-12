"""
Transform Service - Converts parsed LMS data into normalized domain entities.

Transforms parsed Open edX or Moodle data into canonical domain entities:
- Course
- ContentNode (hierarchical: chapter -> sequential -> vertical -> component)
- Assessment
- Question
- AnswerOption
- Asset
- RawFragment
"""

import logging
from typing import Any

from adapters.openedx.problem_parser import parse_problem
from core.identity import stable_id
from domain.entities import (
    AnswerOption,
    Assessment,
    Asset,
    ContentNode,
    Course,
    Question,
    ScormAsset,
)
from domain.enums import AssessmentType, NodeType, SourceSystem
from domain.raw_fragment import RawFragment

logger = logging.getLogger(__name__)


class TransformService:
    """Transform parsed LMS data into canonical domain entities."""

    def transform(self, parsed: dict[str, Any], source_type: str, job_id: str) -> Course:
        """Route parsed data to the appropriate source-specific transformer."""
        logger.info("Transforming %s parse output to canonical IR (job %s)", source_type, job_id)
        if source_type == "openedx":
            course = self._transform_openedx(parsed, job_id)
        elif source_type == "moodle":
            course = self._transform_moodle(parsed, job_id)
        else:
            logger.error("Unsupported source type: %s", source_type)
            raise ValueError(f"Unsupported source type: {source_type}")

        logger.debug(
            "Built course '%s' with %d top-level nodes, %d assets",
            course.title,
            len(course.content_nodes),
            len(course.assets),
        )
        return course

    def _build_raw_fragments(self, parsed: dict[str, Any]) -> list[RawFragment]:
        """Build RawFragment entities from parsed data."""
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

    def _transform_openedx(self, parsed: dict, job_id: str) -> Course:
        source_key = parsed.get("course_key") or ":".join(
            [
                str(parsed.get("org") or "org"),
                str(parsed.get("course_code") or "course"),
                str(parsed.get("course_url_name") or "course"),
            ]
        )
        course_id = stable_id("course", "openedx", source_key)
        raw_fragments = self._build_raw_fragments(parsed)
        assessments: list[Assessment] = []
        questions: list[Question] = []
        answer_options: list[AnswerOption] = []
        content_nodes: list[ContentNode] = []
        assets = [
            self._asset_from_dict(asset_data, course_id) for asset_data in parsed.get("assets", [])
        ]
        assets_by_path = {asset.path: asset for asset in assets}

        component_types = {
            "html": NodeType.HTML,
            "video": NodeType.VIDEO,
            "problem": NodeType.PROBLEM,
            "openassessment": NodeType.OPENASSESSMENT,
            "discussion": NodeType.FORUM,
            "lti": NodeType.LTI,
            "scorm": NodeType.SCORM,
            "scormxblock": NodeType.SCORM,
        }

        for chapter_idx, chapter in enumerate(parsed.get("chapters", [])):
            chapter_ref = chapter.get("url_name") or str(chapter_idx)
            chapter_node = ContentNode(
                node_id=stable_id("node", course_id, "chapter", chapter_ref),
                node_type=NodeType.CHAPTER,
                title=chapter.get("title"),
                position=chapter_idx,
                raw_fragment_ids=[chapter["raw_fragment_id"]]
                if chapter.get("raw_fragment_id")
                else [],
                metadata={"source_url_name": chapter.get("url_name")},
            )
            content_nodes.append(chapter_node)

            for seq_idx, seq in enumerate(chapter.get("sequentials", [])):
                seq_ref = seq.get("url_name") or f"{chapter_ref}:{seq_idx}"
                seq_node = ContentNode(
                    node_id=stable_id("node", course_id, "sequential", seq_ref),
                    node_type=NodeType.SEQUENTIAL,
                    title=seq.get("title"),
                    parent_id=chapter_node.node_id,
                    position=seq_idx,
                    raw_fragment_ids=[seq["raw_fragment_id"]] if seq.get("raw_fragment_id") else [],
                    metadata={"source_url_name": seq.get("url_name")},
                )
                chapter_node.children.append(seq_node)

                for vert_idx, vert in enumerate(seq.get("verticals", [])):
                    vert_ref = vert.get("url_name") or f"{seq_ref}:{vert_idx}"
                    vert_node = ContentNode(
                        node_id=stable_id("node", course_id, "vertical", vert_ref),
                        node_type=NodeType.VERTICAL,
                        title=vert.get("title"),
                        parent_id=seq_node.node_id,
                        position=vert_idx,
                        raw_fragment_ids=[vert["raw_fragment_id"]]
                        if vert.get("raw_fragment_id")
                        else [],
                        metadata={"source_url_name": vert.get("url_name")},
                    )
                    seq_node.children.append(vert_node)

                    for comp_idx, comp in enumerate(vert.get("components", [])):
                        node_type = component_types.get(comp.get("type"), NodeType.UNKNOWN)
                        metadata = dict(comp.get("metadata") or {})
                        if comp.get("inline_xml"):
                            metadata["inline_xml"] = comp["inline_xml"]
                        if comp.get("content_html"):
                            metadata["content_html"] = comp["content_html"]
                        asset_path = metadata.get("asset_path")
                        if asset_path and asset_path in assets_by_path:
                            metadata["asset_id"] = assets_by_path[asset_path].asset_id

                        comp_ref = comp.get("url_name") or f"{vert_ref}:{comp_idx}"
                        comp_node = ContentNode(
                            node_id=stable_id("node", course_id, "component", comp_ref),
                            node_type=node_type,
                            title=comp.get("title", ""),
                            parent_id=vert_node.node_id,
                            position=comp_idx,
                            raw_fragment_ids=[comp["raw_fragment_id"]]
                            if comp.get("raw_fragment_id")
                            else [],
                            metadata=metadata,
                        )
                        vert_node.children.append(comp_node)

                        if node_type == NodeType.PROBLEM and comp.get("raw_fragment_id"):
                            raw_frag = next(
                                (
                                    f
                                    for f in raw_fragments
                                    if f.fragment_id == comp["raw_fragment_id"]
                                ),
                                None,
                            )
                            if raw_frag and raw_frag.raw_text:
                                self._add_openedx_problem(
                                    raw_frag.raw_text,
                                    comp,
                                    comp_node,
                                    course_id,
                                    assessments,
                                    questions,
                                    answer_options,
                                )

        return Course(
            course_id=course_id,
            title=parsed.get("course_title", "Unnamed Course"),
            source_system=SourceSystem.OPENEDX,
            content_nodes=content_nodes,
            assessments=assessments,
            questions=questions,
            answer_options=answer_options,
            assets=assets,
            raw_fragments=raw_fragments,
            metadata={
                "org": parsed.get("org"),
                "course_code": parsed.get("course_code"),
                "source_key": source_key,
                "job_id": job_id,
                "extracted_path": parsed.get("extracted_path"),
                "schema_version": 2,
            },
        )

    def _add_openedx_problem(
        self,
        raw_problem_xml: str,
        comp: dict[str, Any],
        comp_node: ContentNode,
        course_id: str,
        assessments: list[Assessment],
        questions: list[Question],
        answer_options: list[AnswerOption],
    ) -> None:
        problem_data = parse_problem(raw_problem_xml, comp.get("url_name", ""))
        problem_ref = comp.get("url_name") or comp_node.node_id
        assessment_id = stable_id("assessment", course_id, "problem", problem_ref)
        assessment = Assessment(
            assessment_id=assessment_id,
            course_id=course_id,
            title=problem_data["assessment_title"],
            assessment_type=AssessmentType.QUIZ,
            max_score=sum(q.get("points", 0) for q in problem_data["questions"]),
            raw_fragment_ids=[comp["raw_fragment_id"]] if comp.get("raw_fragment_id") else [],
            metadata={
                "problem_url_name": comp.get("url_name"),
                "original_type": "problem",
            },
        )
        assessments.append(assessment)
        comp_node.assessment_id = assessment_id

        for q_index, q_data in enumerate(problem_data["questions"]):
            question_type = self._normalise_question_type(q_data.get("type", "unknown"))
            question_id = stable_id("question", assessment_id, q_index, question_type)
            q_metadata: dict[str, Any] = {
                "source_question_id": q_data.get("question_id"),
            }
            if q_data.get("correct_answers"):
                q_metadata["correct_answers"] = q_data["correct_answers"]
            if q_data.get("correct_answer") is not None:
                q_metadata["correct_answer"] = q_data["correct_answer"]

            question = Question(
                question_id=question_id,
                assessment_id=assessment_id,
                question_type=question_type,
                prompt_text=q_data.get("prompt", ""),
                points=q_data.get("points", 1.0),
                raw_fragment_ids=[comp["raw_fragment_id"]] if comp.get("raw_fragment_id") else [],
                metadata=q_metadata,
            )
            questions.append(question)

            for opt_index, opt in enumerate(q_data.get("answer_options", [])):
                answer_options.append(
                    AnswerOption(
                        option_id=stable_id("option", question_id, opt_index),
                        question_id=question_id,
                        text=opt["text"],
                        is_correct=opt["is_correct"],
                    )
                )

    def _transform_moodle(self, parsed: dict[str, Any], job_id: str) -> Course:
        source_key = (
            parsed.get("course_id")
            or parsed.get("course_shortname")
            or parsed.get("course_title")
            or "moodle-course"
        )
        course_id = stable_id("course", "moodle", source_key)
        raw_fragments = self._build_raw_fragments(parsed)
        content_nodes: list[ContentNode] = []
        assessments: list[Assessment] = []
        assets: list[Asset] = []
        questions: list[Question] = []
        answer_options: list[AnswerOption] = []

        question_bank = self._build_question_bank(parsed)
        quiz_activities = self._find_quiz_activities(parsed)
        self._create_quiz_assessments(
            parsed,
            course_id,
            quiz_activities,
            question_bank,
            assessments,
            questions,
            answer_options,
        )
        self._build_moodle_content_tree(parsed, content_nodes, course_id)

        for asset_data in parsed.get("assets", []):
            assets.append(self._asset_from_dict(asset_data, course_id))

        return Course(
            course_id=course_id,
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
                "source_key": source_key,
                "job_id": job_id,
                "extracted_path": parsed.get("extracted_path"),
                "schema_version": 2,
            },
        )

    def _build_question_bank(self, parsed: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Build a map from original Moodle question ID to question data."""
        question_bank = {}
        for qa in parsed.get("questions_assessments", []):
            for q in qa.get("questions", []):
                orig_id = q.get("original_moodle_id")
                if not orig_id:
                    continue
                question_bank[orig_id] = {
                    "question_id": q["question_id"],
                    "original_moodle_id": orig_id,
                    "question_type": q["question_type"],
                    "prompt_text": q.get("prompt_text", ""),
                    "points": q.get("points", 1.0),
                    "answer_options": q.get("answer_options", []),
                    "correct_answers": q.get("correct_answers", []),
                    "metadata": q.get("metadata", {}),
                }
        return question_bank

    def _find_quiz_activities(self, parsed: dict[str, Any]) -> list[dict[str, Any]]:
        """Find all quiz activities in parsed Moodle data."""
        quiz_activities = []
        for section in parsed.get("sections", []):
            for act in section.get("activities", []):
                if act.get("module_name") == "quiz":
                    quiz_activities.append(act)
        return quiz_activities

    def _create_quiz_assessments(
        self,
        parsed: dict[str, Any],
        course_id: str,
        quiz_activities: list[dict[str, Any]],
        question_bank: dict[str, dict[str, Any]],
        assessments: list[Assessment],
        questions: list[Question],
        answer_options: list[AnswerOption],
    ) -> None:
        """Create Assessment and Question entities for each Moodle quiz."""
        for act in quiz_activities:
            qids = act.get("metadata", {}).get("question_ids", [])
            questions_for_quiz = [question_bank[qid] for qid in qids if qid in question_bank]
            if not questions_for_quiz:
                continue

            activity_ref = act.get("cmid") or f"{act.get('title', 'quiz')}:{len(assessments)}"
            assessment_id = stable_id("assessment", course_id, "moodle-quiz", activity_ref)
            assessment = Assessment(
                assessment_id=assessment_id,
                course_id=course_id,
                title=act.get("title", "Quiz"),
                assessment_type=AssessmentType.QUIZ,
                max_score=sum(q.get("points", 0) for q in questions_for_quiz),
                raw_fragment_ids=[],
                metadata={"quiz_activity_id": act.get("cmid")},
            )
            assessments.append(assessment)

            for q_index, q_data in enumerate(questions_for_quiz):
                source_question_id = (
                    q_data.get("original_moodle_id") or q_data.get("question_id") or str(q_index)
                )
                question_id = stable_id("question", assessment_id, source_question_id)
                metadata = dict(q_data.get("metadata") or {})
                metadata["source_question_id"] = source_question_id
                if q_data.get("correct_answers"):
                    metadata["correct_answers"] = q_data["correct_answers"]
                if metadata.get("correct_answer") is None and q_data.get("correct_answers"):
                    metadata["correct_answer"] = q_data["correct_answers"][0]

                question = Question(
                    question_id=question_id,
                    assessment_id=assessment_id,
                    question_type=self._normalise_question_type(q_data["question_type"]),
                    prompt_text=q_data.get("prompt_text", ""),
                    points=q_data.get("points", 1.0),
                    raw_fragment_ids=[],
                    metadata=metadata,
                )
                questions.append(question)

                for opt_index, opt in enumerate(q_data.get("answer_options", [])):
                    answer_options.append(
                        AnswerOption(
                            option_id=stable_id("option", question_id, opt_index),
                            question_id=question_id,
                            text=opt["text"],
                            is_correct=opt["is_correct"],
                        )
                    )

            act["assessment_id"] = assessment_id

    def _build_moodle_content_tree(
        self,
        parsed: dict[str, Any],
        content_nodes: list[ContentNode],
        course_id: str,
    ) -> None:
        """Build the Moodle Section -> Activity -> Component hierarchy."""
        for section_idx, section in enumerate(parsed.get("sections", [])):
            section_ref = section.get("section_id") or str(section_idx)
            chapter_node = ContentNode(
                node_id=stable_id("node", course_id, "section", section_ref),
                node_type=NodeType.CHAPTER,
                title=section.get("title", f"Section {section_idx + 1}"),
                position=section_idx,
                raw_fragment_ids=[section["raw_fragment_id"]]
                if section.get("raw_fragment_id")
                else [],
                metadata={"moodle_section_id": section.get("section_id")},
            )
            content_nodes.append(chapter_node)

            seq_node = ContentNode(
                node_id=stable_id("node", course_id, "section-content", section_ref),
                node_type=NodeType.SEQUENTIAL,
                title="Content",
                parent_id=chapter_node.node_id,
                position=0,
            )
            chapter_node.children.append(seq_node)

            for act_idx, act in enumerate(section.get("activities", [])):
                activity_ref = act.get("cmid") or f"{section_ref}:{act_idx}"
                vert_node = ContentNode(
                    node_id=stable_id("node", course_id, "activity", activity_ref),
                    node_type=NodeType.VERTICAL,
                    title=act.get("title", f"Activity {act_idx + 1}"),
                    parent_id=seq_node.node_id,
                    position=act_idx,
                    raw_fragment_ids=[act["raw_fragment_id"]] if act.get("raw_fragment_id") else [],
                    metadata={
                        "moodle_cmid": act.get("cmid"),
                        "moodle_section_id": section.get("section_id"),
                    },
                )
                seq_node.children.append(vert_node)
                vert_node.children.append(
                    self._moodle_component(act, vert_node, course_id, activity_ref, act_idx)
                )

    def _moodle_component(
        self,
        act: dict[str, Any],
        parent: ContentNode,
        course_id: str,
        activity_ref: str,
        position: int,
    ) -> ContentNode:
        module = act.get("module_name", "")
        node_type_str = act.get("node_type", "")
        content_html = act.get("content_html", "")
        metadata = dict(act.get("metadata") or {})
        metadata.setdefault("content_html", content_html)
        assessment_id = act.get("assessment_id")
        node_id = stable_id("node", course_id, "component", activity_ref)

        if module in ("page", "label") or node_type_str in ("page", "html"):
            if module == "page":
                metadata.setdefault("moodle_module", "page")
            return ContentNode(
                node_id=node_id,
                node_type=NodeType.HTML,
                title=act.get("title"),
                parent_id=parent.node_id,
                position=position,
                metadata=metadata,
            )

        if module == "quiz" or node_type_str == "quiz":
            return ContentNode(
                node_id=node_id,
                node_type=NodeType.PROBLEM,
                title=act.get("title"),
                parent_id=parent.node_id,
                position=position,
                assessment_id=assessment_id,
                metadata=metadata,
            )

        if module == "forum" or node_type_str == "forum":
            return ContentNode(
                node_id=node_id,
                node_type=NodeType.FORUM,
                title=act.get("title"),
                parent_id=parent.node_id,
                position=position,
                metadata=metadata,
            )

        if module == "workshop" or node_type_str == "openassessment":
            metadata.setdefault("activity_type", "workshop")
            return ContentNode(
                node_id=node_id,
                node_type=NodeType.OPENASSESSMENT,
                title=act.get("title"),
                parent_id=parent.node_id,
                position=position,
                metadata=metadata,
            )

        if node_type_str == "video":
            return ContentNode(
                node_id=node_id,
                node_type=NodeType.VIDEO,
                title=act.get("title"),
                parent_id=parent.node_id,
                position=position,
                metadata=metadata,
            )

        if node_type_str == "scorm" or module == "scorm":
            return ContentNode(
                node_id=node_id,
                node_type=NodeType.SCORM,
                title=act.get("title"),
                parent_id=parent.node_id,
                position=position,
                metadata=metadata,
            )

        if node_type_str == "activity" or module == "url":
            url = metadata.get("externalurl", "")
            link = f'<p><a href="{url}">{url}</a></p>' if url else ""
            if metadata.get("asset_id") or module in ("resource", "url"):
                metadata["content_html"] = content_html or link
                return ContentNode(
                    node_id=node_id,
                    node_type=NodeType.ACTIVITY,
                    title=act.get("title"),
                    parent_id=parent.node_id,
                    position=position,
                    metadata=metadata,
                )
            return ContentNode(
                node_id=node_id,
                node_type=NodeType.HTML,
                title=act.get("title"),
                parent_id=parent.node_id,
                position=position,
                metadata={
                    **metadata,
                    "content_html": content_html or link,
                    "externalurl": url,
                },
            )

        if node_type_str == "lti" or module == "lti":
            return ContentNode(
                node_id=node_id,
                node_type=NodeType.LTI,
                title=act.get("title"),
                parent_id=parent.node_id,
                position=position,
                metadata=metadata,
            )

        return ContentNode(
            node_id=node_id,
            node_type=NodeType.HTML,
            title=act.get("title", "Unknown"),
            parent_id=parent.node_id,
            position=position,
            metadata={
                **metadata,
                "content_html": f"<p>Unsupported activity: {module}</p>",
            },
        )

    def _asset_from_dict(self, asset_data: dict[str, Any], course_id: str) -> Asset:
        common = {
            "asset_id": asset_data["asset_id"],
            "course_id": course_id,
            "path": asset_data.get("path", ""),
            "mime_type": asset_data.get("mime_type"),
            "checksum": asset_data.get("checksum"),
            "metadata": {
                key: value
                for key, value in asset_data.items()
                if key
                not in {
                    "asset_id",
                    "course_id",
                    "path",
                    "mime_type",
                    "checksum",
                    "original_zip_path",
                    "version",
                }
            },
        }

        if asset_data.get("is_scorm") or asset_data.get("original_zip_path"):
            return ScormAsset(
                **common,
                original_zip_path=asset_data.get("original_zip_path") or asset_data.get("path", ""),
                version=asset_data.get("version", ""),
            )
        return Asset(**common)

    def _normalise_question_type(self, question_type: str) -> str:
        mapping = {
            "single-select": "multichoice",
            "multi-select": "multiselect",
            "text_input": "shortanswer",
        }
        return mapping.get(question_type, question_type)
