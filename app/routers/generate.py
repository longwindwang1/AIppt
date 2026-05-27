"""生成 PPT 的 HTTP 入口。

- POST /generate           — 单个 PPT（异步，返 run_id）
- POST /generate/batch     — 整单元批量（一次出该单元全部课时）
- GET  /api/runs/{id}/status
- GET  /api/batch/{batch_id}/status / /zip
"""
from __future__ import annotations

import io
import uuid
import zipfile

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import settings
from app.services import kb as kb_service
from app.services import runs as runs_service
from app.services.generate import GenerationError, GenerationRequest, generate_deck, save_deck_json
from app.services.pricing import estimate_cost
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
        deck, in_tok, out_tok = generate_deck(req)
        runs_service.update(run_id, input_tokens=in_tok, output_tokens=out_tok,
                            cost_usd=estimate_cost(in_tok, out_tok))
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


# --- 单元批量生成 -----------------------------------------------------------


class BatchBody(BaseModel):
    deck_type: str = Field(pattern="^(lesson_plan|knowledge_point|practice|interactive)$")
    grade: int = Field(ge=1, le=6)
    term: int = Field(ge=1, le=2)
    unit_name: str
    theme: str = "formal_blue"
    class_level: str = Field(default="normal", pattern="^(advanced|normal|basic)$")


class BatchAck(BaseModel):
    batch_id: str
    run_ids: list[str]
    status_url: str


@router.post("/generate/batch", response_model=BatchAck)
def generate_batch(body: BatchBody, background_tasks: BackgroundTasks) -> BatchAck:
    if body.theme not in THEMES:
        raise HTTPException(status_code=400, detail=f"未知主题：{body.theme}")

    # 找该单元的所有课时
    tree = kb_service.tree()
    grade_node = tree.get(f"grade_{body.grade}", {})
    term_node = grade_node.get(f"term_{body.term}", {})
    lessons: list[dict] = []
    for unit in term_node.values():
        if unit.get("name") == body.unit_name:
            lessons.extend(unit.get("lessons", []))

    if not lessons:
        raise HTTPException(status_code=404, detail=f"未找到单元《{body.unit_name}》的任何课时")

    batch_id = "b" + uuid.uuid4().hex[:10]
    run_ids: list[str] = []
    for les in lessons:
        run_id = uuid.uuid4().hex[:12]
        runs_service.init(
            run_id,
            deck_type=body.deck_type, grade=body.grade, term=body.term,
            unit_name=body.unit_name, lesson_name=les["name"],
            theme=body.theme, batch_id=batch_id,
        )
        run_body = GenerateBody(
            deck_type=body.deck_type, grade=body.grade, term=body.term,
            unit_name=body.unit_name, lesson_name=les["name"],
            lesson_id=les["id"], theme=body.theme, class_level=body.class_level,
        )
        background_tasks.add_task(_pipeline, run_id, run_body)
        run_ids.append(run_id)

    return BatchAck(batch_id=batch_id, run_ids=run_ids,
                    status_url=f"/api/batch/{batch_id}/status")


@router.get("/api/batch/{batch_id}/status")
def batch_status(batch_id: str) -> dict:
    items = runs_service.find_batch(batch_id)
    if not items:
        raise HTTPException(status_code=404, detail="batch 不存在")
    done = sum(1 for s in items if s.stage == "done")
    error = sum(1 for s in items if s.stage == "error")
    return {
        "batch_id": batch_id,
        "total": len(items),
        "done": done,
        "error": error,
        "in_progress": len(items) - done - error,
        "runs": [
            {**s.model_dump(), "pptx_url": s.pptx_url()} for s in items
        ],
    }


@router.get("/api/batch/{batch_id}/zip")
def batch_zip(batch_id: str) -> Response:
    items = runs_service.find_batch(batch_id)
    if not items:
        raise HTTPException(status_code=404, detail="batch 不存在")
    done_items = [s for s in items if s.stage == "done" and s.pptx_filename]
    if not done_items:
        raise HTTPException(status_code=409, detail="该批次尚无任何完成的 PPT")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for s in done_items:
            path = settings.runs_dir / s.run_id / s.pptx_filename
            if path.exists():
                # zip 内文件名加序号避免重名
                zf.write(path, arcname=f"{s.lesson_name}_{s.deck_type}.pptx")

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={batch_id}.zip"},
    )
