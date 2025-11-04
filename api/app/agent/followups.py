# api/app/agent/followups.py
import asyncio

async def send_email(recipient: str, subject: str, body: str):
    # TODO: integrate Gmail API here
    print(f"Sending email to {recipient}: {subject}")

def schedule_followups(recipient: str):
    """Schedule polite nudges (48h, 5d)."""
    asyncio.create_task(send_email(recipient, "Follow-up", "Just checking in!"))
