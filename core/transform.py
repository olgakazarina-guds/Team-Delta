from domain.entities import Course, ContentNode, Assessment, Asset, RawFragment, MappingNote
from domain.enums import SourceSystem, NodeType, Severity, AssessmentType
import uuid

class TransformService:
    def transform(self, parsed: dict, source_type: str, job_id: str) -> Course:
        if source_type == "openedx":
            return self._transform_openedx(parsed, job_id)
        elif source_type == "moodle":
            return self._transform_moodle(parsed, job_id)
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

        # Create content nodes (chapters -> sequentials -> verticals -> components)
        content_nodes = []
        node_id_map = {}  # url_name -> node_id for linking

        # Process chapters, sequentials, verticals
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

        # Create Course object
        course = Course(
            course_id=job_id,  # temporary, will be replaced later
            title=parsed.get("course_title", "Unnamed Course"),
            source_system=SourceSystem.OPENEDX,
            content_nodes=content_nodes,
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
        Convert the dict produced by MoodleCourseParser into a canonical Course object.

        The tree structure is two levels deep: Section -> Activity.
        Each section becomes a top-level ContentNode; its activities become children
        appended inline to section_node.children, matching the OpenEdX nesting pattern.

        Assessments (quizzes) and Assets (resource files) are built from the flat lists
        accumulated by the parser and stored on the Course alongside content_nodes.

        Pydantic v2 coerces plain dict source_location values to SourceLocation objects
        automatically, so fragments can be passed as dicts without manual hydration.
        """
        raw_fragments = [
            RawFragment(
                fragment_id=fragment["fragment_id"],
                kind=fragment["kind"],
                source_location=fragment["source_location"],
                raw_text=fragment.get("raw_text", ""),  # note use of get since it might be absent
                raw_bytes_ref=fragment.get("raw_bytes_ref", ""),
                checksum=fragment.get("checksum", ""),
            )
            for fragment in parsed.get("fragments", [])
        ]

        content_nodes = []
        for section in parsed.get("sections", []):
            section_node = ContentNode(
                node_id=str(uuid.uuid4()),
                node_type=NodeType.SECTION,
                title=section.get("title", ""),
                position=section.get("position", 0),
                raw_fragment_ids=[section["raw_fragment_id"]] if section.get("raw_fragment_id") else [],
                metadata={"moodle_section_id": section.get("section_id")},
            )
            content_nodes.append(section_node)

            for activity_idx, activity in enumerate(section.get("activities", [])):
                node_type = NodeType(activity.get("node_type", NodeType.UNKNOWN.value))

                # Assemble activity metadata: start with Moodle identifiers, then overlay content_html and
                # assessment_id if present, then any type-specific extras from the parser's own metadata dict
                activity_metadata = {
                    "moodle_cmid": activity.get("cmid"),
                    "module_name": activity.get("module_name"),
                }
                if activity.get("content_html"):
                    activity_metadata["content_html"] = activity["content_html"]
                if activity.get("assessment_id"):
                    activity_metadata["assessment_id"] = activity["assessment_id"]
                activity_metadata.update(activity.get("metadata", {}))

                act_node = ContentNode(
                    node_id=str(uuid.uuid4()),
                    node_type=node_type,
                    title=activity.get("title"),
                    parent_id=section_node.node_id,
                    position=activity_idx,
                    raw_fragment_ids=[activity["raw_fragment_id"]] if activity.get("raw_fragment_id") else [],
                    metadata=activity_metadata,
                )
                section_node.children.append(act_node)

        # Build Assessment objects from the flat list accumulated during the parse.
        # course_id falls back to job_id if the Moodle course id was not present in course.xml
        assessments = [
            Assessment(
                assessment_id=a["assessment_id"],
                course_id=parsed.get("course_id") or job_id,
                title=a.get("title", ""),
                assessment_type=AssessmentType(a.get("assessment_type", "quiz")),
                raw_fragment_ids=[],
            )
            for a in parsed.get("assessments", [])
        ]

        # Build Asset objects for resource files resolved via inforef during the parse
        assets = [
            Asset(
                asset_id=a["asset_id"],
                course_id=parsed.get("course_id") or job_id,
                path=a.get("path", ""),
                mime_type=a.get("mime_type"),
                checksum=a.get("checksum"),
            )
            for a in parsed.get("assets", [])
        ]

        return Course(
            course_id=parsed.get("course_id") or job_id,
            title=parsed.get("course_title", "Unnamed Course"),
            source_system=SourceSystem.MOODLE,
            content_nodes=content_nodes,
            assessments=assessments,
            assets=assets,
            raw_fragments=raw_fragments,
            metadata={
                "shortname": parsed.get("course_shortname"),
                "lang": parsed.get("lang"),
            },
        )

