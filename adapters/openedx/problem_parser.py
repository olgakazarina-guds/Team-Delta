"""
Open edX Problem Parser - Parses problem XMLs into structured question dicts.

Extracts questions from Open edX problem XMLs supporting:
multiplechoiceresponse (multichoice, truefalse)
choiceresponse (single-select, multi-select)
stringresponse (shortanswer)
numericalresponse (numerical)
textinput / numericalinput (legacy custom markup)
formularesponse, coderesponse, customresponse (placeholders)
"""

import uuid

# XML generation and passthrough only; untrusted parsing goes through core.xml_utils.
import xml.etree.ElementTree as ET  # nosec B405
from typing import Any

from core.xml_utils import parse_xml_text


def parse_problem(problem_xml: str, problem_url_name: str) -> dict[str, Any]:
    """
    Parse an Open edX problem XML and return a structured dict with questions.

    Args:
        problem_xml: Raw XML string of the problem file
        problem_url_name: URL name of the problem (used as fallback title)

    Returns:
        Dictionary with structure:
        {
            "assessment_title": str,
            "questions": [
                {
                    "question_id": str (UUID),
                    "type": str (multichoice/truefalse/shortanswer/numerical/etc.),
                    "prompt": str,
                    "points": float,
                    "answer_options": [{"text": str, "is_correct": bool}, ...],
                    "correct_answers": [str, ...]  # for text/numerical inputs
                },
                ...
            ]
        }
    """
    root = parse_xml_text(problem_xml, source=f"problem:{problem_url_name}")
    display_name = root.attrib.get("display_name", f"Problem: {problem_url_name}")
    questions: list[dict[str, Any]] = []

    # 1. Multiple Choice / True-False - <multiplechoiceresponse>
    questions.extend(_parse_multiple_choice_responses(root))

    # 2. Multiple Choice (legacy) - <choiceresponse>
    questions.extend(_parse_choice_responses(root))

    # 3. Short Answer - <stringresponse>
    questions.extend(_parse_string_responses(root))

    # 4. Legacy custom short answer - <textinput>
    questions.extend(_parse_text_inputs(root))

    # 5. Numerical - <numericalresponse> / legacy <numericalinput>
    questions.extend(_parse_numerical_inputs(root))

    # 6. Formula, Code, Custom - placeholders
    questions.extend(_parse_formula_responses(root))
    questions.extend(_parse_code_responses(root))
    questions.extend(_parse_custom_responses(root))

    return {
        "assessment_title": display_name,
        "questions": questions,
    }


def _parse_multiple_choice_responses(root: ET.Element) -> list[dict[str, Any]]:
    """
    Parse <multiplechoiceresponse> elements (multichoice or truefalse).

    Detects true/false by checking if options are exactly "True" and "False".
    """
    questions = []
    for multiresp in root.findall(".//multiplechoiceresponse"):
        label_elem = multiresp.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""

        choicegroup = multiresp.find("choicegroup")
        if choicegroup is None:
            continue

        choices = choicegroup.findall("choice")
        answer_options: list[dict[str, Any]] = []
        for choice in choices:
            text = choice.text.strip() if choice.text else ""
            is_correct = choice.attrib.get("correct", "false").lower() == "true"
            answer_options.append({"text": text, "is_correct": is_correct})

        # Detect true/false: exactly 2 options with text "True" and "False"
        option_texts = {opt["text"].lower() for opt in answer_options}
        q_type = (
            "truefalse"
            if len(answer_options) == 2 and option_texts == {"true", "false"}
            else "multichoice"
        )

        questions.append(
            {
                "question_id": str(uuid.uuid4()),
                "type": q_type,
                "prompt": prompt,
                "points": 1.0,
                "answer_options": answer_options,
                "correct_answers": [opt["text"] for opt in answer_options if opt["is_correct"]],
            }
        )

    return questions


def _parse_choice_responses(root: ET.Element) -> list[dict[str, Any]]:
    """
    Parse legacy <choiceresponse> elements (single-select or multi-select).

    - <radiogroup> → single-select (radio buttons)
    - <checkboxgroup> → multi-select (checkboxes)
    """
    questions = []
    for choiceresponse in root.findall(".//choiceresponse"):
        checkboxgroup = choiceresponse.find("checkboxgroup")
        radiogroup = choiceresponse.find("radiogroup")

        if checkboxgroup is not None:
            q_type = "multiselect"
            choices = checkboxgroup.findall("choice")
        elif radiogroup is not None:
            q_type = "multichoice"
            choices = radiogroup.findall("choice")
        else:
            choices = []
            q_type = "unknown"

        # Extract prompt from label and description
        label_elem = choiceresponse.find("label")
        description_elem = choiceresponse.find("description")
        prompt = ""
        if label_elem is not None and label_elem.text:
            prompt = label_elem.text.strip()
        if description_elem is not None and description_elem.text:
            prompt += " " + description_elem.text.strip()

        answer_options = []
        for choice in choices:
            text = choice.text.strip() if choice.text else ""
            is_correct = choice.attrib.get("correct", "false").lower() == "true"
            answer_options.append({"text": text, "is_correct": is_correct})

        if answer_options:
            questions.append(
                {
                    "question_id": str(uuid.uuid4()),
                    "type": q_type,
                    "prompt": prompt,
                    "points": 1.0,
                    "answer_options": answer_options,
                    "correct_answers": [opt["text"] for opt in answer_options if opt["is_correct"]],
                }
            )

    return questions


