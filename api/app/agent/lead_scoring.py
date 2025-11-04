# api/app/agent/lead_scoring.py
from typing import Dict

def score_lead(llm, email_text: str) -> Dict:
    """Ask the model to extract key signals and score fitness."""
    prompt = f"""
    Analyze the following inquiry and return JSON:
    {{
      "fit_score": 0-100,
      "summary": "<brief description>",
      "contact_email": "<email if found>"
    }}
    Text: {email_text}
    """
    resp = llm.invoke(prompt)
    return resp if isinstance(resp, dict) else {"fit_score": 0, "summary": str(resp)}
