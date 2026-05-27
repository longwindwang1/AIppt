"""调用 Claude Sonnet 生成 Deck。

约定：
- system prompt 从 app/prompts/<deck_type>.md 加载（不要把 prompt 硬编码在这里）
- 通过 tool_use 强制结构化输出，schema 来自 models.slide.DECK_TOOL_SCHEMA
- web_search 工具默认开启，由 settings.enable_web_search 控制
- 失败时透传 stop_reason，不要静默吞错
- AIPPT_MOCK=1 时跳过 Sonnet，按 deck_type 返回不同示例 Deck
- 学情自适应：req.class_level 控制难度方向
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic
from anthropic.types import Message

from app.config import PROJECT_ROOT, settings
from app.models.slide import DECK_TOOL_SCHEMA, SLIDE_TOOL_SCHEMA, Deck, Slide


@dataclass
class GenerationRequest:
    deck_type: str
    grade: int
    term: int
    unit_name: str
    lesson_name: str
    lesson_content: str
    standard_excerpt: str = ""
    extra_instructions: str = ""
    class_level: str = "normal"      # advanced / normal / basic


class GenerationError(RuntimeError):
    def __init__(self, message: str, stop_reason: str | None = None, raw: Message | None = None):
        super().__init__(message)
        self.stop_reason = stop_reason
        self.raw = raw


_MOCK_DECKS_PATH = PROJECT_ROOT / "samples" / "mock_decks.json"


def _load_mock_decks() -> dict:
    if not _MOCK_DECKS_PATH.exists():
        # 兜底：用 fixture
        fixture = PROJECT_ROOT / "tests" / "fixtures" / "sample_deck.json"
        return {"lesson_plan": json.loads(fixture.read_text(encoding="utf-8"))}
    return json.loads(_MOCK_DECKS_PATH.read_text(encoding="utf-8"))


def _generate_mock(req: GenerationRequest) -> Deck:
    """Mock 模式：按 deck_type 选不同样本 deck，注入用户请求的元数据。"""
    decks = _load_mock_decks()
    raw = decks.get(req.deck_type) or decks.get("lesson_plan") or next(iter(decks.values()))
    raw = dict(raw)   # 浅拷贝避免污染
    raw["grade"] = req.grade
    raw["term"] = req.term
    raw["unit_name"] = req.unit_name
    raw["lesson_name"] = req.lesson_name
    raw["deck_type"] = req.deck_type
    type_label = {
        "lesson_plan": "课时教案",
        "knowledge_point": "知识点专项",
        "practice": "练习题集",
        "interactive": "映射教学",
    }.get(req.deck_type, req.deck_type)
    raw["title"] = f"[Mock] {req.unit_name} · {req.lesson_name}（{type_label}）"
    return Deck.model_validate(raw)


def _load_prompt(deck_type: str) -> str:
    path = settings.prompts_dir / f"{deck_type}.md"
    if not path.exists():
        raise GenerationError(f"未找到 PPT 类型 {deck_type} 对应的 prompt 文件: {path}")
    return path.read_text(encoding="utf-8")


_CLASS_LEVEL_GUIDE = {
    "advanced": "本班学情：拔尖班。例题难度上调一档，至少留 1 个有挑战的拓展题；少给具体提示，多让学生自主发现规律。",
    "normal": "本班学情：普通班。难度适中，例题 + 变式 + 一个略具挑战题。",
    "basic": "本班学情：基础班。例题难度下调，每步骤拆得更细，多用 reveal_on_click 让讲解节奏放慢，提示语言更具体。",
}


def _build_user_message(req: GenerationRequest) -> str:
    parts = [
        f"年级：{req.grade}",
        f"学期：{'上册' if req.term == 1 else '下册'}",
        f"单元：{req.unit_name}",
        f"课时：{req.lesson_name}",
        f"PPT 类型：{req.deck_type}",
        f"学情：{_CLASS_LEVEL_GUIDE.get(req.class_level, _CLASS_LEVEL_GUIDE['normal'])}",
        "",
        "## 课时正文（来自老师上传的教材）",
        req.lesson_content.strip() or "（老师尚未上传该课时教材，请基于课程标准和你自身知识生成）",
    ]
    if req.extra_instructions.strip():
        parts += ["", "## 老师备注", req.extra_instructions.strip()]
    parts += [
        "",
        "请调用 emit_deck 工具输出 PPT 结构。",
        "",
        "**重要 (避免 JSON 解析失败)**：",
        "1. slides 字段必须是**原生 JSON 数组**，不要把它作为 JSON 字符串嵌入",
        "2. 所有文本字段（title / notes / bullets 等）中不要使用半角引号 \" 包裹词语",
        "   - 错误示例：notes 中写 \"用'买菜'引入\"，应改为：用「买菜」引入",
        "3. 引用学生口语时用中文引号「」或单引号 '，不要用 \"",
    ]
    return "\n".join(parts)


def _system_blocks(deck_type: str, standard_excerpt: str = "") -> list[dict]:
    """构造 system 参数（list of blocks），最后一块带 cache_control 以启用 prompt 缓存。

    system_prompt + standard_excerpt 在批量生成同单元时反复出现，缓存命中能省 ~70% 输入 token。
    """
    system_prompt = _load_prompt(deck_type)
    blocks: list[dict] = [{"type": "text", "text": system_prompt}]
    if standard_excerpt.strip():
        blocks.append({
            "type": "text",
            "text": "\n\n## 课程标准节选\n\n" + standard_excerpt.strip(),
        })
    # 最后一块标 cache_control = ephemeral；之前的块默认随之缓存
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _tools(extra: list[dict] | None = None) -> list[dict]:
    tools: list[dict] = list(extra or [])
    if settings.enable_web_search:
        tools.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 3,
        })
    return tools


def _extract_tool_input(msg: Message, tool_name: str) -> dict:
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            # debug：把原始 input 写到 /tmp 方便排查复杂结构异常
            try:
                import os, tempfile
                if os.getenv("AIPPT_DEBUG_DUMP"):
                    dump = Path(tempfile.gettempdir()) / "aippt_last_tool_input.json"
                    dump.write_text(json.dumps(block.input, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            return block.input
    raise GenerationError(
        f"Sonnet 未调用 {tool_name} 工具。stop_reason={msg.stop_reason}",
        stop_reason=msg.stop_reason,
        raw=msg,
    )


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __iadd__(self, other: "Usage") -> "Usage":
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        return self


def _usage_from(msg: Message) -> Usage:
    u = msg.usage
    return Usage(
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


def generate_deck(req: GenerationRequest) -> tuple[Deck, Usage]:
    """同步调用 Sonnet，返回 (Deck, Usage)。Mock 模式 usage 全 0。"""
    if settings.mock:
        return _generate_mock(req), Usage()

    if not settings.anthropic_api_key:
        raise GenerationError("未配置 ANTHROPIC_API_KEY，请在 .env 中填写；或设 AIPPT_MOCK=1 走示例")

    client = Anthropic(api_key=settings.anthropic_api_key)
    system = _system_blocks(req.deck_type, req.standard_excerpt)
    user = _build_user_message(req)

    tool_choice = (
        {"type": "auto"}
        if settings.enable_web_search
        else {"type": "tool", "name": "emit_deck"}
    )

    msg = client.messages.create(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=system,
        tools=_tools([DECK_TOOL_SCHEMA]),
        tool_choice=tool_choice,
        messages=[{"role": "user", "content": user}],
    )

    usage = _usage_from(msg)

    if msg.stop_reason == "tool_use" and not _has_tool(msg, "emit_deck"):
        msg = _continue_until(client, system, user, msg, "emit_deck",
                              tools=_tools([DECK_TOOL_SCHEMA]))
        usage += _usage_from(msg)

    deck, retry_usage = _validate_or_retry(client, system, user, msg, max_retries=1)
    usage += retry_usage
    return deck, usage


def _validate_or_retry(client: Anthropic, system: list[dict] | str, user: str,
                        msg: Message, max_retries: int = 1) -> tuple[Deck, Usage]:
    """尝试解析 emit_deck.input；失败则重新提示 Sonnet 修复。"""
    from pydantic import ValidationError

    history: list[dict] = [
        {"role": "user", "content": user},
        {"role": "assistant", "content": msg.content},
    ]
    extra_usage = Usage()

    for attempt in range(max_retries + 1):
        try:
            return Deck.model_validate(_extract_tool_input(msg, "emit_deck")), extra_usage
        except (ValidationError, ValueError) as e:
            if attempt >= max_retries:
                raise GenerationError(
                    f"Sonnet 输出无法解析为 Deck，已重试 {attempt} 次：{e}",
                    stop_reason=msg.stop_reason, raw=msg,
                )
            # 重新提示
            history.append({
                "role": "user",
                "content": (
                    "你上次输出的 emit_deck.slides 不是合法 JSON 数组——很可能"
                    "把 slides 作为 JSON 字符串返回了，或者 notes/title 中嵌了"
                    "未转义的半角双引号。\n\n"
                    "**请重新调用 emit_deck**：\n"
                    "1. slides 一定是原生 array，不是字符串\n"
                    "2. 所有字符串值里不要用半角引号 \" 包裹任何词，用「」或单引号 '\n"
                    "3. 例如：错的 \"notes\": \"先用\\\"买菜\\\"引入\"，对的 "
                    "\"notes\": \"先用「买菜」引入\""
                ),
            })
            msg = client.messages.create(
                model=settings.model,
                max_tokens=settings.max_tokens,
                system=system,
                tools=_tools([DECK_TOOL_SCHEMA]),
                tool_choice={"type": "tool", "name": "emit_deck"},
                messages=history,
            )
            extra_usage += _usage_from(msg)
            history.append({"role": "assistant", "content": msg.content})

    # 不会到这里（max_retries 后会 raise）
    raise GenerationError("validation loop logic error")


def _has_tool(msg: Message, name: str) -> bool:
    return any(
        getattr(b, "type", None) == "tool_use" and b.name == name
        for b in msg.content
    )


def _continue_until(client: Anthropic, system: str, user: str, msg: Message,
                     target_tool: str, tools: list[dict], max_rounds: int = 4) -> Message:
    history: list[dict] = [
        {"role": "user", "content": user},
        {"role": "assistant", "content": msg.content},
    ]
    for _ in range(max_rounds):
        history.append({
            "role": "user",
            "content": f"请基于已搜索到的信息，立即调用 {target_tool} 工具输出结果。",
        })
        msg = client.messages.create(
            model=settings.model,
            max_tokens=settings.max_tokens,
            system=system,
            tools=tools,
            messages=history,
        )
        if _has_tool(msg, target_tool):
            return msg
        history.append({"role": "assistant", "content": msg.content})
    return msg


# --- 单页重生成 -----------------------------------------------------------


_SLIDE_REGEN_SYSTEM = """你是一位资深小学数学教师。任务：重新生成一份已存在 PPT 中的某一页。

