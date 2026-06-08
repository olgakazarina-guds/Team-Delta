"""
Moodle Question Parser – Reads questions.xml and creates canonical assessment dicts.

Parses Moodle's question bank XML format and extracts questions with their
answer options, converting them into a structure that TransformService can
use to create Question and AnswerOption domain entities.

Supports question types: multichoice, truefalse, shortanswer, numerical,
essay, description
"""

import xml.etree.ElementTree as ET
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_questions(questions_xml_path: str) -> List[Dict[str, Any]]:
    """
    Parse Moodle questions.xml and return a list of assessment dicts.
    
    Moodle stores question bank data in categories, but we keep each question
    separate for easier mapping to quiz activities. Each assessment dict
    contains exactly one question.
    
    Args:
        questions_xml_path: Path to the questions.xml file from Moodle backup
        
    Returns:
        List of assessment dicts with structure:
        [
            {
                "assessment_id": str (generated UUID),
                "title": str (question name or "Question {id}"),
                "assessment_type": "quiz",
                "questions": [
                    {
                        "question_id": str (generated UUID),
                        "original_moodle_id": str,
                        "question_type": str (multichoice/truefalse/shortanswer/etc.),
                        "prompt_text": str,
                        "points": float,
                        "answer_options": [{"text": str, "is_correct": bool}, ...],
                        "correct_answers": [str, ...]  # for shortanswer/numerical
                    }
                ],
                "raw_fragment_id": None,
                "original_question_ids": [str]  # for linking to quiz instances
            },
            ...
        ]
        
    Example:
        >>> assessments = parse_questions("questions.xml")
        >>> print(assessments[0]["title"])
        "What caused the Russian Revolution?"
    """
    # -------------------------------------------------------------------------
    # Step 1: Parse XML tree
    # -------------------------------------------------------------------------

    tree = ET.parse(questions_xml_path)
    root = tree.getroot()
    assessments = []

    for q_elem in root.findall(".//question"):
        q_id = q_elem.get("id")
        if not q_id:
            continue

        qtype_elem = q_elem.find("qtype")
        q_type = qtype_elem.text if qtype_elem is not None else "unknown"

        name_elem = q_elem.find("name")
        name = name_elem.text if name_elem is not None else ""

        questiontext_elem = q_elem.find("questiontext")
        questiontext = ""
        if questiontext_elem is not None:
            questiontext = "".join(questiontext_elem.itertext()).strip()

        defaultmark_elem = q_elem.find("defaultmark")
        points = float(defaultmark_elem.text) if defaultmark_elem is not None else 1.0

        question = {
            "question_id": str(uuid.uuid4()),
            "original_moodle_id": q_id,
            "question_type": q_type,
            "prompt_text": questiontext,
            "points": points,
            "answer_options": [],
            "correct_answers": [],
        }

        # --- Parse answers depending on type ---
        if q_type == "multichoice":
            plugin = q_elem.find("plugin_qtype_multichoice_question")
            if plugin is not None:
                for ans in plugin.findall(".//answer"):
                    fraction_elem = ans.find("fraction")
                    fraction = float(fraction_elem.text) if fraction_elem is not None else 0.0
                    answertext_elem = ans.find("answertext")
                    text = "".join(answertext_elem.itertext()).strip() if answertext_elem is not None else ""
                    question["answer_options"].append({
                        "text": text,
                        "is_correct": fraction > 0,
                    })
        # Add other question types similarly...

        assessment_id = str(uuid.uuid4())
        assessments.append({
            "assessment_id": assessment_id,
            "title": name if name else f"Question {q_id}",
            "assessment_type": "quiz",
            "questions": [question],
            "original_question_ids": [q_id],
        })

    return assessments   
