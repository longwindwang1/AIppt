"""Speaker view 预览：HTML 渲染 deck.json，让老师下载前逐页过一遍。

也承载：
- POST /runs/{id}/slides/{idx}/regenerate — 单页重生成
- GET  /api/runs/{id}/slides/{idx}/diagram.png — 数学示意图 PNG
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from app.config import PROJECT_ROOT, settings
from app.models.slide import Deck, Slide
from app.services import diagrams, runs as runs_service
from app.services.generate import (
    GenerationError,
    GenerationRequest,
    regenerate_single_slide,
)
from app.services.render import THEMES, render

router = APIRouter(tags=["preview"])
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


def _deck_path(run_id: str) -> Path:
    return settings.runs_dir / run_id / "deck.json"


def _load_deck(run_id: str) -> Deck:
    path = _deck_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="该 run 没有 deck.json（可能未完成或已删除）")
    return Deck.model_validate_json(path.read_text(encoding="utf-8"))


@router.get("/runs/{run_id}/preview", response_class=HTMLResponse)
def preview(run_id: str, request: Request) -> HTMLResponse:
    deck = _load_deck(run_id)
    status = runs_service.read(run_id)
    theme_key = status.theme if status else "formal_blue"
    return templates.TemplateResponse(request, "preview.html", {
        "deck": deck,
        "slides": list(enumerate(deck.slides)),
        "run_id": run_id,
        "theme": THEMES.get(theme_key, THEMES["formal_blue"]),
        "theme_key": theme_key,
        "pptx_url": f"/download/{run_id}/{deck.filename()}",
    })


# --- 单页重生成 -----------------------------------------------------------


class SlideRegenBody(BaseModel):
    instructions: str = ""    # 老师对本页的指示（如"难度降一档"）


@router.post("/runs/{run_id}/slides/{slide_idx}/regenerate")
def regenerate_slide(run_id: str, slide_idx: int, body: SlideRegenBody) -> dict:
    deck = _load_deck(run_id)
    if slide_idx < 0 or slide_idx >= len(deck.slides):
        raise HTTPException(status_code=400, detail=f"slide_idx 越界：{slide_idx} / {len(deck.slides)}")

    status = runs_service.read(run_id)
    if not status:
        raise HTTPException(status_code=404, detail="run 不存在")

    req = GenerationRequest(
        deck_type=deck.deck_type,
        grade=deck.grade,
        term=deck.term,
        unit_name=deck.unit_name,
        lesson_name=deck.lesson_name,
        lesson_content="",   # 整页重生成不带正文，避免重复
        standard_excerpt="",
        extra_instructions=body.instructions,
    )

    try:
        new_slide = regenerate_single_slide(req, deck, slide_idx)
    except GenerationError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "stop_reason": e.stop_reason})

    # 替换并落盘
    deck.slides[slide_idx] = new_slide
    _deck_path(run_id).write_text(deck.model_dump_json(indent=2), encoding="utf-8")

    # 重渲整个 pptx（覆盖原文件）
    run_dir = settings.runs_dir / run_id
    pptx_path = run_dir / deck.filename()
    render(deck, out_path=pptx_path, theme_key=status.theme)

    # 审计日志
    edits_log = run_dir / "edits.jsonl"
    with edits_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "slide_idx": slide_idx,
            "instructions": body.instructions,
            "new_title": new_slide.title,
        }, ensure_ascii=False) + "\n")

    return {
        "slide_idx": slide_idx,
        "new_slide": new_slide.model_dump(),
        "pptx_filename": pptx_path.name,
    }


@router.get("/api/runs/{run_id}/slides/{slide_idx}/diagram.png")
def diagram_png(run_id: str, slide_idx: int) -> Response:
    """渲染该页的 diagram 为 PNG。404 if 该页没 diagram。"""
    deck = _load_deck(run_id)
    if slide_idx < 0 or slide_idx >= len(deck.slides):
        raise HTTPException(status_code=400, detail="slide_idx 越界")
    diagram = deck.slides[slide_idx].diagram
    if not diagram:
        raise HTTPException(status_code=404, detail="该页无 diagram")
    try:
        png = diagrams.render_diagram_png_bytes(diagram)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"diagram 渲染失败：{e}")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "max-age=300"})
