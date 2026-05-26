"""知识库读写。app 内**唯一**直接改 index.json 的入口。

并发安全靠"读-改-写整个文件"的简单粗暴方式 + 文件锁；本地单用户场景足够。
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path

from app.config import settings


def _empty_index() -> dict:
    return {}


def _read_index() -> dict:
    if not settings.index_path.exists():
        return _empty_index()
    try:
        return json.loads(settings.index_path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return _empty_index()


def _write_index(data: dict) -> None:
    settings.index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.index_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(settings.index_path)


@contextmanager
def _mutate_index():
    """读 → yield → 写。yield 出来的 dict 可以原地修改。"""
    data = _read_index()
    yield data
    _write_index(data)


def add_lesson(*, grade: int, term: int, unit_index: int, unit_name: str,
               lesson_name: str, content: str,
               knowledge_points: list[str] | None = None) -> dict:
    """写入一节课的正文到 textbooks/，并更新 index.json。

    返回写入的 Lesson dict。
    """
    grade_key = f"grade_{grade}"
    term_key = f"term_{term}"
    unit_key = f"unit_{unit_index}"
    lesson_id = f"g{grade}t{term}u{unit_index}l{_next_lesson_seq(grade_key, term_key, unit_key)}"

    rel_path = Path("textbooks") / grade_key / term_key / unit_key / f"{lesson_id}.md"
    abs_path = settings.kb_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(
        f"# {lesson_name}\n\n年级：{grade}　学期：{term}　单元：{unit_name}\n\n{content.strip()}\n",
        encoding="utf-8",
    )

    lesson = {
        "id": lesson_id,
        "name": lesson_name,
        "file": rel_path.as_posix(),
        "knowledge_points": knowledge_points or [],
    }

    with _mutate_index() as idx:
        grade_node = idx.setdefault(grade_key, {})
        term_node = grade_node.setdefault(term_key, {})
        unit_node = term_node.setdefault(unit_key, {"name": unit_name, "lessons": []})
        # 若 unit_name 之前为空，补上
        if not unit_node.get("name"):
            unit_node["name"] = unit_name
        unit_node["lessons"].append(lesson)

    return lesson


def _next_lesson_seq(grade_key: str, term_key: str, unit_key: str) -> int:
    idx = _read_index()
    lessons = idx.get(grade_key, {}).get(term_key, {}).get(unit_key, {}).get("lessons", [])
    return len(lessons) + 1


def tree() -> dict:
    """返回知识库树形结构（供前端渲染选择器）。"""
    return _read_index()


def count_lessons() -> int:
    idx = _read_index()
    n = 0
    for g in idx.values():
        for t in g.values():
            for u in t.values():
                n += len(u.get("lessons", []))
    return n


def get_lesson_content(*, grade: int, term: int, unit_name: str,
                        lesson_name: str, lesson_id: str | None = None) -> str:
    """按 id 或 (grade/term/unit_name/lesson_name) 取课时正文。找不到返回空串。"""
    idx = _read_index()
    grade_node = idx.get(f"grade_{grade}", {})
    term_node = grade_node.get(f"term_{term}", {})

    target_path: str | None = None
    for unit in term_node.values():
        if unit.get("name") != unit_name and not lesson_id:
            continue
        for les in unit.get("lessons", []):
            if lesson_id and les["id"] == lesson_id:
                target_path = les["file"]
                break
            if not lesson_id and les["name"] == lesson_name:
                target_path = les["file"]
                break
        if target_path:
            break

    if not target_path:
        return ""

    abs_path = settings.kb_dir / target_path
    if not abs_path.exists():
        return ""
    return abs_path.read_text(encoding="utf-8")


def get_standard_for_grade(grade: int) -> str:
    """按学段返回课程标准节选。"""
    stage = "1-2" if grade <= 2 else "3-4" if grade <= 4 else "5-6"
    candidates = list(settings.standards_dir.glob(f"stage_{stage}*.md"))
    if not candidates:
        return ""
    return candidates[0].read_text(encoding="utf-8")


# --- 教材切分辅助 ----------------------------------------------------------


_LESSON_PATTERNS = [
    re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*课时", re.MULTILINE),
    re.compile(r"^[\d]+[.\.、]\s*\S{2,15}$", re.MULTILINE),  # "1. 买菜"
]


def split_into_lessons(text: str) -> list[tuple[str, str]]:
    """把上传教材的整段文本按"课时标题"切分。

    返回 [(标题, 正文)]。粗略实现：找到匹配的标题行作为分隔。找不到就整体作为一节。
    """
    text = text.strip()
    if not text:
        return []

    # 找所有可能的标题位置
    indices: list[tuple[int, str]] = []
    for pat in _LESSON_PATTERNS:
        for m in pat.finditer(text):
            indices.append((m.start(), m.group().strip()))
    indices.sort()

    if not indices:
        return [("（未识别课时）", text)]

    lessons: list[tuple[str, str]] = []
    for i, (pos, title) in enumerate(indices):
        end = indices[i + 1][0] if i + 1 < len(indices) else len(text)
        body = text[pos + len(title):end].strip()
        lessons.append((title, body))
    return lessons
