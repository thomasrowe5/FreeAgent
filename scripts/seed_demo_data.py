#!/usr/bin/env python
import asyncio
import random

from faker import Faker

from backend.agents.lead_scoring import score as score_lead
from backend.agents.proposal_gen import draft as draft_proposal
from backend.db import InviteToken, Lead, Proposal, Run, get_session, init_db

FAKE_USER_ID = "demo"


async def seed_lead(fake: Faker) -> None:
    name = fake.name()
    email = fake.email()
    message = fake.paragraph(nb_sentences=3)
    client_type = random.choice(["general", "enterprise", "startup", "nonprofit"])
    value = round(random.uniform(3000, 15000), 2)

    async with get_session() as session:
        lead = Lead(
            user_id=FAKE_USER_ID,
            name=name,
            email=email,
            message=message,
            score=0.0,
            value=value,
            client_type=client_type,
        )
        session.add(lead)
        await session.commit()
        await session.refresh(lead)

        # Lead scoring
        lead.score = score_lead(lead.name, lead.email, lead.message)
        session.add(lead)
        session.add(Run(kind="lead_scoring", lead_id=lead.id))

        # Proposal drafting
        content = draft_proposal(lead.name, lead.message)
        proposal = Proposal(lead_id=lead.id, content=content)
        lead.status = "proposal_sent"
        session.add(proposal)
        session.add(lead)
        session.add(Run(kind="proposal", lead_id=lead.id))

        await session.commit()


async def main(total: int = 20) -> None:
    await init_db()
    fake = Faker()
    for _ in range(total):
        await seed_lead(fake)
    # create five invite tokens for beta testers
    async with get_session() as session:
        for _ in range(5):
            invite = InviteToken(token=fake.uuid4(), email=fake.email())
            session.add(invite)
        await session.commit()
    print(f"Seeded {total} demo leads for user '{FAKE_USER_ID}'.")


if __name__ == "__main__":
    asyncio.run(main())
