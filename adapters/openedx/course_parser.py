"""
Open edX Course Parser - Reads Open edX package XMLs and extracts course structure.

Parses Open edX .tar.gz course packages and extracts the hierarchical structure:
course → chapters → sequentials → verticals → components (html, video, problem, etc.)
Stores raw XML fragments for later domain entity mapping.
"""

import logging
import mimetypes

# XML generation and passthrough only; untrusted parsing goes through core.xml_utils.
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path
from typing import Any

from core.archive_utils import resolve_under
from core.errors import SecurityError, UnsafePathError
from core.identity import sha256_bytes, stable_id
from core.xml_utils import parse_xml_file

from .package_reader import OpenEdxPackageReader

logger = logging.getLogger(__name__)


class OpenEdxCourseParser:
    """
    Parses Open edX course packages into a canonical dictionary structure.

    This parser:
    Extracts Open edX .tar.gz packages
    Parses course.xml and nested component XMLs
    Stores raw XML fragments for auditing/reconstruction
    Extracts HTML content, video metadata, and openassessment prompts
    Returns a structured dict with course metadata and hierarchy
    """

    def __init__(self):
        self.reader = OpenEdxPackageReader()
        self.fragments: list[dict[str, Any]] = []
        self._course_key = ""

    def parse(self, archive_path: str, work_dir: str) -> dict[str, Any]:
        """Extract an Open edX export and return its structured course data."""
        self.fragments = []
        self._course_key = ""
        extracted_root = self.reader.extract(archive_path, work_dir)

        root_course_xml = extracted_root / "course.xml"
        if root_course_xml.exists():
            root = parse_xml_file(root_course_xml)
            url_name = root.attrib.get("url_name")
            org = root.attrib.get("org", "")
            course_code = root.attrib.get("course", "")
            if not url_name:
                raise ValueError("course.xml missing url_name attribute")
            actual_course_xml = self._xml_path(
                extracted_root, "course", url_name, label="course url_name"
            )
        else:
            actual_course_xml = self.reader.get_course_xml_path(extracted_root)
            root = parse_xml_file(actual_course_xml)
            url_name = root.attrib.get("url_name") or actual_course_xml.stem
            org = root.attrib.get("org", "")
            course_code = root.attrib.get("course", "")

        if not actual_course_xml.exists():
            raise FileNotFoundError(f"Course definition not found: {actual_course_xml}")

        root = parse_xml_file(actual_course_xml)
        course_title = root.attrib.get("display_name", "Unnamed Course")
        self._course_key = f"{org or 'org'}:{course_code or 'course'}:{url_name}"

        self._store_fragment(actual_course_xml, extracted_root)
        chapters = self._parse_chapters(root, extracted_root)

        return {
            "course_title": course_title,
            "course_key": self._course_key,
            "course_url_name": url_name,
            "org": org,
            "course_code": course_code,
            "chapters": chapters,
            "assets": self._parse_assets(extracted_root),
            "raw_fragments": self.fragments,
            "extracted_path": str(extracted_root),
        }

    def _parse_assets(self, extracted_root: Path) -> list[dict[str, Any]]:
        """Discover files in the export's static/ directory."""
        static_root = extracted_root / "static"
        if not static_root.is_dir():
            return []

        assets = []
        for file_path in sorted(static_root.rglob("*")):
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(extracted_root).as_posix()
            mime_type, _ = mimetypes.guess_type(file_path.name)
            is_video = bool(mime_type and mime_type.startswith("video/"))
            checksum = _sha256_file(file_path)
            assets.append(
                {
                    "asset_id": stable_id(
                        "asset", "openedx", self._course_key, relative_path, checksum
                    ),
                    "path": relative_path,
                    "original_filename": file_path.name,
                    "mime_type": mime_type,
                    "checksum": checksum,
                    "is_video": is_video,
                    "is_scorm": file_path.suffix.lower() == ".zip",
                }
            )
        return assets

    def _store_fragment(self, file_path: Path, extracted_root: Path) -> str:
        """Read an XML file, store it as a raw fragment, and return its ID."""
        raw_xml = file_path.read_text(encoding="utf-8")
        relative_path = file_path.relative_to(extracted_root).as_posix()
        fragment_id = stable_id("fragment", "openedx", relative_path)
        self.fragments.append(
            {
                "fragment_id": fragment_id,
                "kind": "xml",
                "source_location": {
                    "source_system": "openedx",
                    "package_path": relative_path,
                    "file_path": str(file_path),
                },
                "raw_text": raw_xml,
                "checksum": sha256_bytes(raw_xml.encode("utf-8")),
            }
        )
        return fragment_id

    def _xml_path(self, extracted_root: Path, folder: str, url_name: str, *, label: str) -> Path:
        """Resolve a package XML reference without allowing path traversal."""
        if not url_name or "/" in url_name or "\\" in url_name or url_name in {".", ".."}:
            raise UnsafePathError(f"Invalid {label}: {url_name!r}")
        return resolve_under(extracted_root / folder, f"{url_name}.xml")

    def _parse_chapters(self, root: ET.Element, extracted_root: Path) -> list[dict[str, Any]]:
        """Parse all <chapter> elements from the course file."""
        chapters = []
        for chapter_elem in root.findall("chapter"):
            chapter_url = chapter_elem.attrib.get("url_name")
            if not chapter_url:
                continue

            chapter_file = self._xml_path(
                extracted_root, "chapter", chapter_url, label="chapter url_name"
            )
            if not chapter_file.exists():
                logger.warning("Chapter XML not found: %s", chapter_file)
                continue

            chapters.append(self._parse_chapter(chapter_file, extracted_root))
        return chapters

    def _parse_chapter(self, chapter_file: Path, extracted_root: Path) -> dict[str, Any]:
        """Parse a single chapter XML file."""
        root = parse_xml_file(chapter_file)
        title = root.attrib.get("display_name", "Untitled Chapter")
        fragment_id = self._store_fragment(chapter_file, extracted_root)

        sequentials = []
        for seq_elem in root.findall("sequential"):
            seq_url = seq_elem.attrib.get("url_name")
            if not seq_url:
                continue

            seq_file = self._xml_path(
                extracted_root, "sequential", seq_url, label="sequential url_name"
            )
            if not seq_file.exists():
                logger.warning("Sequential XML not found: %s", seq_file)
                continue

            sequentials.append(self._parse_sequential(seq_file, extracted_root))

        return {
            "title": title,
            "url_name": chapter_file.stem,
            "raw_fragment_id": fragment_id,
            "sequentials": sequentials,
        }

    def _parse_sequential(self, seq_file: Path, extracted_root: Path) -> dict[str, Any]:
        """Parse a single sequential XML file."""
        root = parse_xml_file(seq_file)
        title = root.attrib.get("display_name", "Untitled Sequential")
        fragment_id = self._store_fragment(seq_file, extracted_root)

        verticals = []
        for vert_elem in root.findall("vertical"):
            vert_url = vert_elem.attrib.get("url_name")
            if not vert_url:
                continue

            vert_file = self._xml_path(
                extracted_root, "vertical", vert_url, label="vertical url_name"
            )
            if not vert_file.exists():
                logger.warning("Vertical XML not found: %s", vert_file)
                continue

            verticals.append(self._parse_vertical(vert_file, extracted_root))

        return {
            "title": title,
            "url_name": seq_file.stem,
            "raw_fragment_id": fragment_id,
            "verticals": verticals,
        }

    def _parse_vertical(self, vert_file: Path, extracted_root: Path) -> dict[str, Any]:
        """Parse a vertical and all of its components."""
        root = parse_xml_file(vert_file)
        title = root.attrib.get("display_name", "Untitled Vertical")
        fragment_id = self._store_fragment(vert_file, extracted_root)

        return {
            "title": title,
            "url_name": vert_file.stem,
            "raw_fragment_id": fragment_id,
            "components": self._parse_components(root, extracted_root),
        }

    def _parse_components(self, root: ET.Element, extracted_root: Path) -> list[dict[str, Any]]:
        """Parse all component elements within a vertical."""
        components = []
        for comp in root:
            comp_tag = comp.tag
            comp_url = comp.attrib.get("url_name", "")
            comp_title = comp.attrib.get("display_name", "")
            comp_raw_fragment_id = None
            content_html = None
            metadata: dict[str, Any] = {}

            comp_file = self._find_component_file(comp_tag, comp_url, extracted_root)
            if comp_file and comp_file.exists():
                comp_raw_fragment_id = self._store_fragment(comp_file, extracted_root)
                wrapper_root = self._read_wrapper(comp_file)
                if wrapper_root is not None:
                    wrapper_title = wrapper_root.attrib.get("display_name", "")
                    if wrapper_title:
                        comp_title = wrapper_title

                if comp_tag == "html":
                    content_html = self._extract_html_content(comp_file, extracted_root)
                elif comp_tag == "video":
                    metadata = self._extract_video_metadata(wrapper_root)
                elif comp_tag in ("scorm", "scormxblock"):
                    if wrapper_root is not None:
                        scorm_file = wrapper_root.attrib.get("scorm_file", "")
                        metadata = {
                            "asset_path": self._static_asset_path(scorm_file),
                            "scorm_settings": {
                                "version": wrapper_root.attrib.get("version_scorm", ""),
                                "maxgrade": wrapper_root.attrib.get("weight", ""),
                            },
                        }
                elif comp_tag == "openassessment":
                    prompt = self._extract_openassessment_prompt(wrapper_root, comp)
                    if prompt:
                        content_html = prompt
                elif comp_tag == "discussion" and wrapper_root is not None:
                    description = wrapper_root.findtext("description", "")
                    if description:
                        content_html = description
            elif comp_tag == "openassessment":
                prompt = self._extract_openassessment_prompt(None, comp)
                if prompt:
                    content_html = prompt

            if comp_tag == "openassessment":
                metadata["inline_xml"] = ET.tostring(comp, encoding="unicode")

            components.append(
                {
                    "type": comp_tag,
                    "title": comp_title,
                    "url_name": comp_url,
                    "raw_fragment_id": comp_raw_fragment_id,
                    "inline_xml": metadata.pop("inline_xml", None),
                    "content_html": content_html,
                    "metadata": metadata,
                }
            )

        return components

    def _find_component_file(
        self, comp_tag: str, comp_url: str, extracted_root: Path
    ) -> Path | None:
        """Locate a component XML file based on its tag and url_name."""
        supported = {
            "html",
            "video",
            "problem",
            "openassessment",
            "discussion",
            "lti",
            "scorm",
            "scormxblock",
        }
        if comp_tag not in supported or not comp_url:
            return None
        return self._xml_path(extracted_root, comp_tag, comp_url, label=f"{comp_tag} url_name")

    def _read_wrapper(self, comp_file: Path) -> ET.Element | None:
        try:
            return parse_xml_file(comp_file)
        except SecurityError:
            raise
        except (OSError, ET.ParseError, UnicodeError):
            logger.warning("Could not parse component wrapper: %s", comp_file)
            return None

    def _extract_html_content(self, comp_file: Path, extracted_root: Path) -> str | None:
        """Extract the actual HTML from an html component wrapper."""
        try:
            wrapper_root = parse_xml_file(comp_file)
            html_filename = wrapper_root.get("filename")
            if not html_filename:
                return None

            html_path = resolve_under(extracted_root / "html", html_filename)
            if not html_path.exists():
                logger.warning("HTML payload not found: %s", html_path)
                return None
            return html_path.read_text(encoding="utf-8")
        except SecurityError:
            raise
        except (OSError, ET.ParseError, UnicodeError):
            logger.warning("Could not read HTML component: %s", comp_file)
            return None

    def _extract_video_metadata(self, wrapper_root: ET.Element | None) -> dict[str, Any]:
        if wrapper_root is None:
            return {}

        youtube_id = (
            wrapper_root.attrib.get("youtube_id_1_0") or wrapper_root.attrib.get("youtube_id") or ""
        )
        if not youtube_id:
            youtube_attr = wrapper_root.attrib.get("youtube", "")
            if youtube_attr:
                youtube_id = youtube_attr.split(":", 1)[-1]

        if not youtube_id:
            source = wrapper_root.find("source")
            if source is not None:
                youtube_id = source.attrib.get("youtube_id_1_0", "")

        if youtube_id:
            return {
                "activity_type": "youtube",
                "youtube_id": youtube_id,
                "externalurl": f"https://www.youtube.com/watch?v={youtube_id}",
            }

        source = wrapper_root.find("source")
        if source is not None and source.attrib.get("src"):
            src = source.attrib["src"]
            return {
                "activity_type": "video",
                "video_url": src,
                "asset_path": self._static_asset_path(src),
            }

        return {"activity_type": "video"}

    def _static_asset_path(self, url: str) -> str:
        """Convert a static URL into a path relative to the extracted export."""
        clean = url.lstrip("/")
        if clean.startswith("static/"):
            return clean
        return f"static/{clean}" if clean else ""

    def _extract_openassessment_prompt(
        self, wrapper_root: ET.Element | None, inline_element: ET.Element
    ) -> str | None:
        root = wrapper_root if wrapper_root is not None else inline_element
        prompts = []
        for prompt in root.findall(".//prompt"):
            text = "".join(prompt.itertext()).strip()
            if text:
                prompts.append(text)
        if not prompts:
            for description in root.findall(".//description"):
                text = "".join(description.itertext()).strip()
                if text:
                    prompts.append(text)
        return "\n".join(prompts) if prompts else None


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it entirely into memory."""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