def _parse_string_responses(root: ET.Element) -> list[dict[str, Any]]:
    """
    Parse standard <stringresponse> elements (text input questions).

    The primary answer is stored in the ``answer`` attribute; additional
    accepted answers use <additional_answer answer="..."/> children. Legacy
    files may instead list answers as <answer> children.
    """
    questions = []
    for stringresponse in root.findall(".//stringresponse"):
        label_elem = stringresponse.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""

        correct_answers = []
        primary = stringresponse.attrib.get("answer")
        if primary:
            correct_answers.append(primary.strip())
        for additional in stringresponse.findall("additional_answer"):
            answer = additional.attrib.get("answer")
            if answer:
                correct_answers.append(answer.strip())
        for ans in stringresponse.findall("answer"):
            if ans.text:
                correct_answers.append(ans.text.strip())

        points = float(stringresponse.attrib.get("points", 1.0))

        questions.append(
            {
                "question_id": str(uuid.uuid4()),
                "type": "shortanswer",
                "prompt": prompt,
                "points": points,
                "correct_answers": correct_answers,
                "answer_options": [],
            }
        )

    return questions


def _parse_text_inputs(root: ET.Element) -> list[dict[str, Any]]:
    """Parse legacy custom <textinput> elements (shortanswer questions)."""
    questions = []
    for textinput in root.findall(".//textinput"):
        label_elem = textinput.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""

        response = textinput.find("response")
        correct_answer = ""
        if response is not None:
            correct_answer = response.attrib.get("correct_answer", "")

        questions.append(
            {
                "question_id": str(uuid.uuid4()),
                "type": "shortanswer",
                "prompt": prompt,
                "points": 1.0,
                "correct_answers": [correct_answer] if correct_answer else [],
                "answer_options": [],
            }
        )

    return questions


def _parse_numerical_inputs(root: ET.Element) -> list[dict[str, Any]]:
    """Parse standard <numericalresponse> and legacy <numericalinput> elements."""
    questions = []
    elements = root.findall(".//numericalresponse") + root.findall(".//numericalinput")
    for element in elements:
        label_elem = element.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""

        correct_answer = element.attrib.get("answer", "")
        if not correct_answer:
            response = element.find("response")
            if response is not None:
                correct_answer = response.attrib.get("correct_answer", "")

        questions.append(
            {
                "question_id": str(uuid.uuid4()),
                "type": "numerical",
                "prompt": prompt,
                "points": 1.0,
                "correct_answer": correct_answer,
                "answer_options": [],
            }
        )

    return questions


def _parse_formula_responses(root: ET.Element) -> list[dict[str, Any]]:
    """Parse <formularesponse> elements (placeholder - not fully converted)."""
    questions = []
    for _ in root.findall(".//formularesponse"):
        questions.append(
            {
                "question_id": str(uuid.uuid4()),
                "type": "formula",
                "prompt": "Formula response (not fully converted)",
                "points": 1.0,
                "answer_options": [],
            }
        )
    return questions


def _parse_code_responses(root: ET.Element) -> list[dict[str, Any]]:
    """Parse <coderesponse> elements (placeholder - not fully converted)."""
    questions = []
    for _ in root.findall(".//coderesponse"):
        questions.append(
            {
                "question_id": str(uuid.uuid4()),
                "type": "code",
                "prompt": "Code response (not fully converted)",
                "points": 1.0,
                "answer_options": [],
            }
        )
    return questions


def _parse_custom_responses(root: ET.Element) -> list[dict[str, Any]]:
    """Parse <customresponse> elements (placeholder - not fully converted)."""
    questions = []
    for _ in root.findall(".//customresponse"):
        questions.append(
            {
                "question_id": str(uuid.uuid4()),
                "type": "custom",
                "prompt": "Custom response (not fully converted)",
                "points": 1.0,
                "answer_options": [],
            }
        )
    return questions
