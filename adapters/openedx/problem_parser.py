import xml.etree.ElementTree as ET
import uuid
from typing import Dict, Any, List, Optional

def parse_problem(problem_xml: str, problem_url_name: str) -> Dict[str, Any]:
    """
    Parse an Open edX problem XML and return a structured dict with:
    - assessment_title
    - questions list (each with type, prompt, points, answer_options, etc.)
    """
    root = ET.fromstring(problem_xml)
    
    # Get problem display name (if present)
    display_name = root.attrib.get("display_name", f"Problem: {problem_url_name}")
    
    questions = []
    
    # ============================================================
    # 1. Multiple Choice (Single and Multi-select)
    # ============================================================
    choiceresponse = root.find(".//choiceresponse")
    if choiceresponse is not None:
        # Determine if multi-select (checkboxgroup) or single-select (radiogroup)
        checkboxgroup = choiceresponse.find("checkboxgroup")
        radiogroup = choiceresponse.find("radiogroup")
        
        if checkboxgroup is not None:
            q_type = "multi-select"
            choices = checkboxgroup.findall("choice")
        elif radiogroup is not None:
            q_type = "single-select"
            choices = radiogroup.findall("choice")
        else:
            choices = []
            q_type = "unknown"
        
        # Extract prompt
        label_elem = choiceresponse.find("label")
        description_elem = choiceresponse.find("description")
        prompt = ""
        if label_elem is not None and label_elem.text:
            prompt = label_elem.text.strip()
        if description_elem is not None and description_elem.text:
            prompt += " " + description_elem.text.strip()
        
        # Build answer options
        answer_options = []
        for choice in choices:
            text = choice.text.strip() if choice.text else ""
            is_correct = choice.attrib.get("correct", "false").lower() == "true"
            # Extract hint if present
            hint_elem = choice.find("choicehint")
            hint = hint_elem.text.strip() if hint_elem is not None and hint_elem.text else None
            
            answer_options.append({
                "text": text,
                "is_correct": is_correct,
                "hint": hint
            })
        
        if answer_options:
            questions.append({
                "question_id": str(uuid.uuid4()),
                "type": q_type,
                "prompt": prompt,
                "points": 1.0,  # default, can be overridden by parent
                "answer_options": answer_options,
                "correct_answers": [opt["text"] for opt in answer_options if opt["is_correct"]]
            })
    
    # ============================================================
    # 2. Text Input (String Response)
    # ============================================================
    stringresponse = root.find(".//stringresponse")
    if stringresponse is not None:
        label_elem = stringresponse.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""
        
        # Get correct answer(s)
        correct_answers = []
        for ans in stringresponse.findall("answer"):
            if ans.text:
                correct_answers.append(ans.text.strip())
        
        # Get points
        points = float(stringresponse.attrib.get("points", 1.0))
        
        questions.append({
            "question_id": str(uuid.uuid4()),
            "type": "text_input",
            "prompt": prompt,
            "points": points,
            "correct_answers": correct_answers,
            "answer_options": []
        })
    
    # ============================================================
    # 3. Numerical Input
    # ============================================================
    numericalresponse = root.find(".//numericalresponse")
    if numericalresponse is not None:
        label_elem = numericalresponse.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""
        
        # Get correct answer
        correct_answer = None
        answer_elem = numericalresponse.find("answer")
        if answer_elem is not None and answer_elem.text:
            try:
                correct_answer = float(answer_elem.text.strip())
            except ValueError:
                correct_answer = answer_elem.text.strip()
        
        points = float(numericalresponse.attrib.get("points", 1.0))
        
        questions.append({
            "question_id": str(uuid.uuid4()),
            "type": "numerical",
            "prompt": prompt,
            "points": points,
            "correct_answer": correct_answer,
            "answer_options": []
        })
    
    # ============================================================
    # 4. Formula (Math Expression)
    # ============================================================
    formularesponse = root.find(".//formularesponse")
    if formularesponse is not None:
        label_elem = formularesponse.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""
        
        correct_answer = None
        answer_elem = formularesponse.find("answer")
        if answer_elem is not None and answer_elem.text:
            correct_answer = answer_elem.text.strip()
        
        points = float(formularesponse.attrib.get("points", 1.0))
        
        questions.append({
            "question_id": str(uuid.uuid4()),
            "type": "formula",
            "prompt": prompt,
            "points": points,
            "correct_answer": correct_answer,
            "answer_options": []
        })
    
    # ============================================================
    # 5. Custom Python (Code response)
    # ============================================================
    coderesponse = root.find(".//coderesponse")
    if coderesponse is not None:
        label_elem = coderesponse.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""
        
        # Usually has <codeparam> with initial code display
        codeparam = coderesponse.find("codeparam")
        initial_display = ""
        if codeparam is not None:
            initial_display_elem = codeparam.find("initial_display")
            if initial_display_elem is not None and initial_display_elem.text:
                initial_display = initial_display_elem.text.strip()
        
        points = float(coderesponse.attrib.get("points", 1.0))
        
        questions.append({
            "question_id": str(uuid.uuid4()),
            "type": "code",
            "prompt": prompt,
            "points": points,
            "initial_display": initial_display,
            "answer_options": []
        })
    
    # ============================================================
    # 6. Custom Response (Generic)
    # ============================================================
    customresponse = root.find(".//customresponse")
    if customresponse is not None:
        label_elem = customresponse.find("label")
        prompt = label_elem.text.strip() if label_elem is not None and label_elem.text else ""
        
        points = float(customresponse.attrib.get("points", 1.0))
        
        questions.append({
            "question_id": str(uuid.uuid4()),
            "type": "custom",
            "prompt": prompt,
            "points": points,
            "answer_options": []
        })
    
    return {
        "assessment_title": display_name,
        "questions": questions
    }
