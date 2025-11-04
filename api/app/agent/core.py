# api/app/agent/core.py
from .lead_scoring import score_lead
from .proposal_gen import generate_proposal
from .followups import schedule_followups

class FreeAgentCore:
    """Coordinates agent tasks."""

    def __init__(self, llm_client):
        self.llm = llm_client

    async def process_inbound(self, email_text: str) -> dict:
        """Main entrypoint when a new email arrives."""
        lead_data = score_lead(self.llm, email_text)
        if lead_data["fit_score"] >= 70:
            proposal = generate_proposal(self.llm, lead_data)
            schedule_followups(lead_data["contact_email"])
            return {"status": "qualified", "proposal": proposal}
        return {"status": "nurture", "summary": lead_data["summary"]}
