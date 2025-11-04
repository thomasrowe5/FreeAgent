from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class LeadIn(BaseModel):
    name: str
    email: EmailStr
    message: str
    value: Optional[float] = None
    client_type: Optional[str] = None


class LeadOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    message: str
    score: float
    status: str
    value: float
    client_type: str
    created_at: datetime


class ProposalIn(BaseModel):
    lead_id: int


class ProposalOut(BaseModel):
    id: int
    lead_id: int
    content: str
    created_at: datetime


class FollowupIn(BaseModel):
    lead_id: int
    days_after: int = 3


class GmailCallbackIn(BaseModel):
    code: str


class GmailSendIn(BaseModel):
    to: EmailStr
    subject: str
    body: str


class AgentRun(BaseModel):
    id: int
    kind: str  # "lead_scoring" | "proposal" | "followup"
    lead_id: Optional[int] = None
    status: str  # "queued" | "running" | "succeeded" | "failed"
    cost: float = 0.0
    created_at: datetime


class FeedbackIn(BaseModel):
    lead_id: Optional[int]
    type: str
    comment: Optional[str] = None
    edited_text: Optional[str] = None


class InviteIn(BaseModel):
    email: Optional[EmailStr] = None
