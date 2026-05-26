"""测教材文件解析。仅测 txt/md（PDF 单测依赖二进制 fixture，端到端再测）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import ingest


def test_extract_txt(tmp_path: Path):
    f = tmp_path / "lesson.txt"
    f.write_text("一年级数学 数一数", encoding="utf-8")
    assert ingest.extract_text(f) == "一年级数学 数一数"


def test_extract_md(tmp_path: Path):
    f = tmp_path / "lesson.md"
    f.write_text("# 标题\n\n正文内容", encoding="utf-8")
    text = ingest.extract_text(f)
    assert "正文内容" in text


def test_unsupported_format(tmp_path: Path):
    f = tmp_path / "x.docx"
    f.write_bytes(b"PK")
    with pytest.raises(ValueError, match="不支持的文件类型"):
        ingest.extract_text(f)
