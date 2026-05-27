"""端到端 API 测试：mock 模式跑完整生成流水线。"""
from __future__ import annotations

import io
import time
from pathlib import Path

import pytest


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch):
    # 隔离所有路径
    from app.config import settings
    monkeypatch.setattr(type(settings), "kb_dir", property(lambda self: tmp_path / "kb"))
    monkeypatch.setattr(type(settings), "textbooks_dir", property(lambda self: tmp_path / "kb" / "textbooks"))
    monkeypatch.setattr(type(settings), "standards_dir", property(lambda self: tmp_path / "kb" / "standards"))
    monkeypatch.setattr(type(settings), "index_path", property(lambda self: tmp_path / "kb" / "index.json"))
    monkeypatch.setattr(type(settings), "runs_dir", property(lambda self: tmp_path / "runs"))
    # 强制 mock 模式
    monkeypatch.setattr(settings, "mock", True)
    monkeypatch.setattr(settings, "enable_web_search", False)

    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_healthz(app_client):
    r = app_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mock"] is True


def test_pages_render(app_client):
    for path in ["/", "/upload", "/kb", "/generate", "/runs"]:
        r = app_client.get(path)
        assert r.status_code == 200, f"{path} → {r.status_code}"


def test_load_demo(app_client):
    r = app_client.post("/api/kb/load_demo")
    assert r.status_code == 200
    body = r.json()
    assert body["added_count"] >= 3
    assert body["total_lessons"] >= 3
    # 二次调用不重复
    r = app_client.post("/api/kb/load_demo")
    assert r.json()["added_count"] == 0


def test_full_generation_pipeline(app_client):
    # 先加载示例数据
    app_client.post("/api/kb/load_demo")

    r = app_client.post("/generate", json={
        "deck_type": "lesson_plan", "grade": 4, "term": 2,
        "unit_name": "小数加减法", "lesson_name": "买菜",
        "theme": "kids_warm",
    })
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert len(run_id) == 12

    # 轮询直到完成
    for _ in range(20):
        s = app_client.get(f"/api/runs/{run_id}/status").json()
        if s["stage"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert s["stage"] == "done", f"stage 没到 done: {s}"
    assert s["slide_count"] >= 5
    assert s["pptx_url"].startswith("/download/")

    # 实际下载
    r = app_client.get(s["pptx_url"])
    assert r.status_code == 200
    assert r.content[:2] == b"PK"

    # 列表能看到
    runs = app_client.get("/api/runs").json()["runs"]
    assert any(r["run_id"] == run_id for r in runs)


def test_invalid_theme_rejected(app_client):
    r = app_client.post("/generate", json={
        "deck_type": "lesson_plan", "grade": 4, "term": 2,
        "unit_name": "X", "lesson_name": "Y", "theme": "nope",
    })
    assert r.status_code == 400


def test_preview_page(app_client):
    """完成生成后 /runs/{id}/preview 能渲染。"""
    app_client.post("/api/kb/load_demo")
    r = app_client.post("/generate", json={
        "deck_type": "knowledge_point", "grade": 4, "term": 2,
        "unit_name": "小数加减法", "lesson_name": "小数的意义",
        "theme": "blackboard", "class_level": "advanced",
    })
    run_id = r.json()["run_id"]
    for _ in range(20):
        if app_client.get(f"/api/runs/{run_id}/status").json()["stage"] == "done":
            break
        time.sleep(0.5)

    r = app_client.get(f"/runs/{run_id}/preview")
    assert r.status_code == 200
    # 应该包含 deck 标题和"重生成"按钮
    assert "重生成本页" in r.text
    assert "[Mock]" in r.text or "知识点" in r.text


def test_slide_regenerate(app_client):
    app_client.post("/api/kb/load_demo")
    r = app_client.post("/generate", json={
        "deck_type": "lesson_plan", "grade": 4, "term": 2,
        "unit_name": "小数加减法", "lesson_name": "买菜",
        "theme": "formal_blue",
    })
    run_id = r.json()["run_id"]
    for _ in range(20):
        if app_client.get(f"/api/runs/{run_id}/status").json()["stage"] == "done":
            break
        time.sleep(0.5)

    r = app_client.post(f"/runs/{run_id}/slides/2/regenerate", json={
        "instructions": "把例题换成单价情境",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slide_idx"] == 2
    assert "[已修订]" in body["new_slide"]["title"] or "修订指示" in body["new_slide"]["notes"]

    # edits.jsonl 应有审计记录
    from app.config import settings
    edits = settings.runs_dir / run_id / "edits.jsonl"
    assert edits.exists()
    assert "把例题换成单价" in edits.read_text(encoding="utf-8")


def test_class_level_in_request(app_client):
    """class_level 应被接受并传递（mock 模式下不影响内容）。"""
    app_client.post("/api/kb/load_demo")
    for level in ["advanced", "normal", "basic"]:
        r = app_client.post("/generate", json={
            "deck_type": "lesson_plan", "grade": 4, "term": 2,
            "unit_name": "小数加减法", "lesson_name": "买菜",
            "theme": "formal_blue", "class_level": level,
        })
        assert r.status_code == 200

    # 非法 class_level 应被 Pydantic 拒
    r = app_client.post("/generate", json={
        "deck_type": "lesson_plan", "grade": 4, "term": 2,
        "unit_name": "X", "lesson_name": "Y", "theme": "formal_blue",
        "class_level": "genius",
    })
    assert r.status_code == 422


def test_mock_diversity(app_client):
    """4 种 deck_type 各返回不同样本。"""
    app_client.post("/api/kb/load_demo")
    titles = set()
    for dt in ["lesson_plan", "knowledge_point", "practice", "interactive"]:
        r = app_client.post("/generate", json={
            "deck_type": dt, "grade": 4, "term": 2,
            "unit_name": "U", "lesson_name": "L", "theme": "formal_blue",
        })
        run_id = r.json()["run_id"]
        for _ in range(20):
            s = app_client.get(f"/api/runs/{run_id}/status").json()
            if s["stage"] == "done":
                titles.add(s["deck_title"])
                break
            time.sleep(0.3)
    # 4 种类型应产出不同标题（标题里有类型 label）
    assert len(titles) == 4


def test_run_delete(app_client):
    app_client.post("/api/kb/load_demo")
    r = app_client.post("/generate", json={
        "deck_type": "lesson_plan", "grade": 4, "term": 2,
        "unit_name": "小数加减法", "lesson_name": "买菜", "theme": "formal_blue",
    })
    run_id = r.json()["run_id"]
    # 等完成
    for _ in range(20):
        if app_client.get(f"/api/runs/{run_id}/status").json()["stage"] == "done":
            break
        time.sleep(0.5)
    r = app_client.delete(f"/api/runs/{run_id}")
    assert r.status_code == 200
    r = app_client.get(f"/api/runs/{run_id}/status")
    assert r.status_code == 404
