"""Branding and marketing routes handling assets, PDFs, and tone training."""

import asyncio
import base64
import json
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

BRANDING_DIR = Path("data/branding")
EMAIL_TEMPLATE_DIR = Path("data/email_templates")
BRANDING_DIR.mkdir(parents=True, exist_ok=True)
EMAIL_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/branding", tags=["branding"])


class ProposalSection(BaseModel):
    title: str
    body: str


class ProposalPDFPayload(BaseModel):
    user_id: str = Field(..., description="User requesting the PDF")
    proposal_title: str = Field(..., description="Main proposal heading")
    summary: str = Field(..., description="High level summary of proposal")
    sections: List[ProposalSection] = Field(default_factory=list)
    brand_colors: Optional[Dict[str, str]] = None
    font_family: Optional[str] = None


class EmailTemplatePayload(BaseModel):
    user_id: str
    name: str
    html: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TrainTonePayload(BaseModel):
    text: str


def _branding_path(user_id: str) -> Path:
    user_dir = BRANDING_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


@router.post("/assets")
async def upload_branding_assets(
    user_id: str = Form(...),
    brand_colors: Optional[str] = Form(None),
    fonts: Optional[str] = Form(None),
    logo: UploadFile | None = File(None),
) -> JSONResponse:
    user_dir = _branding_path(user_id)
    config_path = user_dir / "config.json"
    config: Dict[str, Any] = {
        "user_id": user_id,
        "updated_at": datetime.utcnow().isoformat(),
    }
    if brand_colors:
        try:
            config["brand_colors"] = json.loads(brand_colors)
        except json.JSONDecodeError:
            config["brand_colors"] = {"primary": brand_colors}
    if fonts:
        try:
            config["fonts"] = json.loads(fonts)
        except json.JSONDecodeError:
            config["fonts"] = {"primary": fonts}
    if logo:
        logo_path = user_dir / f"logo_{logo.filename}"
        contents = await logo.read()
        logo_path.write_bytes(contents)
        config["logo_path"] = str(logo_path.resolve())
        config["logo_size"] = len(contents)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return JSONResponse(config)


@router.get("/assets/{user_id}")
async def get_branding_assets(user_id: str):
    config_path = _branding_path(user_id) / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Branding assets not found")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return data


def _load_branding_config(user_id: str) -> Dict[str, Any]:
    config_path = _branding_path(user_id) / "config.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@router.post("/proposal_pdf")
async def generate_proposal_pdf(payload: ProposalPDFPayload):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.pdfgen import canvas
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="reportlab is not installed; PDF generation unavailable.",
        )

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER)
    styles = getSampleStyleSheet()
    flowables: List[Any] = []

    config = _load_branding_config(payload.user_id)
    primary_color_hex = (payload.brand_colors or config.get("brand_colors", {})).get("primary", "#111827")

    def _hex_to_rgb(value: str):
        value = value.lstrip("#")
        lv = len(value)
        return tuple(int(value[i : i + lv // 3], 16) / 255 for i in range(0, lv, lv // 3))

    try:
        primary_rgb = _hex_to_rgb(primary_color_hex)
    except Exception:
        primary_rgb = (0.07, 0.09, 0.15)

    title_style = styles["Title"]
    title_style.textColor = colors.Color(*primary_rgb)
    if payload.font_family:
        title_style.fontName = payload.font_family

    flowables.append(Paragraph(payload.proposal_title, title_style))
    flowables.append(Spacer(1, 18))

    summary_style = styles["BodyText"]
    summary_style.leading = 16
    flowables.append(Paragraph(payload.summary, summary_style))
    flowables.append(Spacer(1, 12))

    for section in payload.sections:
        heading_style = styles["Heading2"]
        heading_style.textColor = colors.Color(*primary_rgb)
        flowables.append(Paragraph(section.title, heading_style))
        flowables.append(Spacer(1, 6))
        flowables.append(Paragraph(section.body, summary_style))
        flowables.append(Spacer(1, 12))

    doc.build(flowables)
    buffer.seek(0)
    filename = f"proposal_{payload.user_id}_{uuid4().hex}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)


@router.post("/email_templates")
async def save_email_template(payload: EmailTemplatePayload):
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    template_id = uuid4().hex
    template = {
        "id": template_id,
        "user_id": payload.user_id,
        "name": payload.name,
        "html": payload.html,
        "metadata": payload.metadata,
        "created_at": datetime.utcnow().isoformat(),
    }
    path = EMAIL_TEMPLATE_DIR / f"{payload.user_id}_{timestamp}_{template_id}.json"
    path.write_text(json.dumps(template, indent=2), encoding="utf-8")
    return {"id": template_id, "path": str(path.resolve())}


@router.get("/email_templates/{user_id}")
async def list_email_templates(user_id: str, limit: int = 10):
    templates = []
    for file in sorted(EMAIL_TEMPLATE_DIR.glob(f"{user_id}_*.json"), reverse=True)[:limit]:
        try:
            content = json.loads(file.read_text(encoding="utf-8"))
            templates.append(content)
        except json.JSONDecodeError:
            continue
    return {"templates": templates}


@router.post("/train_tone")
async def train_tone(payload: TrainTonePayload):
    text = payload.text.lower()
    tokens: List[str] = []
    if any(word in text for word in ["innovative", "cutting-edge", "visionary"]):
        tokens.append("innovative")
    if any(word in text for word in ["experienced", "trusted", "proven"]):
        tokens.append("trustworthy")
    if any(word in text for word in ["friendly", "personal", "approachable"]):
        tokens.append("friendly")
    if any(word in text for word in ["technical", "engineering", "architecture"]):
        tokens.append("technical")
    if any(word in text for word in ["assertive", "decisive", "leader"]):
        tokens.append("assertive")
    if not tokens:
        tokens.append("neutral")
    return {"tokens": tokens, "word_count": len(text.split())}
