# fonts/

数学示意图（`app/services/diagrams.py`）渲染中文需要 CJK 字体。

## 哪些环境需要

- **Windows / macOS**：系统自带（微软雅黑 / 苹方），**不需要**手动下载
- **Linux 无 CJK 字体**：渲染的图里中文会成方框，需要装字体
- **CI**：CI 走 `apt-get install fonts-noto-cjk`，也不需要这里的字体

## 怎么装

```bash
# 推荐：脚本下载 Noto Sans SC（思源黑体简体，SIL OFL 协议）
python scripts/fetch_fonts.py
```

或手动从 [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) 下载 `NotoSansSC-Regular.otf` 放到本目录。

## 为什么不打包到仓库

字体文件 4~5 MB，且 OFL 协议要求保留 LICENSE。让用户按需下载更清爽。
