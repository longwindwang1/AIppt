"""跨学科测试：人教版七下历史《盛唐气象》。

当前 prompt 是为小学数学调的，这里用 extra_instructions 显式切到历史模式。
"""
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

LESSON = "盛唐气象"

# 强力 extra_instructions —— 显式告诉 Sonnet 这是历史课，不是数学
HISTORY_OVERRIDE = """\
⚠️ **重要：本次生成的是 中国古代史 课程，不是数学课。请忽略 system prompt 中关于'小学数学/算术/数轴'等数学相关指引。**

学科调整为初中历史（中国古代史 · 唐朝），生成规则改为：

1. **不要**使用 diagram 字段（diagram 是数学示意图，历史课用不上）
2. **不要**用 solution_steps、answer 字段（这些是数学例题用）
3. example 类型的 slide 用作"史料分析"：question 放史料引文/史实问题，notes 写讲解思路
4. practice 类型：题目以材料题、思考题、连线题为主
5. interactive 类型：开放性问题（"为什么...？"、"如何看待..."）
6. **学情按初一**：用词不要太小儿化，但保持生动；可以引诗句、可以联系学生生活
7. **不要**用"成都"等小学数学课的本地化情境（这是历史课，情境就是历史本身）
8. 时间线、人物关系、事件因果是核心；适当用 bullets 列举（如盛唐三大诗人对比）
9. **保留** duration_minutes 字段（初中一节课 45 分钟）

PPT 类型为课时教案：导入 → 经济繁荣 → 民族交融 → 社会风气 → 文学艺术 → 讨论 → 小结。建议 10~14 页，总时长 35~40 分钟（留 5 分钟讨论）。
"""

req = GenerationRequest(
    deck_type="lesson_plan",
    grade=7, term=2,
    unit_name="隋唐时期：繁荣与开放的时代",
    lesson_name=LESSON,
    lesson_content=kb_service.get_lesson_content(
        grade=7, term=2,
        unit_name="隋唐时期：繁荣与开放的时代",
        lesson_name=LESSON,
    ),
    standard_excerpt="",   # 数学课程标准不适用，留空
    extra_instructions=HISTORY_OVERRIDE,
    class_level="normal",
)
print(f"课时正文 {len(req.lesson_content)} 字符")
print(f"模型 {settings.model} / 主题 formal_blue（历史适合正式蓝）")
print()
t0 = time.time()
deck, usage = generate_deck(req)
print(f"[ok] 生成 {time.time()-t0:.1f}s")
print(f"页数 {len(deck.slides)}  时长合计 {sum(s.duration_minutes for s in deck.slides):.1f} min")
print(f"slide 类型：" + ", ".join(s.type.value for s in deck.slides))
print(f"diagram 用 {sum(1 for s in deck.slides if s.diagram)} 处  "
      f"动画 {sum(1 for s in deck.slides if s.animation.value != 'none')} 处")

out_dir = settings.runs_dir / "real_demo_history"
out_dir.mkdir(parents=True, exist_ok=True)
out_dir.joinpath("deck.json").write_text(deck.model_dump_json(indent=2), encoding="utf-8")
pptx = render(deck, out_path=out_dir / f"{LESSON}.pptx", theme_key="formal_blue")
print(f"PPTX {pptx} ({pptx.stat().st_size // 1024} KB)")

cost = estimate_cost(usage.input_tokens, usage.output_tokens,
                     usage.cache_read_tokens, usage.cache_write_tokens,
                     model_id=settings.model)
print(f"Token in={usage.input_tokens} out={usage.output_tokens} "
      f"cache_r={usage.cache_read_tokens} cache_w={usage.cache_write_tokens}  ${cost}")
