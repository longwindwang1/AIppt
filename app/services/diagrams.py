"""数学示意图生成 — 纯 Pillow，无 cairo / matplotlib 依赖。

Sonnet 输出结构化参数（Diagram model），后端绘制成 PNG，嵌入 PPT / 预览页。

4 种支持的图：
- number_line: 数轴（标记若干点 + 可选标签）
- area_model: 面积模型（横竖切分的方格，部分着色）
- fraction_bar: 分数条（一根矩形条等分，部分着色）
- place_value_chart: 数位表（个十百千 / 十分位百分位千分位）

设计原则：
- 输入参数纯粹（数字、列表），不含样式
- 颜色用浅色调，保证小学课堂可读性
- 中文字体走系统默认（msyh.ttc on Windows / PingFang on macOS / DejaVu fallback）
"""
from __future__ import annotations

import io
import platform
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1200
HEIGHT = 480
MARGIN = 60
BG = (255, 255, 255)
LINE = (47, 84, 121)         # 深蓝
ACCENT = (232, 116, 34)      # 橙
SHADED = (255, 226, 192)     # 浅橙填充
TEXT = (40, 40, 40)


PROJECT_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"


def _cn_font(size: int) -> ImageFont.FreeTypeFont:
    """中文字体多级 fallback。

    优先级：
    1. 项目自带 fonts/ 目录（用 scripts/fetch_fonts.py 下载）
    2. 系统字体（Windows / macOS / Linux 常见路径）
    3. Pillow 默认（DejaVu，无中文 → 方框）
    """
    candidates: list[Path] = []

    # 1. 项目自带（首选，跨平台一致）
    if PROJECT_FONTS_DIR.exists():
        for ext in ("*.ttf", "*.ttc", "*.otf"):
            candidates += sorted(PROJECT_FONTS_DIR.glob(ext))

    # 2. 系统字体
    sysname = platform.system().lower()
    if sysname == "windows":
        candidates += [
            Path(r"C:\Windows\Fonts\msyh.ttc"),
            Path(r"C:\Windows\Fonts\msyh.ttf"),
            Path(r"C:\Windows\Fonts\simhei.ttf"),
        ]
    elif sysname == "darwin":
        candidates += [
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/Library/Fonts/Songti.ttc"),
        ]
    else:
        # Linux：Noto / 文泉驿 / DejaVu
        candidates += [
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]

    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _blank(width: int = WIDTH, height: int = HEIGHT) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (width, height), BG)
    return img, ImageDraw.Draw(img)


# --- 数轴 -------------------------------------------------------------------

