"""runs 状态机生命周期。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import runs


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path: Path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(type(settings), "runs_dir",
                        property(lambda self: tmp_path / "runs"))
    yield


def test_init_and_read():
    s = runs.init("abc123", deck_type="lesson_plan", grade=4, term=2,
                  unit_name="小数加减法", lesson_name="买菜")
    assert s.stage == "queued"
    back = runs.read("abc123")
    assert back is not None
    assert back.unit_name == "小数加减法"
    assert back.grade == 4


def test_update_transitions():
    runs.init("x1")
    runs.update("x1", stage="thinking", message="调 Sonnet", progress=0.2)
    runs.update("x1", stage="rendering", message="渲染中", progress=0.7,
                deck_title="T", slide_count=8)
    runs.update("x1", stage="done", message="完成", progress=1.0,
                pptx_filename="T.pptx")
    s = runs.read("x1")
    assert s.stage == "done"
    assert s.pptx_filename == "T.pptx"
    assert s.pptx_url() == "/download/x1/T.pptx"


def test_list_sorted_by_updated_at():
    import time
    runs.init("a")
    time.sleep(0.05)
    runs.init("b")
    time.sleep(0.05)
    runs.init("c")
    items = runs.list_all()
    ids = [s.run_id for s in items]
    # 最新创建的在前
    assert ids[0] == "c"
    assert ids[-1] == "a"


def test_delete():
    runs.init("kill_me")
    assert runs.read("kill_me") is not None
    assert runs.delete("kill_me") is True
    assert runs.read("kill_me") is None
    assert runs.delete("nope") is False


def test_read_missing_returns_none():
    assert runs.read("ghost") is None


def test_count():
    runs.init("a"); runs.init("b")
    assert runs.count() == 2
