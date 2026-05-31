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

    # -------------------------------------------------------------------------
    # Step 2: Extract each question and build assessment dicts
    # -------------------------------------------------------------------------
    for q_elem in root.findall(".//question"):
        q_id = q_elem.get("id")
        
        # Get question type with fallback to "unknown" if missing
        q_type = q_elem.get("type")
        if not q_type:
            q_type = "unknown"
        
        # Parse question name
        name_elem = q_elem.find("name")
        name = name_elem.findtext("text", "") if name_elem is not None else ""
        
        # Parse question text (the actual prompt)
        questiontext_elem = q_elem.find("questiontext")
        questiontext = ""
        if questiontext_elem is not None:
            text_elem = questiontext_elem.find("text")
            if text_elem is not None and text_elem.text:
                questiontext = text_elem.text
        
        # Parse point value (defaultgrade)
        defaultgrade = float(q_elem.findtext("defaultgrade", "1"))

        # Build base question dict
        question = {
            "question_id": str(uuid.uuid4()),
            "original_moodle_id": q_id,
            "question_type": q_type,  # Now guaranteed to be a string
            "prompt_text": questiontext,
            "points": defaultgrade,
            "answer_options": [],
            "correct_answers": [],
        }

        # -------------------------------------------------------------------------
        # Step 3: Parse answer options based on question type
        # -------------------------------------------------------------------------
        if q_type in ("multichoice", "truefalse"):
            # Multiple choice: single correct answer (or multiple if single="0")
            single = q_elem.findtext("single", "1") == "1"
            for ans in q_elem.findall(".//answer"):
                text_elem = ans.find("text")
                text = text_elem.text if text_elem is not None else ""
                fraction = float(ans.get("fraction", "0"))
                is_correct = fraction > 0
                question["answer_options"].append({
                    "text": text,
                    "is_correct": is_correct,
                })
                
        elif q_type == "shortanswer":
            # Short answer: case-sensitive text answers
            for ans in q_elem.findall(".//answer"):
                text_elem = ans.find("text")
                text = text_elem.text if text_elem is not None else ""
                fraction = float(ans.get("fraction", "0"))
                if fraction > 0:
                    question["correct_answers"].append(text)
                    
        elif q_type == "numerical":
            # Numerical: numeric answer with optional tolerance
            for ans in q_elem.findall(".//answer"):
                text_elem = ans.find("text")
                text = text_elem.text if text_elem is not None else ""
                fraction = float(ans.get("fraction", "0"))
                if fraction > 0:
                    try:
                        question["correct_answer"] = float(text)
                    except ValueError:
                        question["correct_answer"] = text
                        
        elif q_type in ("essay", "description"):
            # Essay/description: no answer options, just store prompt
            pass
        
        # -------------------------------------------------------------------------
        # Step 4: Wrap question in assessment dict
        # -------------------------------------------------------------------------
        assessment_id = str(uuid.uuid4())
        assessments.append({
            "assessment_id": assessment_id,
            "title": name if name else f"Question {q_id}",
            "assessment_type": "quiz",
            "questions": [question],
            "raw_fragment_id": None,
            "original_question_ids": [q_id],  # for linking to quiz instances
        })

    return assessments
