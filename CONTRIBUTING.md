# 贡献指南

欢迎一起把这个工具做得更好。本项目面向**小学数学教师**，所以贡献时请优先考虑：

1. **教师的使用体验**：每个改动想象一个对技术不太熟悉的老师怎么用
2. **数学教学正确性**：算理、术语、例题难度梯度——比"AI 跑通了"更重要
3. **教材版权安全**：永远不要把教材正文写进代码 / fixture / 测试

---

## 开发环境

```bash
git clone git@github.com:longwindwang1/AIppt.git
cd AIppt
uv sync --extra dev
cp .env.example .env
# 编辑 .env 填入 ANTHROPIC_API_KEY，或设 AIPPT_MOCK=true 走 mock 模式

# 启动开发服务器
uv run uvicorn app.main:app --reload

# 跑测试
uv run pytest tests/ -v
```

---

## 改 prompt（不需要会 Python）

教学法或生成内容质量改进，主要是改 `app/prompts/*.md`：

- `lesson_plan.md` — 课时教案
- `knowledge_point.md` — 知识点专项
- `practice.md` — 练习题集
- `interactive.md` — 映射教学（互动/动画）

改完后用 mock 模式 + 真实 API key 各跑一次同一课时，对比输出差异。

---

## 改前端

- 模板：`app/templates/*.html`（Jinja2）
- 样式：`static/style.css`（单文件，没用预处理器）
- 没有构建步骤——保存即生效

---

## 改后端 / 加功能

提交前请：

1. `uv run pytest tests/ -v` 全绿
2. `uv run ruff check .` 无错误
3. 新功能配测试（按 `tests/test_app.py` 的端到端模式，用 mock 模式跑）
4. 不要 mock python-pptx——直接渲染临时文件验证

新功能涉及架构变化时，更新 `CLAUDE.md`。

---

## Commit 风格

简短中英文皆可。建议前缀：

- `feat:` 新功能
- `fix:` bug 修复
- `prompt:` prompt 调优
- `ui:` 前端 / 样式
- `docs:` 文档
- `test:` 测试
- `chore:` 杂项 / CI / 依赖

---

## 不要做的事

- 不要把任何教材正文 commit 进 repo（包括 fixtures 和测试样本）
- 不要在代码里硬编码 API key
- 不要静默吞 Sonnet 的错误——透传 stop_reason 给前端
- 不要给小学数学之外的学段 / 学科加支持，除非项目方向变化
