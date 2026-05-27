"""真接 Sonnet 跑一次端到端，观察实际产出，作为 M9→M10 迭代输入。

跑法：python scripts/smoke_real_api.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
# 强制读 .env
os.environ.setdefault("AIPPT_MOCK", "false")

from app.config import settings  # noqa: E402

if not settings.anthropic_api_key:
    print("[error] 没读到 ANTHROPIC_API_KEY，检查 .env")
    sys.exit(1)

# 控制台 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

print(f"模型：{settings.model}")
print(f"Web search: {settings.enable_web_search}")
print(f"Mock: {settings.mock}")
print()

# 1. 加载示例课时
from scripts import load_demo  # noqa: E402
added = load_demo.load_all()
print(f"已加载示例课时：{len(added)}")

# 2. 直接调 generate_deck（绕 FastAPI）
from app.services import kb as kb_service  # noqa: E402
from app.services.generate import GenerationRequest, generate_deck  # noqa: E402
from app.services.render import render  # noqa: E402

req = GenerationRequest(
    deck_type="lesson_plan",
    grade=4, term=2,
    unit_name="小数加减法",
    lesson_name="买菜",
    lesson_content=kb_service.get_lesson_content(
        grade=4, term=2, unit_name="小数加减法", lesson_name="买菜"
    ),
    standard_excerpt=kb_service.get_standard_for_grade(4),
    extra_instructions="",
    class_level="normal",
)
print(f"课时正文长度：{len(req.lesson_content)} 字符")
print(f"课程标准长度：{len(req.standard_excerpt)} 字符")
print()
print("→ 调 Sonnet（约 20~40 秒）…")
t0 = time.time()
deck, usage = generate_deck(req)
elapsed = time.time() - t0
print(f"[ok] 生成完成 {elapsed:.1f}s")
print()

# 3. 报告
print("=" * 60)
print("【实际产出 vs M1-M9 假设】")
print("=" * 60)
print(f"标题：{deck.title}")
print(f"slides 数：{len(deck.slides)}")
slide_types = [s.type.value for s in deck.slides]
print(f"slide 类型分布：{dict((t, slide_types.count(t)) for t in set(slide_types))}")

durations = [s.duration_minutes for s in deck.slides]
print(f"\nduration_minutes:")
print(f"  非零页数：{sum(1 for d in durations if d > 0)} / {len(durations)}")
print(f"  总时长：{sum(durations):.1f} 分钟")
print(f"  各页：{[round(d, 1) for d in durations]}")

diagrams_used = [(i, s.diagram.get('type')) for i, s in enumerate(deck.slides) if s.diagram]
print(f"\ndiagram 字段:")
if diagrams_used:
    for i, dt in diagrams_used:
        print(f"  第 {i+1} 页: {dt} {deck.slides[i].diagram}")
else:
    print("  无 — Sonnet 没主动加图")

animations = [(i, s.animation.value) for i, s in enumerate(deck.slides) if s.animation.value != "none"]
print(f"\n动画:")
for i, anim in animations:
    print(f"  第 {i+1} 页: {anim}")

notes_lens = [len(s.notes) for s in deck.slides]
print(f"\nnotes 长度：均 {sum(notes_lens)/len(notes_lens):.0f} 字，最长 {max(notes_lens)}，最短 {min(notes_lens)}")
empty_notes = sum(1 for n in notes_lens if n < 10)
print(f"  几乎空的 notes：{empty_notes} 页")

print(f"\nToken / 成本:")
print(f"  输入：{usage.input_tokens}")
print(f"  输出：{usage.output_tokens}")
print(f"  cache_read：{usage.cache_read_tokens}")
print(f"  cache_write：{usage.cache_write_tokens}")
from app.services.pricing import estimate_cost
cost = estimate_cost(usage.input_tokens, usage.output_tokens,
                     usage.cache_read_tokens, usage.cache_write_tokens,
                     model_id=settings.model)
print(f"  成本：${cost}")

# 4. 渲染 pptx 看大小
out_dir = settings.runs_dir / "smoke_real"
out_dir.mkdir(parents=True, exist_ok=True)
pptx_path = render(deck, out_path=out_dir / "smoke.pptx", theme_key="formal_blue")
print(f"\nPPTX：{pptx_path} ({pptx_path.stat().st_size // 1024} KB)")

# 5. 存 deck.json 备查
deck_path = out_dir / "deck.json"
deck_path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
print(f"Deck JSON：{deck_path}")
