# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

面向**成都市小学数学教师**的本地 PPT 自动生成工具。输入"年级/学期/单元/课时 + PPT 类型"，输出可直接讲课用的 .pptx 文件。

- **学科**：仅小学数学。不要扩展到其他学科——会稀释知识库结构。
- **教材版本**：北师大版为主，一年级人教版为辅（成都市义务教育实际使用情况）。
- **生成引擎**：Claude Sonnet 4.6（model id：`claude-sonnet-4-6`），通过 Anthropic Python SDK 调用，启用 web search 工具按需补充生活化情境/拓展题。

## 常用命令

```bash
# 安装依赖（用 uv，比 pip 快）
uv sync

# 启动开发服务器（默认 http://127.0.0.1:8000）
uv run uvicorn app.main:app --reload

# 跑测试
uv run pytest                          # 全部
uv run pytest tests/test_render.py     # 单文件
uv run pytest -k "test_lesson_plan"    # 单用例
RUN_INTEGRATION=1 uv run pytest tests/integration/   # 端到端（会真调 Sonnet）

# 抓课程标准入库（一次性，只跑公开资源）
uv run python scripts/fetch_standards.py

# 加载示例课时（首次体验，免上传）
uv run python scripts/load_demo.py

# Lint / 格式化
uv run ruff check .
uv run ruff format .
```

环境变量：拷贝 `.env.example` → `.env`，至少设置 `ANTHROPIC_API_KEY`。

**Mock 模式**：设 `AIPPT_MOCK=true` 跳过 Sonnet 调用，直接返回示例 Deck。用途：
- 没 API key 时演示完整 UI 流程
- CI 跑端到端不烧钱
- 调前端 / 主题 / 渲染时不必等真生成

## 架构关键点

### 知识库不是数据库

`knowledge_base/` 是**纯文件目录**，不要引入 SQLite/向量库。所有结构靠 `knowledge_base/index.json` 维护：

```json
{
  "grade_4": {
    "term_2": {
      "unit_3": {
        "name": "小数加减法",
        "lessons": [
          {
            "id": "g4t2u3l1",
            "name": "买菜",
            "file": "textbooks/grade_4/term_2/unit_3/lesson_1.md",
            "knowledge_points": ["小数的意义", "小数加法"]
          }
        ]
      }
    }
  }
}
```

修改 KB 时**永远先读 index.json、再写**，避免并发覆盖。`app/services/kb.py` 是唯一改 index 的入口——别的模块不要直接写文件。

### Prompt 按 PPT 类型分文件

`app/prompts/*.md` 是 system prompt，每种 PPT 类型一个：`lesson_plan` / `knowledge_point` / `practice` / `interactive`。生成时由 `app/services/generate.py` 选择，再把课时正文 + 课程标准对应条目作为 user message 拼进去。

**修改 prompt 不要去 Python 字符串里改**，直接编辑 .md 文件，代码用 `Path.read_text()` 加载。这样调 prompt 的人不需要懂 Python。

### PPT 结构是 JSON，不是直接生成 pptx

Sonnet 永远返回 JSON（通过 tool use 的 structured output，schema 见 `app/models/slide.py`），由 `app/services/render.py` 翻译成 python-pptx 调用。**不要让 Sonnet 直接写 python-pptx 代码**——会出现引用不存在的母版占位符、动画 API 错用等问题。

### 动画/互动用 hint 而非真动画

python-pptx 对动画支持有限。`AnimationHint` 字段约定一套语义（如 `reveal_on_click`、`step_by_step`），render 时通过分页 + 隐藏文本占位符模拟。**不要尝试用 python-pptx 写真正的 PowerPoint 动画时间线 XML**，维护成本极高。

### 生成是异步的，前端轮询状态

`POST /generate` 立即返 `{run_id, status_url}`，真生成跑在 `BackgroundTasks` 里。状态写到 `runs/{run_id}/status.json`，前端 `setInterval(1500ms)` 拉 `GET /api/runs/{id}/status`。

状态机：`queued → thinking → rendering → done | error`。所有状态读写**只走 `app/services/runs.py`**，别的模块不要直接动 status.json。

### 视觉主题在 render.py 里，不要散在前端

`THEMES` dict 是单一来源：3 套预设（formal_blue / kids_warm / blackboard）。增主题就改 `render.py` 里的 `Theme` dataclass + 注册到 `THEMES`，前端 `/generate` 表单和 `/runs` 列表自动同步。Theme 类有 `*_hex` 属性把 RGBColor 转成 CSS 串供模板用。

### 预览页是 HTML 渲染，不是 PNG