def number_line(start: float, end: float, marks: list[float] | None = None,
                 labels: list[str] | None = None, step: float | None = None,
                 width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """画一条 [start, end] 的数轴，标记若干点。

    Args:
        start, end: 数轴左右端点
        marks: 要标星的位置列表
        labels: 与 marks 对应的标签（不够长则用 mark 数值）
        step: 主刻度间隔（默认自动算）
    """
    img, draw = _blank(width, height)
    y = height // 2

    # 主线
    draw.line([(MARGIN, y), (width - MARGIN, y)], fill=LINE, width=3)
    # 箭头
    draw.polygon([(width - MARGIN, y - 8), (width - MARGIN + 14, y), (width - MARGIN, y + 8)], fill=LINE)

    if end <= start:
        end = start + 1
    span = end - start
    if step is None:
        # 取使刻度数 5~10 的整数 step
        for cand in [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]:
            if span / cand <= 12:
                step = cand
                break
        else:
            step = span / 10

    font = _cn_font(20)
    font_label = _cn_font(22)

    # 主刻度
    x_count = 0
    cur = start
    while cur <= end + 1e-9 and x_count < 50:
        ratio = (cur - start) / span
        x = MARGIN + ratio * (width - 2 * MARGIN)
        draw.line([(x, y - 8), (x, y + 8)], fill=LINE, width=2)
        text = f"{cur:g}"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text((x - tw / 2, y + 14), text, fill=TEXT, font=font)
        cur += step
        x_count += 1

    # 标记点
    marks = marks or []
    for i, m in enumerate(marks):
        ratio = (m - start) / span
        x = MARGIN + ratio * (width - 2 * MARGIN)
        r = 12
        draw.ellipse([(x - r, y - r), (x + r, y + r)], fill=ACCENT, outline=LINE, width=2)
        label = labels[i] if labels and i < len(labels) else f"{m:g}"
        bbox = draw.textbbox((0, 0), label, font=font_label)
        tw = bbox[2] - bbox[0]
        draw.text((x - tw / 2, y - 50), label, fill=ACCENT, font=font_label)

    return img


# --- 面积模型 ---------------------------------------------------------------

def area_model(rows: int, cols: int, shaded: int = 0,
                width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """rows × cols 网格，前 shaded 个格子涂色。"""
    img, draw = _blank(width, height)
    rows = max(1, min(rows, 20))
    cols = max(1, min(cols, 20))
    cell_size = min((width - 2 * MARGIN) // cols, (height - 2 * MARGIN) // rows)
    grid_w = cols * cell_size
    grid_h = rows * cell_size
    ox = (width - grid_w) // 2
    oy = (height - grid_h) // 2

    total = rows * cols
    shaded = max(0, min(shaded, total))
    for i in range(rows):
        for j in range(cols):
            x0 = ox + j * cell_size
            y0 = oy + i * cell_size
            idx = i * cols + j
            fill = SHADED if idx < shaded else BG
            draw.rectangle([(x0, y0), (x0 + cell_size, y0 + cell_size)],
                           fill=fill, outline=LINE, width=2)

    font = _cn_font(28)
    caption = f"{shaded} / {total}"
    bbox = draw.textbbox((0, 0), caption, font=font)
    cw = bbox[2] - bbox[0]
    draw.text(((width - cw) / 2, oy + grid_h + 10), caption, fill=TEXT, font=font)
    return img


# --- 分数条 ------------------------------------------------------------------

def fraction_bar(parts: int, shaded: int = 0,
                  width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """长条等分 parts 份，前 shaded 份涂色。"""
    img, draw = _blank(width, height)
    parts = max(1, min(parts, 24))
    shaded = max(0, min(shaded, parts))

    bar_h = 120
    bar_w = width - 2 * MARGIN
    part_w = bar_w / parts
    y0 = (height - bar_h) // 2

    for i in range(parts):
        x0 = MARGIN + i * part_w
        x1 = MARGIN + (i + 1) * part_w
        fill = SHADED if i < shaded else BG
        draw.rectangle([(x0, y0), (x1, y0 + bar_h)], fill=fill, outline=LINE, width=2)

    font = _cn_font(36)
    caption = f"{shaded}/{parts}"
    bbox = draw.textbbox((0, 0), caption, font=font)
    cw = bbox[2] - bbox[0]
    draw.text(((width - cw) / 2, y0 + bar_h + 20), caption, fill=ACCENT, font=font)
    return img


# --- 数位表 ------------------------------------------------------------------

_PLACE_NAMES = ["千", "百", "十", "个", "·", "十分位", "百分位", "千分位"]


def place_value_chart(value: float | str, width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    """画一张数位表，把 value 的各位填进去。

    支持 value 是 number 或字符串（"23.45"），最多 4 整数位 + 3 小数位。
    """
    img, draw = _blank(width, height)
    s = str(value).strip()
    if "." in s:
        int_part, dec_part = s.split(".", 1)
    else:
        int_part, dec_part = s, ""

    int_digits = list(int_part[-4:].rjust(4, " "))   # 千百十个
    dec_digits = list(dec_part[:3].ljust(3, " "))    # 十分百分千分

    cells = [
        ("千", int_digits[0]), ("百", int_digits[1]),
        ("十", int_digits[2]), ("个", int_digits[3]),
        (".", "."),
        ("十分位", dec_digits[0]), ("百分位", dec_digits[1]), ("千分位", dec_digits[2]),
    ]

    cell_w = (width - 2 * MARGIN) // len(cells)
    cell_h = 80
    y_head = (height - 2 * cell_h) // 2
    y_val = y_head + cell_h

    font_head = _cn_font(22)
    font_val = _cn_font(40)

    for i, (name, digit) in enumerate(cells):
        x0 = MARGIN + i * cell_w
        is_point = name == "."
        # 表头
        if not is_point:
            draw.rectangle([(x0, y_head), (x0 + cell_w, y_head + cell_h)],
                           fill=(241, 245, 249), outline=LINE, width=2)
        bbox = draw.textbbox((0, 0), name, font=font_head)
        nw = bbox[2] - bbox[0]
        draw.text((x0 + (cell_w - nw) / 2, y_head + (cell_h - 22) / 2), name, fill=LINE, font=font_head)

        # 数值
        if not is_point:
            draw.rectangle([(x0, y_val), (x0 + cell_w, y_val + cell_h)],
                           fill=BG, outline=LINE, width=2)
        d = digit if digit.strip() else ""
        if is_point:
            d = "."
        bbox = draw.textbbox((0, 0), d, font=font_val)
        dw = bbox[2] - bbox[0]
        draw.text((x0 + (cell_w - dw) / 2, y_val + (cell_h - 50) / 2), d,
                  fill=ACCENT if d.strip() else TEXT, font=font_val)

    return img


# --- 分发 -------------------------------------------------------------------

def render_diagram(diagram: dict) -> Image.Image:
    """按 diagram.type 分发到具体生成器。

    Raises ValueError if type 未知 / 参数非法。
    """
    if not isinstance(diagram, dict) or "type" not in diagram:
        raise ValueError("diagram 缺少 type 字段")

    dtype = diagram["type"]
    if dtype == "number_line":
        return number_line(
            start=float(diagram.get("start", diagram.get("range", [0, 10])[0])),
            end=float(diagram.get("end", diagram.get("range", [0, 10])[1])),
            marks=[float(m) for m in diagram.get("marks", [])],
            labels=[str(l) for l in diagram.get("labels", [])] or None,
            step=float(diagram["step"]) if "step" in diagram else None,
        )
    if dtype == "area_model":
        return area_model(
            rows=int(diagram.get("rows", 4)),
            cols=int(diagram.get("cols", 4)),
            shaded=int(diagram.get("shaded", 0)),
        )
    if dtype == "fraction_bar":
        return fraction_bar(
            parts=int(diagram.get("parts", 4)),
            shaded=int(diagram.get("shaded", 0)),
        )
    if dtype == "place_value_chart":
        return place_value_chart(value=diagram.get("value", 0))
    raise ValueError(f"未知 diagram type: {dtype}")


def render_diagram_png_bytes(diagram: dict) -> bytes:
    img = render_diagram(diagram)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
