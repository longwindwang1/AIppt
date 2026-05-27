"""下载思源黑体 / Noto Sans SC 到本地 fonts/ 目录。

为什么需要：Linux 默认无 CJK 字体时，diagrams.py 渲染的图里中文会成方框。
本机用 Windows 雅黑 / macOS 苹方就够了，这个脚本主要给 Linux 用户和 CI 用。

跑法：
    python scripts/fetch_fonts.py

下载源：Google Fonts CDN（公开 CDN，OFL 协议字体）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"

# Noto Sans SC Regular（思源黑体简体 Regular）— SIL OFL 1.1
# 直接拿 Google Fonts 提供的稳定 woff2 不行（PIL 不支持），需要 .otf/.ttf
# 用 GitHub 上 Google 的 noto-cjk 仓库 release（CC-BY-SA-OFL 协议）
URL = "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"
TARGET = "NotoSansSC-Regular.otf"


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    target = FONTS_DIR / TARGET

    if target.exists() and target.stat().st_size > 100_000:
        print(f"[ok] {target} 已存在（{target.stat().st_size // 1024} KB），跳过。")
        return 0

    print(f"下载 {URL}\n→ {target}\n（首次约 4~5MB，可能需 10~30 秒）")
    try:
        with httpx.Client(follow_redirects=True, timeout=60) as c:
            r = c.get(URL)
            r.raise_for_status()
            target.write_bytes(r.content)
        print(f"[ok] 已写入 {target} ({target.stat().st_size // 1024} KB)")
    except Exception as e:
        print(f"[error] 下载失败：{e}")
        print("替代方案：手动到 https://github.com/notofonts/noto-cjk 下载 NotoSansSC-Regular.otf"
              f" 放到 {FONTS_DIR}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
