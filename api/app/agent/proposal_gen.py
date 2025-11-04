# api/app/agent/proposal_gen.py
from datetime import date

def generate_proposal(llm, lead_data):
    prompt = f"""
    Draft a short service proposal for this lead:

    {lead_data}

    Include sections:
    - Overview
    - Scope (bulleted)
    - Timeline
    - Pricing (use ranges)
    - Next Steps
    """
    text = llm.invoke(prompt)
    return {
        "title": f"Proposal_{date.today()}",
        "content": text,
    }
