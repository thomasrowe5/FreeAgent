from fastapi import FastAPI
from agent.core import FreeAgentCore

app = FastAPI(title="FreeAgent API")
agent = FreeAgentCore(llm_client=None)  # placeholder until OpenAI client connected

@app.post("/agent/process")
async def process_email(payload: dict):
    text = payload.get("email_text", "")
    return await agent.process_inbound(text)

