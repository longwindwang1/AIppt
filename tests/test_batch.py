"""测批量生成 + zip 打包。"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(type(settings), "kb_dir", property(lambda self: tmp_path / "kb"))
    monkeypatch.setattr(type(settings), "textbooks_dir", property(lambda self: tmp_path / "kb" / "textbooks"))
    monkeypatch.setattr(type(settings), "standards_dir", property(lambda self: tmp_path / "kb" / "standards"))
    monkeypatch.setattr(type(settings), "index_path", property(lambda self: tmp_path / "kb" / "index.json"))
    monkeypatch.setattr(type(settings), "runs_dir", property(lambda self: tmp_path / "runs"))
    monkeypatch.setattr(settings, "mock", True)
    monkeypatch.setattr(settings, "enable_web_search", False)

    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    c.post("/api/kb/load_demo")
    return c


def _wait_batch_done(client, batch_id: str, timeout_s: float = 30) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = client.get(f"/api/batch/{batch_id}/status").json()
        if s["done"] + s["error"] == s["total"]:
            return s
        time.sleep(0.5)
    return s


def test_batch_generates_all_lessons_in_unit(app_client):
    r = app_client.post("/generate/batch", json={
        "deck_type": "lesson_plan", "grade": 4, "term": 2,
        "unit_name": "小数加减法", "theme": "kids_warm",
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["run_ids"]) == 3                # demo 单元有 3 节课
    batch_id = data["batch_id"]

    s = _wait_batch_done(app_client, batch_id)
    assert s["total"] == 3
    assert s["done"] == 3
    assert s["error"] == 0


def test_batch_zip_download(app_client):
    r = app_client.post("/generate/batch", json={
        "deck_type": "practice", "grade": 4, "term": 2,
        "unit_name": "小数加减法", "theme": "formal_blue",
    })
    batch_id = r.json()["batch_id"]
    _wait_batch_done(app_client, batch_id)

    r = app_client.get(f"/api/batch/{batch_id}/zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert len(names) == 3
    for n in names:
        # 每个文件至少 1KB（应该是真 .pptx）
        assert zf.getinfo(n).file_size > 1000
        assert n.endswith(".pptx")


def test_batch_unknown_unit(app_client):
    r = app_client.post("/generate/batch", json={
        "deck_type": "lesson_plan", "grade": 4, "term": 2,
        "unit_name": "不存在的单元", "theme": "formal_blue",
    })
    assert r.status_code == 404


def test_batch_status_404(app_client):
    r = app_client.get("/api/batch/ghost/status")
    assert r.status_code == 404


def test_diagram_in_rendered_pptx(app_client):
    """有 diagram 的 mock deck（knowledge_point）能渲染出包含图的 pptx。"""
    r = app_client.post("/generate", json={
        "deck_type": "knowledge_point", "grade": 4, "term": 2,
        "unit_name": "小数加减法", "lesson_name": "小数的意义",
        "theme": "formal_blue",
    })
    run_id = r.json()["run_id"]
    for _ in range(30):
        s = app_client.get(f"/api/runs/{run_id}/status").json()
        if s["stage"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert s["stage"] == "done"

    # 渲染产物应该比纯文字版稍大（嵌入了 PNG）
    r = app_client.get(s["pptx_url"])
    assert r.status_code == 200
    assert len(r.content) > 10000   # 含 diagram 的 pptx 至少 10KB

    # diagram PNG endpoint 也应工作（mock deck 的第 3 页带 place_value_chart）
    r = app_client.get(f"/api/runs/{run_id}/slides/3/diagram.png")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
