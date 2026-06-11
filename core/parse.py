import logging

from adapters.moodle import MoodleCourseParser
from adapters.openedx.course_parser import OpenEdxCourseParser

logger = logging.getLogger(__name__)

class ParseService:
    def parse(self, source_path: str, source_type: str, work_dir: str) -> dict:
        """
        Dispatch to the appropriate source adapter and return its raw parsed dict.

        source_type must be one of 'openedx' or 'moodle'.
        work_dir is the scratch directory used for archive extraction.
        The returned dict is passed directly to TransformService.transform().
        """
        logger.info("Parsing %s source: %s", source_type, source_path)
        logger.debug("Extraction work_dir=%s", work_dir)
        if source_type == "openedx":
            parser = OpenEdxCourseParser()
            result = parser.parse(source_path, work_dir)
        elif source_type == "moodle":
            parser = MoodleCourseParser()
            result = parser.parse(source_path, work_dir)
        else:
            logger.error("Unsupported source type: %s", source_type)
            raise ValueError(f"Unsupported source type: {source_type}")

        logger.debug(  "Parsed %d raw fragments from %s",len(result.get("raw_fragments", [])), source_path,)
