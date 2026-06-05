"""
Moodle Target Adapter, Converts canonical Course domain objects into 
Moodle export format (.mbz).

This adapter handles:
- video Full course hierarchy (Chapter-> Sequential -> Vertical -> Components)
- Assessments with questions and answer options
- Asset file copying from Moodle backups
- XML generation for all Open Moodle components (html, problem, video, etc.)
"""

import os
import tarfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional

from domain.entities import Course, ContentNode, Assessment, Question, AnswerOption, Asset, RawFragment, MappingNote
from domain.enums import SourceSystem, NodeType, AssessmentType, Severity


class MoodleTargetAdapter:
    """
    Adapter for exporting canonical Course objects to Open Moodle format.

    This class transforms domain entities into Open Moodle's XML-based course 
    structure and packages them into a tar.gz archive suitable for import 
    into Open edX instances.

    Attributes:
        work_dir: Temporary working directory for export files
        course: The Course domain object being exported
        node_id_map: Mapping from node_id to url_name for XML references
    """

    def __init__(self):
        """Initialize the adapter with empty state."""
        self.work_dir: Optional[Path] = None
        self.course: Optional[Course] = None
        self.node_id_map: Dict[str, str] = {}  # node_id -> url_name mapping

    def generate_export(
        self, 
        course: Course, 
        output_path: str, 
        edx_extracted_path: Optional[str] = None
    ) -> str:
        """
        Generate a Moodle course export tarball from a canonical Course.
    
        Creates the full directory structure, generates all XML files for 
        course hierarchy and components, copies assets if available, and 
        packages everything into a .tar.gz archive.
    
        Args:
            course: The canonical Course domain object to export
            output_path: Destination path for the .tar.gz file
            edx_extracted_path: Optional path to Open edX extract for copying assets
            
        Returns:
            Absolute path to the generated .mbz export file

        Example:
             adapter = OpenEdxTargetAdapter()
             output = adapter.generate_export(course, "output/course.tar.gz")

        """
        # -------------------------------------------------------------------------
        # Step 1: Initialize working directory and course state
        # -------------------------------------------------------------------------
        self.course = course
        self.work_dir = Path("data/moodle_export") / uuid.uuid4().hex
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # -------------------------------------------------------------------------
        # Step 2: Create Open Moodle directory structure
        # -------------------------------------------------------------------------
        for subdir in ["course",
            "sections",
            "activities",
            "questions",
            "files"]:
            (self.work_dir / subdir).mkdir(exist_ok=True)

    print("Moodle migration activated.")