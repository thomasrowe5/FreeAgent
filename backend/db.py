import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator, List, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Field, SQLModel


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/freeagent",
)


engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

async_session_factory = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
)


class Organization(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    plan: str = "free"
    stripe_customer_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    id: str = Field(primary_key=True)
    email: str
    org_id: str


class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    org_id: str
    name: str
    email: str
    message: str
    score: float = 0.0
    status: str = "new"  # new, proposal_sent, followup_pending, won, lost
    client_type: str = "general"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    value: float = 0.0  # closed revenue amount


class Proposal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int
    org_id: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str
    lead_id: Optional[int] = None
    org_id: Optional[str] = None
    status: str = "succeeded"
    cost: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GmailToken(SQLModel, table=True):
    user_id: str = Field(primary_key=True)
    org_id: Optional[str] = None
    access_token: str
    refresh_token: Optional[str] = None
    expiry: Optional[datetime] = None


class GmailThread(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    org_id: Optional[str] = None
    thread_id: str
    snippet: Optional[str] = None

    __table_args__ = (UniqueConstraint("user_id", "thread_id", name="uq_gmail_thread"),)


class AnalyticsSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    org_id: str
    total_leads: int = 0
    proposals_sent: int = 0
    followups_sent: int = 0
    wins: int = 0
    revenue: float = 0.0
    ts: datetime = Field(default_factory=datetime.utcnow)


class RunHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    org_id: Optional[str] = None
    lead_id: Optional[int] = None
    stage: str
    success: bool = True
    error_text: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Usage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: str
    action_type: str
    count: int = 0
    month: str

    __table_args__ = (UniqueConstraint("org_id", "action_type", "month", name="uq_usage"),)


class MemoryEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    org_id: Optional[str] = None
    key: str
    value: str
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    vector: Optional[List[float]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Feedback(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str
    org_id: Optional[str] = None
    lead_id: Optional[int] = None
    type: str
    comment: Optional[str] = None
    edited_text: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InviteToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)
    email: Optional[str] = None
    org_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    redeemed: bool = False


class AgentKPI(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_name: str = Field(index=True)
    org_id: Optional[str] = None
    total_runs: int = 0
    successes: int = 0
    total_tokens: int = 0
    avg_response_ms: float = 0.0
    acceptance_rate: float = 0.0
    roi: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
