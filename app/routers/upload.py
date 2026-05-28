"""教材上传：表单提交 + 文件 → 解析 → 切分 → 入库。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

from app.services import ingest, kb

router = APIRouter(tags=["upload"])


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    grade: int = Form(..., ge=1, le=12),
    term: int = Form(..., ge=1, le=2),
    unit_index: int = Form(..., ge=1, le=20),
    unit_name: str = Form(...),
    lesson_name: str = Form(""),                       # 留空则自动切分
    knowledge_points: str = Form(""),                  # 逗号分隔
) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=415, detail=f"不支持的文件类型: {suffix}")

    # 写到临时文件再解析（pypdf 需要 path）
    data = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        text = ingest.extract_text(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="未能从文件中提取到文字。如果是扫描件，请先做 OCR 转成 .txt 再上传。",
        )

    kps = [p.strip() for p in knowledge_points.split(",") if p.strip()]

    if lesson_name.strip():
        # 老师明确指定了课时名，整段作为一节
        lesson = kb.add_lesson(
            grade=grade, term=term, unit_index=unit_index, unit_name=unit_name,
            lesson_name=lesson_name.strip(), content=text, knowledge_points=kps,
        )
        return {"added": [lesson]}

    # 否则自动切分
    pieces = kb.split_into_lessons(text)
    added = []
    for title, body in pieces:
        added.append(kb.add_lesson(
            grade=grade, term=term, unit_index=unit_index, unit_name=unit_name,
            lesson_name=title, content=body, knowledge_points=kps,
        ))
    return {"added": added}


@router.post("/upload/form")
async def upload_form(
    file: UploadFile = File(...),
    grade: int = Form(...),
    term: int = Form(...),
    unit_index: int = Form(...),
    unit_name: str = Form(...),
    lesson_name: str = Form(""),
    knowledge_points: str = Form(""),
) -> RedirectResponse:
    """同 /upload，但成功后跳到 /kb 页面（给浏览器表单用）。"""
    await upload(file=file, grade=grade, term=term, unit_index=unit_index,
                 unit_name=unit_name, lesson_name=lesson_name,
                 knowledge_points=knowledge_points)
    return RedirectResponse(url="/kb", status_code=303)
