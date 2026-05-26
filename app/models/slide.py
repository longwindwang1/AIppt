"""PPT 结构 schema — Sonnet 通过 tool_use 返回的就是 Deck。

设计原则：
- 字段尽量扁平，方便 Sonnet 填充和 render 翻译。
- 动画用 AnimationHint 语义化字段，render 通过分页模拟，避免写 pptx 动画时间线 XML。
- type 决定 render 走哪个布局分支，缺省字段允许为空。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class AnimationHint(str, Enum):
    none = "none"
    reveal_on_click = "reveal_on_click"   # bullets 逐条出现：render 时拆成多页累积
    step_by_step = "step_by_step"          # 解题过程逐步显示：拆成多页递增
    highlight_answer = "highlight_answer"  # 答案最后一页才显示


class SlideType(str, Enum):
    title = "title"            # 封面：title + subtitle
    section = "section"        # 章节分隔页：title only
    content = "content"        # 知识讲解：title + bullets
    example = "example"        # 例题：question + solution（可分步）+ answer
    practice = "practice"      # 课堂练习：question 留白（answer 放在 notes）
    interactive = "interactive"  # 互动提问：question + 留白 + 提示
    summary = "summary"        # 总结：title + bullets


class Slide(BaseModel):
    type: SlideType
    title: str = ""
    subtitle: str = ""
    bullets: list[str] = Field(default_factory=list)
    notes: str = ""                     # 教师讲稿（PPT 备注栏）
    animation: AnimationHint = AnimationHint.none

    # 例题/练习/互动专用
    question: str = ""
    solution_steps: list[str] = Field(default_factory=list)   # 分步解题
    answer: str = ""
    hint: str = ""


class Deck(BaseModel):
    title: str
    grade: int = Field(ge=1, le=6)
    term: int = Field(ge=1, le=2)
    unit_name: str
    lesson_name: str
    deck_type: str  # lesson_plan / knowledge_point / practice / interactive
    slides: list[Slide]

    def filename(self) -> str:
        safe = self.title.replace("/", "_").replace("\\", "_")
        return f"{safe}.pptx"


# JSON Schema 给 Sonnet 的 tool_use（手写，避免 Pydantic 自动 schema 带太多噪音）
DECK_TOOL_SCHEMA = {
    "name": "emit_deck",
    "description": "输出完整的 PPT 结构。每页一个 slide 对象，按讲课顺序排列。",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "PPT 标题（如：北师大版四年级下册 第三单元 买菜）"},
            "grade": {"type": "integer", "minimum": 1, "maximum": 6},
            "term": {"type": "integer", "minimum": 1, "maximum": 2, "description": "学期：1=上册, 2=下册"},
            "unit_name": {"type": "string"},
            "lesson_name": {"type": "string"},
            "deck_type": {
                "type": "string",
                "enum": ["lesson_plan", "knowledge_point", "practice", "interactive"],
            },
            "slides": {
                "type": "array",
                "minItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["title", "section", "content", "example", "practice", "interactive", "summary"],
                        },
                        "title": {"type": "string"},
                        "subtitle": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "notes": {"type": "string", "description": "讲稿，写进 PPT 备注栏，教师讲课时参考"},
                        "animation": {
                            "type": "string",
                            "enum": ["none", "reveal_on_click", "step_by_step", "highlight_answer"],
                        },
                        "question": {"type": "string"},
                        "solution_steps": {"type": "array", "items": {"type": "string"}},
                        "answer": {"type": "string"},
                        "hint": {"type": "string"},
                    },
                    "required": ["type"],
                },
            },
        },
        "required": ["title", "grade", "term", "unit_name", "lesson_name", "deck_type", "slides"],
    },
}
