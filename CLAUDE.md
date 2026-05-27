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
