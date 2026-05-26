"""调用 Claude Sonnet 生成 Deck。

约定：
- system prompt 从 app/prompts/<deck_type>.md 加载（不要把 prompt 硬编码在这里）
- 通过 tool_use 强制结构化输出，schema 来自 models.slide.DECK_TOOL_SCHEMA
- web_search 工具默认开启，由 settings.enable_web_search 控制
- 失败时透传 stop_reason，不要静默吞错
- AIPPT_MOCK=1 时跳过 Sonnet，返回示例 Deck（CI / 无 key 演示用）
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic
from anthropic.types import Message

from app.config import PROJECT_ROOT, settings
from app.models.slide import DECK_TOOL_SCHEMA, Deck


@dataclass
class GenerationRequest:
    deck_type: str          # lesson_plan / knowledge_point / practice / interactive
    grade: int
    term: int
    unit_name: str
    lesson_name: str
    lesson_content: str     # 教材正文（用户上传后从 KB 取）
    standard_excerpt: str = ""   # 对应课程标准条目（可选）
    extra_instructions: str = "" # 老师自由备注（如"重点讲方法 X"）


class GenerationError(RuntimeError):
    def __init__(self, message: str, stop_reason: str | None = None, raw: Message | None = None):
        super().__init__(message)
        self.stop_reason = stop_reason
        self.raw = raw


def _load_prompt(deck_type: str) -> str:
    path = settings.prompts_dir / f"{deck_type}.md"
    if not path.exists():
        raise GenerationError(f"未找到 PPT 类型 {deck_type} 对应的 prompt 文件: {path}")
    return path.read_text(encoding="utf-8")


def _build_user_message(req: GenerationRequest) -> str:
    parts = [
        f"年级：{req.grade}",
        f"学期：{'上册' if req.term == 1 else '下册'}",
        f"单元：{req.unit_name}",
        f"课时：{req.lesson_name}",
        f"PPT 类型：{req.deck_type}",
        "",
        "## 课时正文（来自老师上传的教材）",
        req.lesson_content.strip() or "（老师尚未上传该课时教材，请基于课程标准和你自身知识生成）",
    ]
    if req.standard_excerpt.strip():
        parts += ["", "## 对应课程标准条目", req.standard_excerpt.strip()]
    if req.extra_instructions.strip():
        parts += ["", "## 老师备注", req.extra_instructions.strip()]
    parts += ["", "请调用 emit_deck 工具输出 PPT 结构。"]
    return "\n".join(parts)


def _tools() -> list[dict]:
    tools: list[dict] = [DECK_TOOL_SCHEMA]
    if settings.enable_web_search:
        tools.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 3,
        })
    return tools


def _extract_deck(msg: Message) -> Deck:
    """从 Sonnet 响应中找出 emit_deck tool_use 块。"""
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_deck":
            return Deck.model_validate(block.input)
    raise GenerationError(
        f"Sonnet 未调用 emit_deck 工具。stop_reason={msg.stop_reason}",
        stop_reason=msg.stop_reason,
        raw=msg,
    )


_MOCK_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "sample_deck.json"


def _generate_mock(req: GenerationRequest) -> Deck:
    """Mock 模式：从 fixture 读 Deck，把请求字段替换进去。"""
    if not _MOCK_FIXTURE.exists():
        raise GenerationError(f"Mock fixture 不存在：{_MOCK_FIXTURE}")
    raw = json.loads(_MOCK_FIXTURE.read_text(encoding="utf-8"))
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


def generate_deck(req: GenerationRequest) -> Deck:
    """同步调用 Sonnet，返回解析后的 Deck。Mock 模式跳过 Sonnet。"""
    if settings.mock:
        return _generate_mock(req)

    if not settings.anthropic_api_key:
        raise GenerationError("未配置 ANTHROPIC_API_KEY，请在 .env 中填写；或设 AIPPT_MOCK=1 走示例")

    client = Anthropic(api_key=settings.anthropic_api_key)
    system = _load_prompt(req.deck_type)
    user = _build_user_message(req)

    msg = client.messages.create(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=system,
        tools=_tools(),
        tool_choice={"type": "tool", "name": "emit_deck"} if not settings.enable_web_search else {"type": "auto"},
        messages=[{"role": "user", "content": user}],
    )

    # web_search 可能让模型先 search 再 emit_deck，必要时多轮
    if msg.stop_reason == "tool_use" and not _has_emit_deck(msg):
        msg = _continue_until_deck(client, system, user, msg)

    return _extract_deck(msg)


def _has_emit_deck(msg: Message) -> bool:
    return any(
        getattr(b, "type", None) == "tool_use" and b.name == "emit_deck"
        for b in msg.content
    )


def _continue_until_deck(client: Anthropic, system: str, user: str, msg: Message,
                          max_rounds: int = 4) -> Message:
    """处理 web_search 多轮：把 search 结果反馈回去，直到模型调用 emit_deck。"""
    history: list[dict] = [
        {"role": "user", "content": user},
        {"role": "assistant", "content": msg.content},
    ]

    for _ in range(max_rounds):
        # 收集所有 server-side tool_use 的 tool_use_id（web_search 是 server tool，
        # 结果已经回流到 content 里；我们这里其实不需要回 tool_result。
        # 但如果 Sonnet 还在等更多 server tool 轮次，let it run）
        # 简化处理：如果它没产出 emit_deck，再发一条 user 消息催它。
        history.append({
            "role": "user",
            "content": "请基于已搜索到的信息，立即调用 emit_deck 工具输出 PPT 结构。",
        })
        msg = client.messages.create(
            model=settings.model,
            max_tokens=settings.max_tokens,
            system=system,
            tools=_tools(),
            messages=history,
        )
        if _has_emit_deck(msg):
            return msg
        history.append({"role": "assistant", "content": msg.content})

    return msg


def save_deck_json(deck: Deck, run_dir: Path) -> Path:
    """把生成的 Deck JSON 也存一份到 runs/，方便调试。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "deck.json"
    path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    return path