`/runs/{id}/preview` 用 Jinja2 模板把 `deck.json` 渲染成 HTML mini-slides（每页 16:9 div + 旁边 notes 面板）。**不要尝试用 LibreOffice/PowerPoint headless 渲 PNG** — 太重，依赖复杂。HTML 预览跟 PPT 渲染有 1:1 的语义对应（同一份 deck 数据），只是视觉细节不同。

### 单页重生成走独立 tool schema

整 deck 重生成用 `emit_deck`，单页用 `emit_slide`（`SLIDE_TOOL_SCHEMA`）。单页调用更便宜、更快。修改诉求放老师备注里。变更走 `regenerate_single_slide()`，必须重渲整个 .pptx，并在 `runs/{id}/edits.jsonl` 留审计行。

### 学情自适应在 user message 里，不在 system prompt 里

`class_level` (advanced/normal/basic) 拼到每次调用的 user message，不要为不同学情写不同 system prompt — system prompt 数量爆炸，且对模型来说"动态情境信息"和"静态身份指令"应该分开。

### 数学示意图：Sonnet 出参数，后端画 PNG

Sonnet 不直接生成图片。它在 slide 里输出 `diagram` 字段（结构化参数），由 `app/services/diagrams.py` 用 Pillow 绘成 PNG 嵌入 pptx 和预览页。4 种类型：`number_line` / `area_model` / `fraction_bar` / `place_value_chart`。

**不要让 Sonnet 输出 SVG 或 base64 图片** — 它会胡编，且 token 浪费严重。结构化参数 + 后端确定性渲染才是正路。

加新 diagram 类型：在 `diagrams.py` 加新函数 + 在 `render_diagram()` 加分发；在 `_DIAGRAM_SCHEMA` 加字段；在 4 个 prompt 文件加使用提示。

### 批量生成走多个 BackgroundTasks，不走单进程串行

`/generate/batch` 把一个单元的 N 节课各 spawn 一个 `_pipeline` BackgroundTask。FastAPI BackgroundTasks 跑在线程池里，单机 4 并发足够。共享 `batch_id` 用于 `/api/batch/{id}/status` 聚合查询。完成后 `/api/batch/{id}/zip` 即时打包，不预生成。

不要引入 Celery/Redis；这个工具是单机本地的，BackgroundTasks 是合适尺寸。

### 成本追踪用 msg.usage，不要估算

Anthropic SDK 的 `client.messages.create(...).usage` 已经返回精确的 `input_tokens` / `output_tokens`。不要自己 tokenize 计算近似值。`app/services/pricing.py` 是单价单一来源，可由 env 覆盖 `AIPPT_INPUT_USD_PER_MTOK` / `AIPPT_OUTPUT_USD_PER_MTOK`。

### 教学反馈环：难点 → 澄清 PPT

老师在 preview 页标记某些 slide 为"难点"（存到 `runs/{id}/difficult.json`），点"生成澄清 PPT"会触发：把难点页的内容浓缩成 `extra_instructions`，spawn 新 run 跑 `lesson_plan` 流水线（强制 `class_level="basic"`，要求 6~10 页 + 多用 diagram）。新 run 的 `batch_id` 设为 `clarify_of_{原 run_id}`，便于追踪溯源。

不要为澄清搞独立 prompt — 复用 lesson_plan 加充分上下文比写一份新 prompt 维护成本低，且模型理解力足够。

### CJK 字体 fallback 链

`diagrams.py` 渲染中文优先用 `fonts/` 目录（用 `scripts/fetch_fonts.py` 下载 Noto Sans SC），其次系统字体（雅黑 / 苹方 / Noto / 文泉驿），最后兜底 DejaVu（无中文 → 方框）。CI 走 `apt-get install fonts-noto-cjk`。

### Prompt caching（M9）

system prompt + 课程标准节选会反复出现（batch 生成同单元 N 节课时一模一样）。`services/generate.py:_system_blocks()` 把它们作为 list-of-blocks 传，最后一块带 `cache_control: ephemeral`，命中 Anthropic prompt 缓存。

成本侧：`cache_creation_input_tokens` 按 1.25× input 单价，`cache_read_input_tokens` 按 0.10×。批量生成同单元 5 节课，理论上从第 2 节开始 ~70% 输入是缓存读。`RunStatus.cache_read_tokens` / `cache_write_tokens` 记录之，`pricing.estimate_cost()` 加权累计。

注意：mock 模式所有 cache token 为 0，测不到真行为，要等真 API 跑过 batch 验证缓存命中。

### parent_run_id：派生 run 的统一字段

