"""FastAPI 入口。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.config import PROJECT_ROOT, settings
from app.routers import download, generate, kb, upload
from app.services.render import THEMES

app = FastAPI(title="aippt", description="成都市小学数学 PPT 自动生成", version="0.1.0")

app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")

app.include_router(upload.router)
app.include_router(kb.router)
app.include_router(generate.router)
app.include_router(download.router)


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "model": settings.model,
        "kb_indexed_lessons": _count_lessons(),
        "runs_count": _count_runs(),
        "web_search": settings.enable_web_search,
        "mock": settings.mock,
    }


def _count_lessons() -> int:
    from app.services import kb as kb_service
    try:
        return kb_service.count_lessons()
    except Exception:
        return 0


def _count_runs() -> int:
    from app.services import runs as runs_service
    try:
        return runs_service.count()
    except Exception:
        return 0


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html", {
        "model": settings.model,
        "lesson_count": _count_lessons(),
        "runs_count": _count_runs(),
    })


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "upload.html", {})


@app.get("/kb", response_class=HTMLResponse)
def kb_page(request: Request) -> HTMLResponse:
    from app.services import kb as kb_service
    return templates.TemplateResponse(request, "kb.html", {
        "tree": kb_service.tree(),
    })


@app.get("/generate", response_class=HTMLResponse)
def generate_page(request: Request) -> HTMLResponse:
    from app.services import kb as kb_service
    return templates.TemplateResponse(request, "generate.html", {
        "tree": kb_service.tree(),
        "themes": THEMES,
    })


@app.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request) -> HTMLResponse:
    from app.services import runs as runs_service
    return templates.TemplateResponse(request, "runs.html", {
        "runs": [r.model_dump() for r in runs_service.list_all()],
        "type_labels": {
            "lesson_plan": "课时教案",
            "knowledge_point": "知识点专项",
            "practice": "练习题集",
            "interactive": "映射教学",
        },
        "theme_labels": {k: t.label for k, t in THEMES.items()},
    })
