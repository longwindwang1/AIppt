"""生成 PPT 的 HTTP 入口（M5：异步化）。

流程：
  POST /generate → 立即返 run_id；BackgroundTasks 跑生成流水线
  GET  /api/runs/{run_id}/status → 轮询进度

阶段：queued → thinking（调 Sonnet）→ rendering → done | error
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services import kb as kb_service
from app.services import runs as runs_service
from app.services.generate import GenerationError, GenerationRequest, generate_deck, save_deck_json
from app.services.render import THEMES, render

router = APIRouter(tags=["generate"])


class GenerateBody(BaseModel):
    deck_type: str = Field(pattern="^(lesson_plan|knowledge_point|practice|interactive)$")
    grade: int = Field(ge=1, le=6)
    term: int = Field(ge=1, le=2)
    unit_name: str
    lesson_name: str
    lesson_id: str | None = None
    extra_instructions: str = ""
    theme: str = "formal_blue"
    class_level: str = Field(default="normal", pattern="^(advanced|normal|basic)$")


class GenerateAck(BaseModel):
    run_id: str
    status_url: str


def _pipeline(run_id: str, body: GenerateBody) -> None:
    """后台跑：Sonnet → 渲染 → 写 done/error。状态消息按阶段细化。"""
    runs_service.update(run_id, stage="thinking", progress=0.05,
                        message="读取课时正文和课程标准…")

    try:
        lesson_content = kb_service.get_lesson_content(
            grade=body.grade, term=body.term,
            unit_name=body.unit_name, lesson_name=body.lesson_name,
            lesson_id=body.lesson_id,
        )
        standard_excerpt = kb_service.get_standard_for_grade(body.grade)

        type_label = {
            "lesson_plan": "课时教案", "knowledge_point": "知识点专项",
            "practice": "练习题集", "interactive": "映射教学",
        }.get(body.deck_type, body.deck_type)
        runs_service.update(run_id, progress=0.15,
                            message=f"Sonnet 正在设计《{body.lesson_name}》{type_label}大纲…")

        req = GenerationRequest(
            deck_type=body.deck_type, grade=body.grade, term=body.term,
            unit_name=body.unit_name, lesson_name=body.lesson_name,
            lesson_content=lesson_content, standard_excerpt=standard_excerpt,
            extra_instructions=body.extra_instructions,
            class_level=body.class_level,
        )
        deck = generate_deck(req)
    except GenerationError as e:
        runs_service.update(run_id, stage="error", message=f"生成失败：{e}",
                            error=str(e), stop_reason=e.stop_reason or "")
        return
    except Exception as e:
        runs_service.update(run_id, stage="error", message=f"未预期异常：{e}", error=str(e))
        return

    runs_service.update(run_id, stage="rendering",
                        message=f"已生成 {len(deck.slides)} 页大纲，正在排版 .pptx…",
                        progress=0.75, deck_title=deck.title, slide_count=len(deck.slides))

    try:
        run_dir = settings.runs_dir / run_id
        save_deck_json(deck, run_dir)
        pptx_path = render(deck, out_path=run_dir / deck.filename(), theme_key=body.theme)
    except Exception as e:
        runs_service.update(run_id, stage="error", message=f"渲染失败：{e}", error=str(e))
        return

    runs_service.update(
        run_id, stage="done",
        message=f"生成完成 · {len(deck.slides)} 页 · 主题：{body.theme}",
        progress=1.0, pptx_filename=pptx_path.name,
    )


@router.post("/generate", response_model=GenerateAck)
def generate(body: GenerateBody, background_tasks: BackgroundTasks) -> GenerateAck:
    if body.theme not in THEMES:
        raise HTTPException(status_code=400, detail=f"未知主题：{body.theme}（可选：{list(THEMES)}）")

    run_id = uuid.uuid4().hex[:12]
    runs_service.init(
        run_id,
        deck_type=body.deck_type, grade=body.grade, term=body.term,
        unit_name=body.unit_name, lesson_name=body.lesson_name, theme=body.theme,
    )
    background_tasks.add_task(_pipeline, run_id, body)
    return GenerateAck(run_id=run_id, status_url=f"/api/runs/{run_id}/status")


@router.get("/api/runs")
def list_runs() -> dict:
    return {"runs": [s.model_dump() for s in runs_service.list_all()]}


@router.get("/api/runs/{run_id}/status")
def run_status(run_id: str) -> dict:
    s = runs_service.read(run_id)
    if not s:
        raise HTTPException(status_code=404, detail="run 不存在")
    out = s.model_dump()
    out["pptx_url"] = s.pptx_url()
    return out


@router.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> dict:
    ok = runs_service.delete(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="run 不存在")
    return {"deleted": run_id}
