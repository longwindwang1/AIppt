"""知识库 schema。

文件布局：
  knowledge_base/
    textbooks/grade_X/term_Y/unit_Z/lesson_N.md    # 用户上传后切分的正文
    standards/                                      # 课程标准
    index.json                                      # 树形元数据，按 grade/term/unit 索引
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Lesson(BaseModel):
    id: str
    name: str
    file: str                                     # 相对 knowledge_base 的路径
    knowledge_points: list[str] = Field(default_factory=list)


class Unit(BaseModel):
    name: str
    lessons: list[Lesson] = Field(default_factory=list)


class Term(BaseModel):
    units: dict[str, Unit] = Field(default_factory=dict)   # key: "unit_3"


class Grade(BaseModel):
    terms: dict[str, Term] = Field(default_factory=dict)   # key: "term_1" / "term_2"


class Standard(BaseModel):
    """义务教育数学课程标准条目（按学段：1-2年级 / 3-4年级 / 5-6年级）。"""
    stage: str                                    # "1-2" / "3-4" / "5-6"
    title: str
    content: str