澄清 PPT、单页重生成等"从已有 run 派生新 run"的场景统一用 `RunStatus.parent_run_id`。**不要再用 batch_id 兜底**（batch_id 专表"一次批量任务"的成员）。新加派生关系的功能也走 parent_run_id。

### 价格按 model_id 查表

`services/pricing.py:_PRICING` dict 按 model_id 索引 (input, output) 单价。新模型加一行；环境变量 `AIPPT_INPUT/OUTPUT_USD_PER_MTOK` 覆盖。`estimate_cost(..., model_id=settings.model)` 总是显式传 model，不依赖默认值。

### 每页 duration_minutes（M9）

`Slide.duration_minutes` 让 Sonnet 估算讲解时长，prompt 里给了每类页的参考值。整 deck 总和≈ 35~40 分钟（一节小学课）。render 时把 `⏱ ~X 分钟` 加到 PPT 备注栏顶部，preview 页显示总时长 + 单页时长 chip。

### M10 视觉规范

每种 slide type 有独特布局（不只是换 title bar 颜色）：

- **title**：左侧 4.5" 大色块 + 两个装饰圆 + 右侧大字标题
- **section**：大编号圆 + 标题 + 装饰线
- **content**：标题栏 + 左侧 accent 细条 + 大字 bullets 均匀分布
- **example**：题目卡（soft title 底色）→ 解答卡（accent 框）→ 答案条（accent 实色）三区分明
- **practice**：题目卡（soft accent + ?图标）+ 虚线答题留白框 + 💡 hint
- **interactive**：💭 图标 + 大字居中问题 + soft title 卡
- **summary**：1~N 编号圆 + 大五角星装饰

字号已普调：bullets 28、title bar 32、cover title 56（kids_warm 再加大）。每页有 footer（课题 + N/M 页码），封面除外。

布局靠 `_add_card / _add_title_bar / _add_footer / _add_textbox / _add_bullets_block / _add_numbered_steps` 这几个 helper 拼。新增 slide type 时尽量复用 helper，不要直接调 `s.shapes.add_*`。

`_draw_example_slide` 返回 sol_h 给上层用以定位 diagram（避免硬编码 y 位置导致重叠）。

`_add_numbered_steps` 按字号自动收紧行距（size≤13 line_spacing=1.05），防长解答溢出卡片。

### solution_steps 上限 4 步

prompt 已约束「最多 4 步，每步 ≤30 字」。render 也有兜底（5+ 步降到 12pt + 增高度），但希望源头出 ≤4。修改 prompt 时不要放松这条 — 经实测 5 步会出现卡片溢出。

### 联网搜索靠 Sonnet 的 web search 工具

不要自己写爬虫调搜索引擎。在 `app/services/generate.py` 里把 web_search 工具加进 tools 数组，让模型自主决定是否搜。搜什么、怎么用都由 prompt 控制。

唯一例外是 `scripts/fetch_standards.py`（一次性抓义务教育数学课程标准），跑一次就完事，可以直接 requests。

## 教材数据的边界

- 用户**手动上传**教材 PDF/图片，**不抓取教材正文**（版权问题）。
- 课程标准、教材目录、公开教案是公开资源，可联网获取。
- 如果用户问"能不能帮我下载 xx 教材"——拒绝，引导他自己扫描或拍照上传。

## 测试约定

- `tests/test_render.py` **不调 API**，只测 JSON → pptx 渲染。fixture 在 `tests/fixtures/sample_deck.json`。
- `tests/test_ingest.py` 用 `tests/fixtures/sample.pdf` 测解析切分。
- 调用 Sonnet 的端到端测试放在 `tests/integration/`，默认 skip，需要 `RUN_INTEGRATION=1` 才跑。
- **永远不要 mock python-pptx**——直接生成临时 .pptx 然后读回来断言。

## 不要做的事

- 不要把 PPT 模板硬编码在 Python 里——用 `pptx_assets/template.pptx` 母版。
- 不要给小学数学之外的学段/学科加支持，除非用户明确要求扩展。
- 不要在 KB 里存教材正文以外的衍生数据（如生成历史、用户配置），那些放别的目录（如 `runs/`）。
- 不要静默吞 Sonnet 的 tool_use 错误，把 `stop_reason` 透传给前端，方便调试。
- 不要让 Sonnet 直接生成图片（SVG/base64） — 输出 diagram 参数让后端画。
- 不要为了"动画看起来真"去写 PPT 动画时间线 XML — 分页模拟够用。
- 不要在 `/runs` 列表跑 PNG 缩略图渲染 — CSS 占位卡片够用，PNG 渲染依赖 LibreOffice。
