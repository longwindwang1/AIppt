"""按 run_id 下载生成产物。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter(tags=["download"])


@router.get("/download/{run_id}/{filename}")
def download(run_id: str, filename: str) -> FileResponse:
    if not run_id.isalnum() or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法路径")
    path = settings.runs_dir / run_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )
