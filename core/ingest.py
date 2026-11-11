import uuid
from pathlib import Path
from typing import Any, Dict

from core.parse import ParseService
from core.transform import TransformService
from core.validate import ValidationService
from persistence.repositories import save_job


class IngestService:
    def __init__(self):
        self.parse_service = ParseService()
        self.transform_service = TransformService()
        self.validation_service = ValidationService()

    def inspect(
        self,
        source_path: str,
        source_type: str = "openedx",
        work_dir: str = "data/extracted",
    ) -> Dict[str, Any]:
        """Parse, transform, validate, and persist a source course."""
        job_id = str(uuid.uuid4())
        extract_dir = Path(work_dir) / job_id
        extract_dir.mkdir(parents=True, exist_ok=True)
        parsed = self.parse_service.parse(source_path, source_type, str(extract_dir))
        if parsed is None:
            raise ValueError(
                f"Parse service returned None for {source_type} course. Check logs."
            )

        course = self.transform_service.transform(parsed, source_type, job_id)
        report = self.validation_service.validate(course)
        save_job(
            job_id,
            source_type,
            "",
            course,
            report,
            parsed.get("extracted_path"),
        )

        return {
            "job_id": job_id,
            "course": course,
            "report": report,
            "raw_fragments_count": len(parsed.get("raw_fragments", [])),
            "extracted_path": parsed.get("extracted_path"),
            "parsed": parsed,
        }
