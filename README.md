# aippt

面向**成都市小学数学教师**的本地 PPT 自动生成工具。输入"年级 / 学期 / 单元 / 课时 + PPT 类型"，自动产出可直接讲课用的 .pptx。

## 特性

- 4 种 PPT 类型：课时教案、知识点专项、练习题集、映射教学（含动画/互动 hint）
- 教材正文由老师手动上传（避开版权风险），课程标准/公开教案联网抓取
- 调用 Claude Sonnet 4.6 生成，按需用 web search 找生活化情境/拓展题
- 纯本地 Web 应用，浏览器开 http://127.0.0.1:8000 就能用

## 快速开始

```bash
# 1. 安装 uv（如未安装）
# Windows PowerShell:
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. 安装依赖
uv sync

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 ANTHROPIC_API_KEY

# 4. 启动
uv run uvicorn app.main:app --reload

# 5. 浏览器打开 http://127.0.0.1:8000
```

## 工作流

1. **上传教材**：在"教材上传"页选择 PDF/图片，标注年级/学期/单元/课时，系统自动切分入库
2. **抓取课程标准**（一次性）：`uv run python scripts/fetch_standards.py`
3. **生成 PPT**：在"生成"页选课时和 PPT 类型，提交后 10~30 秒可下载

## 项目结构

详见 [CLAUDE.md](./CLAUDE.md)。

## 教材版权说明

本工具**不抓取、不分发**任何受版权保护的教材正文。教材文件由用户在本机自行扫描或拍照上传，仅存储在用户本地 `knowledge_base/textbooks/`，不会上传到任何远程服务。
