"""教材文件解析：PDF → 文本。

设计：
- 主路径用 pypdf 提文字层；若文字层近乎为空（扫描件），返回空串让上层提示用户。
- OCR fallback 是 optional 依赖（pytesseract），未安装则跳过。
- 不抓教材正文，只解析用户上传的本地文件。
"""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    text = "\n".join(c.strip() for c in chunks if c.strip())
    return text


def extract_text(path: Path) -> str:
    """识别格式后分发。返回纯文本。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = extract_text_from_pdf(path)
        if len(text) >= 50:
            return text
        return _ocr_fallback(path) or text
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".png", ".jpg", ".jpeg"}:
        return _ocr_fallback(path) or ""
    raise ValueError(f"不支持的文件类型: {suffix}（支持 .pdf .txt .md .png .jpg）")


def _ocr_fallback(path: Path) -> str:
    """需要 pip install pytesseract pillow + 系统安装 tesseract-ocr-chi-sim。"""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    if path.suffix.lower() == ".pdf":
        # PDF 扫描件需要先转图片，这里不强求依赖 pdf2image/poppler，留 hook
        return ""

    try:
        return pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")
    except Exception:
        return ""
