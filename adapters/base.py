from abc import ABC, abstractmethod
from typing import Dict, Any, List
from domain.entities import Course, RawFragment

class SourceAdapter(ABC):
    @abstractmethod
    def parse(self, source_path: str) -> Dict[str, Any]:
        """Extract raw structure and return a dict with parsed data and fragments."""
        pass

    @abstractmethod
    def to_canonical(self, parsed: Dict[str, Any]) -> Course:
        """Convert parsed dict to a canonical Course object."""
        pass

    @abstractmethod
    def get_raw_fragments(self, parsed: Dict[str, Any]) -> List[RawFragment]:
        """Return list of raw fragments extracted during parse."""
        pass

class TargetAdapter(ABC):
    @abstractmethod
    def prepare_import(self, course: Course) -> dict:
        pass

    @abstractmethod
    def load(self, prepared: dict, target_credentials: dict) -> str:
        pass
