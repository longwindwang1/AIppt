"""真接 Sonnet 给「里程表（二）」生成完整 PPT，给用户看效果。"""
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

# 1. 把新课时加入 KB
from scripts import load_demo  # noqa: E402
added = load_demo.load_all()
print(f"[init] 加载示例课时：{len(added)} 节新增")

# 2. 调真 API
from app.services import kb as kb_service  # noqa: E402
from app.services.generate import GenerationRequest, generate_deck  # noqa: E402
from app.services.pricing import estimate_cost  # noqa: E402
from app.services.render import render  # noqa: E402

LESSON_NAME = "里程表（二）"
print(f"\n[gen] 生成《{LESSON_NAME}》课时教案 PPT")
print(f"  模型: {settings.model}")
print(f"  web_search: {settings.enable_web_search}")
print(f"  主题: kids_warm（适合三年级）")

req = GenerationRequest(
    deck_type="lesson_plan",
    grade=3, term=1,
    unit_name="加与减",
    lesson_name=LESSON_NAME,
    lesson_content=kb_service.get_lesson_content(
        grade=3, term=1, unit_name="加与减", lesson_name=LESSON_NAME,
    ),
    standard_excerpt=kb_service.get_standard_for_grade(3),
    extra_instructions="本课是数轴 / 线段图教学的好机会，请多用 number_line 类型的 diagram 展示里程关系。",
    class_level="normal",
)
print(f"  课时正文长度: {len(req.lesson_content)} 字符")
print(f"  课程标准长度: {len(req.standard_excerpt)} 字符")
print()
t0 = time.time()
deck, usage = generate_deck(req)
elapsed = time.time() - t0
print(f"[ok] 生成 {elapsed:.1f}s")

# 3. 渲染
out_dir = settings.runs_dir / "real_demo_licheng"
out_dir.mkdir(parents=True, exist_ok=True)
pptx = render(deck, out_path=out_dir / f"{LESSON_NAME}.pptx", theme_key="kids_warm")
deck_json = out_dir / "deck.json"
deck_json.write_text(deck.model_dump_json(indent=2), encoding="utf-8")

# 4. 报告
print("\n" + "=" * 60)
print(f"【《{LESSON_NAME}》生成结果】")
print("=" * 60)
print(f"标题: {deck.title}")
print(f"页数: {len(deck.slides)}")

types = [s.type.value for s in deck.slides]
print(f"\n各页结构:")
for i, s in enumerate(deck.slides):
    extras = []
    if s.diagram:
        extras.append(f"📊 {s.diagram.get('type')}")
    if s.animation.value != "none":
        extras.append(f"🎬 {s.animation.value}")
    extras.append(f"⏱{s.duration_minutes}min")
    print(f"  {i+1:2}. [{s.type.value:11}] {s.title[:40]:42}  {' '.join(extras)}")

print(f"\n时长合计: {sum(s.duration_minutes for s in deck.slides):.1f} 分钟")
diagrams_used = [s.diagram for s in deck.slides if s.diagram]
print(f"diagram 使用: {len(diagrams_used)} 处，类型: {[d.get('type') for d in diagrams_used]}")

print(f"\nToken: input {usage.input_tokens} / output {usage.output_tokens}"
      f" / cache_read {usage.cache_read_tokens} / cache_write {usage.cache_write_tokens}")
cost = estimate_cost(usage.input_tokens, usage.output_tokens,
                     usage.cache_read_tokens, usage.cache_write_tokens,
                     model_id=settings.model)
print(f"成本: ${cost}")
print(f"\nPPTX: {pptx} ({pptx.stat().st_size // 1024} KB)")
print(f"Deck: {deck_json}")
