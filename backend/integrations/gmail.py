import asyncio
import base64
import os
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.db import GmailToken, get_session

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _client_config() -> Dict[str, Any]:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError("Google OAuth configuration missing")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def _build_flow(state: Optional[str] = None) -> Flow:
    config = _client_config()
    client_config = {
        "web": {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uris": [config["redirect_uri"]],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, state=state)
    flow.redirect_uri = config["redirect_uri"]
    return flow


def get_authorize_url(state: Optional[str] = None) -> str:
    flow = _build_flow(state)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return authorization_url


def exchange_code_for_token(code: str) -> Dict[str, Any]:
    flow = _build_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials
    expiry = None
    if credentials.expiry:
        expiry = credentials.expiry.astimezone(timezone.utc).replace(tzinfo=None)
    return {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "expiry": expiry,
    }


async def _get_credentials(user_id: str) -> Credentials:
    config = _client_config()
    async with get_session() as session:
        token = await session.get(GmailToken, user_id)
        if not token:
            raise RuntimeError("No Gmail credentials stored for user")

        creds = Credentials(
            token=token.access_token,
            refresh_token=token.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            scopes=SCOPES,
        )
        if token.expiry:
            creds.expiry = token.expiry.replace(tzinfo=timezone.utc)

        if creds.expired and creds.refresh_token:
            await asyncio.to_thread(creds.refresh, Request())
            token.access_token = creds.token
            if creds.refresh_token:
                token.refresh_token = creds.refresh_token
            if creds.expiry:
                token.expiry = creds.expiry.astimezone(timezone.utc).replace(tzinfo=None)
            session.add(token)
            await session.commit()

        return creds


def _decode_base64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _extract_body(payload: Dict[str, Any]) -> str:
    if not payload:
        return ""
    body = payload.get("body", {})
    data = body.get("data")
    if data:
        return _decode_base64(data).decode("utf-8", errors="ignore")
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain":
            part_body = part.get("body", {}).get("data")
            if part_body:
                return _decode_base64(part_body).decode("utf-8", errors="ignore")
    return ""


def _parse_headers(headers: List[Dict[str, Any]]) -> Dict[str, str]:
    parsed = {}
    for header in headers or []:
        name = header.get("name", "").lower()
        value = header.get("value", "")
        parsed[name] = value
    return parsed


async def list_inbox_threads(user_id: str, label: str = "INBOX", max: int = 10) -> List[Dict[str, Any]]:
    credentials = await _get_credentials(user_id)

    def _list():
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        try:
            response = (
                service.users()
                .threads()
                .list(userId="me", labelIds=[label], maxResults=max)
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"Gmail list failed: {exc}") from exc

        threads = []
        for thread_meta in response.get("threads", []):
            thread_id = thread_meta.get("id")
            if not thread_id:
                continue
            try:
                thread = (
                    service.users()
                    .threads()
                    .get(userId="me", id=thread_id, format="full")
                    .execute()
                )
            except HttpError:
                continue

            messages = thread.get("messages", [])
            if not messages:
                continue
            message = messages[0]
            payload = message.get("payload", {})
            headers = _parse_headers(payload.get("headers", []))
            from_header = headers.get("from", "")
            subject = headers.get("subject", "")
            _, from_email = parseaddr(from_header)
            from_name = parseaddr(from_header)[0]
            body_text = _extract_body(payload) or thread.get("snippet", "")

            threads.append(
                {
                    "id": thread_id,
                    "snippet": thread.get("snippet", ""),
                    "subject": subject,
                    "from_name": from_name,
                    "from_email": from_email,
                    "message": body_text,
                }
            )
        return threads

    return await asyncio.to_thread(_list)


async def send_email(user_id: str, to: str, subject: str, body: str) -> Dict[str, Any]:
    credentials = await _get_credentials(user_id)

    def _send():
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        try:
            result = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(f"Gmail send failed: {exc}") from exc
        return result

    return await asyncio.to_thread(_send)
