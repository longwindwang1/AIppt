"""把 samples/lessons/ 下的示例课时复制到 knowledge_base/，让首次安装就能用。

跑法：
    python scripts/load_demo.py            # 加载所有示例
    python scripts/load_demo.py --reset    # 先清空 KB 再加载（小心，会删用户已上传的）

也可以通过 HTTP 调用：POST /api/kb/load_demo
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services import kb as kb_service  # noqa: E402

SAMPLES_ROOT = Path(__file__).resolve().parent.parent / "samples" / "lessons"


def load_all() -> list[dict]:
    """返回新增的 lesson 列表。"""
    added: list[dict] = []
    for unit_dir in sorted(SAMPLES_ROOT.iterdir()):
        if not unit_dir.is_dir():
            continue
        manifest_path = unit_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        unit = manifest["unit"]
        for les in manifest["lessons"]:
            content = (unit_dir / les["file"]).read_text(encoding="utf-8")
            # 已在 KB 中则跳过
            existing = kb_service.get_lesson_content(
                grade=unit["grade"], term=unit["term"],
                unit_name=unit["unit_name"], lesson_name=les["name"],
            )
            if existing.strip():
                continue
            lesson = kb_service.add_lesson(
                grade=unit["grade"],
                term=unit["term"],
                unit_index=unit["unit_index"],
                unit_name=unit["unit_name"],
                lesson_name=les["name"],
                content=content,
                knowledge_points=les["knowledge_points"],
            )
            added.append(lesson)
    return added


def reset_kb() -> None:
    """清空 KB（仅 textbooks 和 index）。standards 不动。"""
    import shutil
    if settings.textbooks_dir.exists():
        shutil.rmtree(settings.textbooks_dir)
    settings.textbooks_dir.mkdir(parents=True, exist_ok=True)
    settings.index_path.write_text("{}", encoding="utf-8")


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    if "--reset" in sys.argv:
        reset_kb()
        print("[reset] 已清空 textbooks/ 和 index.json")

    added = load_all()
    print(f"已加载 {len(added)} 节示例课时：")
    for les in added:
        print(f"  - {les['id']}: {les['name']}")
    if not added:
        print("（无新增——示例课时已在 KB 中。用 --reset 强制重新加载。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
