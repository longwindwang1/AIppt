"""测知识库读写 + 教材切分。不动 PROJECT_ROOT 下的真实 knowledge_base，
通过 monkeypatch 把 kb_dir 改到 tmp_path。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import kb


@pytest.fixture(autouse=True)
def isolated_kb(tmp_path: Path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(type(settings), "kb_dir", property(lambda self: tmp_path / "kb"))
    monkeypatch.setattr(type(settings), "textbooks_dir", property(lambda self: tmp_path / "kb" / "textbooks"))
    monkeypatch.setattr(type(settings), "standards_dir", property(lambda self: tmp_path / "kb" / "standards"))
    monkeypatch.setattr(type(settings), "index_path", property(lambda self: tmp_path / "kb" / "index.json"))
    yield


def test_add_lesson_creates_file_and_index():
    lesson = kb.add_lesson(
        grade=4, term=2, unit_index=3, unit_name="小数加减法",
        lesson_name="买菜", content="妈妈去买菜...",
        knowledge_points=["小数加法"],
    )
    assert lesson["id"] == "g4t2u3l1"
    assert kb.count_lessons() == 1

    content = kb.get_lesson_content(
        grade=4, term=2, unit_name="小数加减法", lesson_name="买菜"
    )
    assert "妈妈去买菜" in content


def test_add_lesson_increments_seq():
    kb.add_lesson(grade=1, term=1, unit_index=1, unit_name="数一数",
                  lesson_name="第一课时", content="一")
    second = kb.add_lesson(grade=1, term=1, unit_index=1, unit_name="数一数",
                           lesson_name="第二课时", content="二")
    assert second["id"] == "g1t1u1l2"
    assert kb.count_lessons() == 2


def test_tree_structure():
    kb.add_lesson(grade=4, term=2, unit_index=3, unit_name="小数加减法",
                  lesson_name="买菜", content="x")
    tree = kb.tree()
    assert tree["grade_4"]["term_2"]["unit_3"]["name"] == "小数加减法"
    assert tree["grade_4"]["term_2"]["unit_3"]["lessons"][0]["name"] == "买菜"


def test_split_into_lessons_with_numbered_headings():
    text = (
        "1. 买菜\n"
        "正文一。\n"
        "正文二。\n"
        "2. 看电影\n"
        "电影正文。\n"
    )
    pieces = kb.split_into_lessons(text)
    titles = [t for t, _ in pieces]
    assert any("买菜" in t for t in titles)
    assert any("看电影" in t for t in titles)


def test_split_into_lessons_with_keshi_headings():
    text = "第一课时 引入\n内容 A\n第二课时 深化\n内容 B\n"
    pieces = kb.split_into_lessons(text)
    assert len(pieces) == 2
    assert "引入" in pieces[0][0] or "第一课时" in pieces[0][0]


def test_split_without_headings_returns_whole():
    text = "这是一段没有课时标题的教材片段。"
    pieces = kb.split_into_lessons(text)
    assert len(pieces) == 1
    assert "没有课时" in pieces[0][1]
