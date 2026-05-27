"""Speaker view 预览：HTML 渲染 deck.json，让老师下载前逐页过一遍。

也承载：
- POST /runs/{id}/slides/{idx}/regenerate — 单页重生成
- GET  /api/runs/{id}/slides/{idx}/diagram.png — 数学示意图 PNG
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
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


def _difficult_path(run_id: str) -> Path:
    return settings.runs_dir / run_id / "difficult.json"


def _read_difficult(run_id: str) -> set[int]:
    path = _difficult_path(run_id)
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")).get("indices", []))
    except Exception:
        return set()


def _write_difficult(run_id: str, indices: set[int]) -> None:
    path = _difficult_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"indices": sorted(indices)}), encoding="utf-8")


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
    difficult = _read_difficult(run_id)
    return templates.TemplateResponse(request, "preview.html", {
        "deck": deck,
        "slides": list(enumerate(deck.slides)),
        "run_id": run_id,
        "theme": THEMES.get(theme_key, THEMES["formal_blue"]),
        "theme_key": theme_key,
        "pptx_url": f"/download/{run_id}/{deck.filename()}",
        "difficult_set": difficult,
    })


# --- 难点标记 -------------------------------------------------------------

@router.post("/runs/{run_id}/difficult/{slide_idx}")
def toggle_difficult(run_id: str, slide_idx: int) -> dict:
    deck = _load_deck(run_id)
    if slide_idx < 0 or slide_idx >= len(deck.slides):
        raise HTTPException(status_code=400, detail="slide_idx 越界")
    current = _read_difficult(run_id)
    if slide_idx in current:
        current.discard(slide_idx)
        marked = False
    else:
        current.add(slide_idx)
        marked = True
    _write_difficult(run_id, current)
    return {"slide_idx": slide_idx, "marked": marked, "all_difficult": sorted(current)}


@router.get("/runs/{run_id}/difficult")
def get_difficult(run_id: str) -> dict:
    return {"indices": sorted(_read_difficult(run_id))}


# --- 难点澄清 PPT --------------------------------------------------------

@router.post("/runs/{run_id}/clarify")
def generate_clarification(run_id: str, background_tasks: BackgroundTasks) -> dict:
    """根据被标的难点页，spawn 一个新 run 生成澄清 PPT。"""
    deck = _load_deck(run_id)
    status = runs_service.read(run_id)
    if not status:
        raise HTTPException(status_code=404, detail="原 run 不存在")

    difficult = sorted(_read_difficult(run_id))
    if not difficult:
        raise HTTPException(status_code=400, detail="尚未标记任何难点页")

    # 把难点页的核心内容浓缩成 extra_instructions
    lines = ["这是一节【难点澄清课】，针对学生在原 PPT 中表示没听懂的若干页重新讲解。",
             f"原 PPT 题目：{deck.title}",
             "",
             "## 学生反馈的难点页内容："]
    for idx in difficult:
        s = deck.slides[idx]
        lines.append(f"\n### 第 {idx + 1} 页（type={s.type}）")
        if s.title:
            lines.append(f"标题：{s.title}")
        if s.question:
            lines.append(f"题目：{s.question}")
        if s.bullets:
            lines.append("要点：" + "；".join(s.bullets))
        if s.solution_steps:
            lines.append("解答步骤：" + " → ".join(s.solution_steps))
        if s.notes:
            lines.append(f"原讲稿：{s.notes[:200]}")

    lines += [
        "",
        "## 重生成要求",
        "- 总页数 6~10 页（不是完整一节课，是聚焦澄清）",
        "- 用更直观的方式（多用 diagram 字段、举更生活化例子）重新讲解上面的难点",
        "- 假设学生已经听过原 PPT 但没理解，所以**不要重复原讲法**，换思路",
        "- 每个难点至少 1~2 页对应",
        "- 末尾留 1 页「小测一下」练习",
    ]
    extra_instructions = "\n".join(lines)

    # 用原 run 的元数据 + 这段超长指令，spawn 新生成
    from app.routers.generate import GenerateBody, _pipeline

    new_run_id = uuid.uuid4().hex[:12]
    runs_service.init(
        new_run_id,
        deck_type="lesson_plan",
        grade=status.grade, term=status.term,
        unit_name=status.unit_name,
        lesson_name=f"{status.lesson_name} · 难点澄清",
        theme=status.theme,
        parent_run_id=run_id,
    )
    body = GenerateBody(
        deck_type="lesson_plan",
        grade=status.grade, term=status.term,
        unit_name=status.unit_name,
        lesson_name=f"{status.lesson_name} · 难点澄清",
        theme=status.theme,
        extra_instructions=extra_instructions,
        class_level="basic",   # 澄清课默认按基础班难度走
    )
    background_tasks.add_task(_pipeline, new_run_id, body)
    return {
        "new_run_id": new_run_id,
        "based_on": run_id,
        "difficult_pages": difficult,
        "status_url": f"/api/runs/{new_run_id}/status",
        "preview_url_after_done": f"/runs/{new_run_id}/preview",
    }


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
        new_slide, usage = regenerate_single_slide(req, deck, slide_idx)
    except GenerationError as e:
        raise HTTPException(status_code=502, detail={"error": str(e), "stop_reason": e.stop_reason})

    # 累加 token 用量
    from app.services.pricing import estimate_cost
    new_in = status.input_tokens + usage.input_tokens
    new_out = status.output_tokens + usage.output_tokens
    new_cache_r = status.cache_read_tokens + usage.cache_read_tokens
    new_cache_w = status.cache_write_tokens + usage.cache_write_tokens
    runs_service.update(
        run_id,
        input_tokens=new_in,
        output_tokens=new_out,
        cache_read_tokens=new_cache_r,
        cache_write_tokens=new_cache_w,
        cost_usd=estimate_cost(new_in, new_out, new_cache_r, new_cache_w,
                               model_id=settings.model),
    )

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