注意：
- 必须调用 emit_slide 工具输出**单页**结构
- 保持整体风格 / 难度梯度与原 deck 一致
- 老师的修改诉求（用户消息中"修改要求"）优先级最高
- 不要改变 slide 的 type，除非用户明确要求
"""


def _mock_regenerate_slide(req: GenerationRequest, deck: Deck, idx: int) -> Slide:
    """Mock 模式：把指示词附到 notes 末尾，title 加 [已修订]。"""
    s = deck.slides[idx].model_copy()
    s.title = f"[已修订] {s.title}" if s.title else "[已修订]"
    note_suffix = f"\n\n[修订指示] {req.extra_instructions}" if req.extra_instructions else "\n\n[已模拟重生成]"
    s.notes = (s.notes or "") + note_suffix
    return s


def regenerate_single_slide(req: GenerationRequest, deck: Deck, idx: int) -> tuple[Slide, Usage]:
    """重新生成 deck 第 idx 页。返回 (Slide, Usage)。"""
    if settings.mock:
        return _mock_regenerate_slide(req, deck, idx), Usage()

    if not settings.anthropic_api_key:
        raise GenerationError("未配置 ANTHROPIC_API_KEY")

    client = Anthropic(api_key=settings.anthropic_api_key)
    original = deck.slides[idx]
    user = "\n".join([
        f"# 整 deck 上下文（共 {len(deck.slides)} 页）",
        f"课题：{deck.title}",
        f"PPT 类型：{deck.deck_type}",
        f"学情：{_CLASS_LEVEL_GUIDE.get(req.class_level, '')}",
        "",
        f"# 需要重生成的是第 {idx + 1} 页（从 1 计数）",
        "## 原始页结构",
        original.model_dump_json(indent=2, exclude_defaults=True),
        "",
        "## 同 deck 中前后页的标题（保持衔接）",
        *(f"- 第 {i+1} 页: {s.title or s.type} ({s.type})" for i, s in enumerate(deck.slides)),
        "",
        "## 修改要求",
        req.extra_instructions or "（无具体要求，请按原页主题重新生成，质量更好的版本）",
        "",
        "请调用 emit_slide 工具输出新的单页结构。",
    ])

    msg = client.messages.create(
        model=settings.model,
        max_tokens=2048,
        system=_SLIDE_REGEN_SYSTEM,
        tools=[SLIDE_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "emit_slide"},
        messages=[{"role": "user", "content": user}],
    )

    slide = Slide.model_validate(_extract_tool_input(msg, "emit_slide"))
    return slide, _usage_from(msg)


def save_deck_json(deck: Deck, run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "deck.json"
    path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    return path
