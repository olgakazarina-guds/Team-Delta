from domain.entities import Course, ContentNode, Assessment, Asset, RawFragment, MappingNote
from domain.enums import SourceSystem, NodeType, Severity
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
