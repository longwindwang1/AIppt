"""Deck (Pydantic) → .pptx 文件。

设计：
- 不依赖外部 .pptx 模板也能跑（python-pptx 默认母版即可），有 template.pptx 则用它。
- 动画通过"展开成多页"模拟，不写动画时间线 XML。
- Theme 控制配色 / 字体 / 装饰，3 套预设：formal_blue / kids_warm / blackboard。
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from app.config import settings
from app.models.slide import AnimationHint, Deck, Slide, SlideType


# --- 主题系统 ---------------------------------------------------------------

@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    cn_font: str
    title_color: RGBColor
    accent_color: RGBColor
    text_color: RGBColor
    muted_color: RGBColor
    bg_color: RGBColor | None = None     # 整页背景色（None = 白）
    title_bar_text_color: RGBColor = field(default_factory=lambda: RGBColor(0xFF, 0xFF, 0xFF))
    base_size_bullet: int = 22
    base_size_title_bar: int = 28
    base_size_cover_title: int = 44
    rounded_corners: bool = False        # True = 标题栏圆角矩形（kids_warm）

    def best_for(self) -> str:
        return {
            "formal_blue": "公开课、家长会，正式场合",
            "kids_warm": "低年级日常课，活泼亲切",
            "blackboard": "复习课，黑板感强",
        }.get(self.key, "")


_FORMAL_BLUE = Theme(
    key="formal_blue",
    label="正式蓝",
    cn_font="Microsoft YaHei",
    title_color=RGBColor(0x1F, 0x4E, 0x79),
    accent_color=RGBColor(0xE8, 0x74, 0x22),
    text_color=RGBColor(0x33, 0x33, 0x33),
    muted_color=RGBColor(0x88, 0x88, 0x88),
)

_KIDS_WARM = Theme(
    key="kids_warm",
    label="童趣暖",
    cn_font="Microsoft YaHei",
    title_color=RGBColor(0xE6, 0x7E, 0x22),
    accent_color=RGBColor(0x27, 0xAE, 0x60),
    text_color=RGBColor(0x34, 0x49, 0x5E),
    muted_color=RGBColor(0x95, 0xA5, 0xA6),
    base_size_bullet=24,
    base_size_title_bar=30,
    base_size_cover_title=48,
    rounded_corners=True,
)

_BLACKBOARD = Theme(
    key="blackboard",
    label="黑板风",
    cn_font="Microsoft YaHei",
    title_color=RGBColor(0xF1, 0xC4, 0x0F),     # 粉笔黄
    accent_color=RGBColor(0xE7, 0x4C, 0x3C),    # 红粉笔
    text_color=RGBColor(0xEC, 0xF0, 0xF1),      # 近白粉笔
    muted_color=RGBColor(0xBD, 0xC3, 0xC7),
    bg_color=RGBColor(0x1B, 0x2D, 0x1F),         # 墨绿黑板
    title_bar_text_color=RGBColor(0xF1, 0xC4, 0x0F),
)


THEMES: dict[str, Theme] = {
    t.key: t for t in [_FORMAL_BLUE, _KIDS_WARM, _BLACKBOARD]
}


def get_theme(key: str | None) -> Theme:
    if not key or key not in THEMES:
        return _FORMAL_BLUE
    return THEMES[key]


# --- 公开 API ---------------------------------------------------------------

def render(deck: Deck, out_path: Path | None = None,
           theme_key: str | None = None) -> Path:
    """渲染 Deck 到 .pptx 文件，返回写入路径。"""
    theme = get_theme(theme_key)
    prs = _new_presentation()

    for slide in _expand_animations(deck.slides):
        _add_slide(prs, slide, theme)

    if out_path is None:
        settings.runs_dir.mkdir(parents=True, exist_ok=True)
        out_path = settings.runs_dir / deck.filename()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out_path)
    return out_path


def render_to_bytes(deck: Deck, theme_key: str | None = None) -> bytes:
    theme = get_theme(theme_key)
    prs = _new_presentation()
    for slide in _expand_animations(deck.slides):
        _add_slide(prs, slide, theme)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# --- 内部实现 ---------------------------------------------------------------

def _new_presentation() -> Presentation:
    template = settings.template_pptx
    if template.exists():
        return Presentation(str(template))
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def _expand_animations(slides: list[Slide]) -> list[Slide]:
    out: list[Slide] = []
    for s in slides:
        if s.animation == AnimationHint.reveal_on_click and s.bullets:
            for i in range(1, len(s.bullets) + 1):
                out.append(s.model_copy(update={
                    "bullets": s.bullets[:i],
                    "animation": AnimationHint.none,
                }))
        elif s.animation == AnimationHint.step_by_step and s.solution_steps:
            for i in range(1, len(s.solution_steps) + 1):
                out.append(s.model_copy(update={
                    "solution_steps": s.solution_steps[:i],
                    "animation": AnimationHint.none,
                }))
        elif s.animation == AnimationHint.highlight_answer:
            out.append(s.model_copy(update={"answer": "", "animation": AnimationHint.none}))
            if s.answer:
                out.append(s.model_copy(update={"animation": AnimationHint.none}))
        else:
            out.append(s)
    return out


def _add_slide(prs: Presentation, slide: Slide, theme: Theme) -> None:
    blank = prs.slide_layouts[6]
    s = prs.slides.add_slide(blank)

    # 背景色（黑板风专属）
    if theme.bg_color is not None:
        bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = theme.bg_color
        bg.line.fill.background()
        # 把背景放到最底层
        spTree = bg._element.getparent()
        spTree.remove(bg._element)
        spTree.insert(2, bg._element)

    if slide.type == SlideType.title:
        _draw_title_slide(s, slide, theme)
    elif slide.type == SlideType.section:
        _draw_section_slide(s, slide, theme)
    elif slide.type == SlideType.example:
        _draw_example_slide(s, slide, theme)
    elif slide.type == SlideType.practice:
        _draw_practice_slide(s, slide, theme)
    elif slide.type == SlideType.interactive:
        _draw_interactive_slide(s, slide, theme)
    else:
        _draw_content_slide(s, slide, theme)

    if slide.notes:
        s.notes_slide.notes_text_frame.text = slide.notes


def _draw_title_slide(s, slide: Slide, theme: Theme) -> None:
    _add_text_box(s, slide.title or slide.subtitle, Inches(1), Inches(2.5),
                  Inches(11.3), Inches(1.5), theme,
                  size=theme.base_size_cover_title, bold=True, color=theme.title_color)
    if slide.subtitle:
        _add_text_box(s, slide.subtitle, Inches(1), Inches(4.2),
                      Inches(11.3), Inches(1), theme, size=24, color=theme.muted_color)
    _add_accent_bar(s, theme)


def _draw_section_slide(s, slide: Slide, theme: Theme) -> None:
    _add_accent_bar(s, theme)
    _add_text_box(s, slide.title, Inches(1), Inches(3), Inches(11.3), Inches(1.5),
                  theme, size=40, bold=True, color=theme.title_color)
    if slide.bullets:
        _add_bullets(s, slide.bullets, theme, top=Inches(4.8), size=20, color=theme.muted_color)


def _draw_content_slide(s, slide: Slide, theme: Theme) -> None:
    _add_title_bar(s, slide.title, theme)
    if slide.bullets:
        _add_bullets(s, slide.bullets, theme, top=Inches(1.6))


def _draw_example_slide(s, slide: Slide, theme: Theme) -> None:
    _add_title_bar(s, slide.title or "例题", theme)
    y = Inches(1.6)
    if slide.question:
        _add_text_box(s, "【题目】" + slide.question, Inches(0.6), y,
                      Inches(12), Inches(1.4), theme, size=22, color=theme.text_color)
        y = Inches(3.0)
    if slide.solution_steps:
        _add_text_box(s, "【解答】", Inches(0.6), y, Inches(2), Inches(0.5),
                      theme, size=22, bold=True, color=theme.accent_color)
        _add_bullets(s, slide.solution_steps, theme, top=Inches(y.inches + 0.6), size=20)
    if slide.answer:
        _add_text_box(s, "答：" + slide.answer, Inches(0.6), Inches(6.4),
                      Inches(12), Inches(0.7), theme, size=22, bold=True, color=theme.accent_color)


def _draw_practice_slide(s, slide: Slide, theme: Theme) -> None:
    _add_title_bar(s, slide.title or "课堂练习", theme)
    if slide.question:
        _add_text_box(s, slide.question, Inches(0.6), Inches(1.8),
                      Inches(12), Inches(2), theme, size=24, color=theme.text_color)
    if slide.hint:
        _add_text_box(s, "提示 · " + slide.hint, Inches(0.6), Inches(6.2),
                      Inches(12), Inches(0.7), theme, size=18, color=theme.muted_color)


def _draw_interactive_slide(s, slide: Slide, theme: Theme) -> None:
    _add_title_bar(s, slide.title or "想一想", theme)
    if slide.question:
        _add_text_box(s, slide.question, Inches(0.6), Inches(2.0),
                      Inches(12), Inches(2), theme, size=28, bold=True, color=theme.title_color)
    if slide.bullets:
        _add_bullets(s, slide.bullets, theme, top=Inches(4.5), size=20)
    if slide.hint:
        _add_text_box(s, "提示：" + slide.hint, Inches(0.6), Inches(6.4),
                      Inches(12), Inches(0.7), theme, size=16, color=theme.muted_color)


def _add_title_bar(s, title: str, theme: Theme) -> None:
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if theme.rounded_corners else MSO_SHAPE.RECTANGLE
    bar = s.shapes.add_shape(shape_type, 0, 0, Inches(13.333), Inches(0.9))
    bar.fill.solid()
    bar.fill.fore_color.rgb = theme.title_color
    bar.line.fill.background()
    tf = bar.text_frame
    tf.margin_left = Inches(0.5)
    tf.margin_top = Inches(0.15)
    tf.text = title
    run = tf.paragraphs[0].runs[0]
    run.font.size = Pt(theme.base_size_title_bar)
    run.font.bold = True
    run.font.color.rgb = theme.title_bar_text_color
    run.font.name = theme.cn_font


def _add_accent_bar(s, theme: Theme) -> None:
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1), Inches(2.2),
                             Inches(0.15), Inches(2.5))
    bar.fill.solid()
    bar.fill.fore_color.rgb = theme.accent_color
    bar.line.fill.background()


def _add_text_box(s, text: str, left, top, width, height, theme: Theme,
                  size: int = 20, bold: bool = False, color: RGBColor | None = None) -> None:
    box = s.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.text = text
    p = tf.paragraphs[0]
    for run in p.runs:
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color or theme.text_color
        run.font.name = theme.cn_font


def _add_bullets(s, bullets: list[str], theme: Theme, top,
                  size: int | None = None, color: RGBColor | None = None) -> None:
    size = size or theme.base_size_bullet
    color = color or theme.text_color
    box = s.shapes.add_textbox(Inches(0.8), top, Inches(11.7), Inches(5.5))
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = "• " + item
        for run in p.runs:
            run.font.size = Pt(size)
            run.font.color.rgb = color
            run.font.name = theme.cn_font
        p.space_after = Pt(8)
