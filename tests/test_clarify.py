"""难点标记 + 澄清 PPT 流程。"""
from __future__ import annotations

import time
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
    # 先生成一个 deck 作为标记基础
    r = c.post("/generate", json={
        "deck_type": "lesson_plan", "grade": 4, "term": 2,
        "unit_name": "小数加减法", "lesson_name": "买菜", "theme": "formal_blue",
    })
    run_id = r.json()["run_id"]
    for _ in range(20):
        if c.get(f"/api/runs/{run_id}/status").json()["stage"] == "done":
            break
        time.sleep(0.3)
    return c, run_id


def test_toggle_difficult_on_off(app_client):
    c, run_id = app_client
    # 一开始是空
    assert c.get(f"/runs/{run_id}/difficult").json()["indices"] == []
    # 标第 2 页
    r = c.post(f"/runs/{run_id}/difficult/2")
    assert r.status_code == 200
    assert r.json()["marked"] is True
    assert r.json()["all_difficult"] == [2]
    # 再标第 4 页
    c.post(f"/runs/{run_id}/difficult/4")
    indices = c.get(f"/runs/{run_id}/difficult").json()["indices"]
    assert indices == [2, 4]
    # 再点一次第 2 页 → 取消
    r = c.post(f"/runs/{run_id}/difficult/2")
    assert r.json()["marked"] is False
    assert c.get(f"/runs/{run_id}/difficult").json()["indices"] == [4]


def test_difficult_out_of_range(app_client):
    c, run_id = app_client
    r = c.post(f"/runs/{run_id}/difficult/9999")
    assert r.status_code == 400


def test_clarify_requires_at_least_one_difficult(app_client):
    c, run_id = app_client
    r = c.post(f"/runs/{run_id}/clarify")
    assert r.status_code == 400


def test_clarify_spawns_new_run(app_client):
    c, run_id = app_client
    c.post(f"/runs/{run_id}/difficult/2")
    c.post(f"/runs/{run_id}/difficult/3")
    r = c.post(f"/runs/{run_id}/clarify")
    assert r.status_code == 200
    data = r.json()
    new_run_id = data["new_run_id"]
    assert new_run_id != run_id
    assert data["based_on"] == run_id
    assert data["difficult_pages"] == [2, 3]

    # 等新 run 完成
    for _ in range(30):
        s = c.get(f"/api/runs/{new_run_id}/status").json()
        if s["stage"] == "done":
            break
        time.sleep(0.3)
    assert s["stage"] == "done"
    # 新 run 应该有 "难点澄清" 字样
    assert "难点澄清" in s["lesson_name"]
    # 应链接回原 run
    assert s["batch_id"] == f"clarify_of_{run_id}"


def test_cost_zero_in_mock_mode(app_client):
    """mock 模式下 token / cost 都应为 0，不烧钱。"""
    c, run_id = app_client
    s = c.get(f"/api/runs/{run_id}/status").json()
    assert s["input_tokens"] == 0
    assert s["output_tokens"] == 0
    assert s["cost_usd"] == 0.0
