"""知识库 JSON API（前端列表 / 加载示例 / 统计等）。"""
from __future__ import annotations

from fastapi import APIRouter

from app.services import kb as kb_service

router = APIRouter(prefix="/api/kb", tags=["kb"])


@router.get("/tree")
def get_tree() -> dict:
    return kb_service.tree()


@router.get("/stats")
def get_stats() -> dict:
    return {"total_lessons": kb_service.count_lessons()}


@router.post("/load_demo")
def load_demo() -> dict:
    """加载 samples/lessons/ 下的示例课时到知识库，让首次安装就能体验。"""
    # 延迟导入避免 main 启动时拉 samples 目录
    from scripts import load_demo as loader  # type: ignore
    added = loader.load_all()
    return {
        "added": added,
        "added_count": len(added),
        "total_lessons": kb_service.count_lessons(),
    }
