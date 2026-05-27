"""测 4 种 diagram 渲染器。"""
from __future__ import annotations

from PIL import Image

from app.services import diagrams


def test_number_line_with_marks():
    img = diagrams.number_line(start=0, end=10, marks=[3.5, 7.0], labels=["A", "B"])
    assert isinstance(img, Image.Image)
    assert img.size[0] > 100 and img.size[1] > 100


def test_area_model_grid():
    img = diagrams.area_model(rows=3, cols=4, shaded=5)
    assert isinstance(img, Image.Image)


def test_area_model_clamps_oversize():
    """rows/cols 越界要被夹到合理范围，不能崩。"""
    img = diagrams.area_model(rows=100, cols=100, shaded=99999)
    assert isinstance(img, Image.Image)


def test_fraction_bar():
    img = diagrams.fraction_bar(parts=5, shaded=2)
    assert isinstance(img, Image.Image)


def test_place_value_chart_decimal():
    img = diagrams.place_value_chart("23.45")
    assert isinstance(img, Image.Image)


def test_place_value_chart_integer():
    img = diagrams.place_value_chart(1234)
    assert isinstance(img, Image.Image)


def test_render_diagram_dispatch():
    for d in [
        {"type": "number_line", "start": 0, "end": 5, "marks": [2.5]},
        {"type": "area_model", "rows": 2, "cols": 4, "shaded": 3},
        {"type": "fraction_bar", "parts": 6, "shaded": 4},
        {"type": "place_value_chart", "value": "23.45"},
    ]:
        img = diagrams.render_diagram(d)
        assert isinstance(img, Image.Image)


def test_render_diagram_unknown_type():
    import pytest
    with pytest.raises(ValueError):
        diagrams.render_diagram({"type": "alien_thing"})


def test_render_diagram_png_bytes():
    png = diagrams.render_diagram_png_bytes(
        {"type": "fraction_bar", "parts": 4, "shaded": 1}
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 200
