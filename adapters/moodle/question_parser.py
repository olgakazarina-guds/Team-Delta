"""
Moodle Question Parser – Reads questions.xml and creates canonical assessment dicts.

Parses Moodle's question bank XML format and extracts questions with their
answer options, converting them into a structure that TransformService can
use to create Question and AnswerOption domain entities.

Supports question types: multichoice, truefalse, shortanswer, numerical,
essay, description.
"""

import xml.etree.ElementTree as ET
import uuid
from typing import Any, Dict, List

from core.xml_utils import parse_xml_file


def parse_questions(questions_xml_path: str) -> List[Dict[str, Any]]:
    """Parse Moodle questions.xml and return one assessment dict per question."""
    root = parse_xml_file(questions_xml_path)
    assessments = []

    for q_elem in root.findall(".//question"):
        q_id = q_elem.get("id")
        if not q_id:
            continue

        qtype_elem = q_elem.find("qtype")
        q_type = (qtype_elem.text or "unknown").strip() if qtype_elem is not None else "unknown"

        name = q_elem.findtext("name", "").strip()
        questiontext_elem = q_elem.find("questiontext")
        questiontext = (
            "".join(questiontext_elem.itertext()).strip()
            if questiontext_elem is not None
            else ""
        )

        defaultmark_elem = q_elem.find("defaultmark")
        try:
            points = float(defaultmark_elem.text) if defaultmark_elem is not None else 1.0
        except (TypeError, ValueError):
            points = 1.0

        answer_options: List[Dict[str, Any]] = []
        correct_answers: List[str] = []
        metadata: Dict[str, Any] = {}
        canonical_type = q_type

        if q_type == "multichoice":
            plugin = q_elem.find("plugin_qtype_multichoice_question")
            single = True
            if plugin is not None:
                single_elem = plugin.findtext("multichoice/single", "1")
                single = single_elem.strip() != "0"
                for ans in plugin.findall(".//answer"):
                    text = _answer_text(ans)
                    fraction = _fraction(ans)
                    if not text:
                        continue
                    answer_options.append({
                        "text": text,
                        "is_correct": fraction > 0,
                    })
                    if fraction > 0:
                        correct_answers.append(text)
            canonical_type = "multichoice" if single else "multiselect"

        elif q_type == "truefalse":
            plugin = q_elem.find("plugin_qtype_truefalse_question")
            if plugin is not None:
                for ans in plugin.findall(".//answer"):
                    text = _answer_text(ans)
                    if not text:
                        continue
                    is_correct = _fraction(ans) > 0
                    answer_options.append({
                        "text": text,
                        "is_correct": is_correct,
                    })
                    if is_correct:
                        correct_answers.append(text)

        elif q_type == "shortanswer":
            plugin = q_elem.find("plugin_qtype_shortanswer_question")
            if plugin is not None:
                for ans in plugin.findall(".//answer"):
                    text = _answer_text(ans)
                    if not text:
                        continue
                    fraction = _fraction(ans)
                    answer_options.append({
                        "text": text,
                        "is_correct": fraction > 0,
                    })
                    if fraction > 0:
                        correct_answers.append(text)

        elif q_type == "numerical":
            plugin = q_elem.find("plugin_qtype_numerical_question")
            if plugin is not None:
                for ans in plugin.findall(".//answer"):
                    text = _answer_text(ans)
                    if not text:
                        continue
                    fraction = _fraction(ans)
                    answer_options.append({
                        "text": text,
                        "is_correct": fraction > 0,
                    })
                    if fraction > 0:
                        correct_answers.append(text)
                        metadata.setdefault("correct_answer", text)
                    tolerance = ans.findtext("tolerance")
                    if tolerance is not None:
                        metadata["tolerance"] = tolerance

        elif q_type in ("essay", "description"):
            metadata["requires_manual_review"] = True

        question = {
            "question_id": str(uuid.uuid4()),
            "original_moodle_id": q_id,
            "question_type": canonical_type,
            "prompt_text": questiontext,
            "points": points,
            "answer_options": answer_options,
            "correct_answers": correct_answers,
            "metadata": metadata,
        }

        assessment_id = str(uuid.uuid4())
        assessments.append({
            "assessment_id": assessment_id,
            "title": name if name else f"Question {q_id}",
            "assessment_type": "quiz",
            "questions": [question],
            "original_question_ids": [q_id],
        })

    return assessments


def _answer_text(answer: ET.Element) -> str:
    elem = answer.find("answertext")
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _fraction(answer: ET.Element) -> float:
    elem = answer.find("fraction")
    if elem is None or elem.text is None:
        return 0.0
    try:
        return float(elem.text)
    except ValueError:
        return 0.0
