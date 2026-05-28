"""真接 Sonnet 生成 五下《长方体的体积》课时教案 PPT。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
os.environ.setdefault("AIPPT_MOCK", "false")

from app.config import settings  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

if not settings.anthropic_api_key:
    print("[error] 没读到 ANTHROPIC_API_KEY")
    sys.exit(1)

from scripts import load_demo  # noqa: E402
added = load_demo.load_all()
print(f"[init] +{len(added)} 节示例课时")

from app.services import kb as kb_service  # noqa: E402
from app.services.generate import GenerationRequest, generate_deck  # noqa: E402
from app.services.pricing import estimate_cost  # noqa: E402
from app.services.render import render  # noqa: E402

LESSON = "长方体的体积"
req = GenerationRequest(
    deck_type="lesson_plan",
    grade=5, term=2,
    unit_name="长方体（二）",
    lesson_name=LESSON,
    lesson_content=kb_service.get_lesson_content(
        grade=5, term=2, unit_name="长方体（二）", lesson_name=LESSON,
    ),
    standard_excerpt=kb_service.get_standard_for_grade(5),
    extra_instructions="本课重点是公式推导（摆小正方体），可多用 area_model 类型的 diagram 模拟单位正方体；让学生体会从数小正方体到用公式计算的抽象过程。",
    class_level="normal",
)
print(f"课时正文 {len(req.lesson_content)} 字符 / 标准 {len(req.standard_excerpt)} 字符")
print(f"模型 {settings.model} / 主题 kids_warm")
print()
t0 = time.time()
deck, usage = generate_deck(req)
print(f"[ok] 生成 {time.time()-t0:.1f}s")
print(f"页数 {len(deck.slides)}  时长合计 {sum(s.duration_minutes for s in deck.slides):.1f} min")
print(f"diagram 用 {sum(1 for s in deck.slides if s.diagram)} 处  "
      f"动画 {sum(1 for s in deck.slides if s.animation.value != 'none')} 处")

out_dir = settings.runs_dir / "real_demo_changfangti"
out_dir.mkdir(parents=True, exist_ok=True)
out_dir.joinpath("deck.json").write_text(deck.model_dump_json(indent=2), encoding="utf-8")
pptx = render(deck, out_path=out_dir / f"{LESSON}.pptx", theme_key="kids_warm")
print(f"PPTX {pptx} ({pptx.stat().st_size // 1024} KB)")

cost = estimate_cost(usage.input_tokens, usage.output_tokens,
                     usage.cache_read_tokens, usage.cache_write_tokens,
                     model_id=settings.model)
print(f"Token in={usage.input_tokens} out={usage.output_tokens} "
      f"cache_r={usage.cache_read_tokens} cache_w={usage.cache_write_tokens}  ${cost}")
