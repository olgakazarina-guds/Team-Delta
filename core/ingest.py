from pathlib import Path
import uuid
from typing import Dict, Any
from core.parse import ParseService
from core.transform import TransformService
from core.validate import ValidationService

class IngestService:
    def __init__(self):
        self.parse_service = ParseService()
        self.transform_service = TransformService()
        self.validation_service = ValidationService()

    def inspect(self, source_path: str, source_type: str = "openedx", work_dir: str = "data/extracted") -> Dict[str, Any]:
        # Generate job ID
        job_id = str(uuid.uuid4())
        # Parse source
        parsed = self.parse_service.parse(source_path, source_type, work_dir)
        # Transform to canonical course
        course = self.transform_service.transform(parsed, source_type, job_id)
        # Validate and generate report
        report = self.validation_service.validate(course)
        return {
            "job_id": job_id,
            "course": course,
            "report": report,
            "raw_fragments_count": len(parsed.get("raw_fragments", [])),
            "extracted_path": parsed.get("extracted_path"),
        }
