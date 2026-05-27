"""运行历史 + 状态机。

每个 run 在 runs/{run_id}/ 下有：
  status.json   — 实时状态：stage / message / result / error / timestamps
  deck.json     — Sonnet 返回的 Deck 结构（done 时才有）
  *.pptx        — 渲染好的文件（done 时才有）

状态机：
  queued → thinking → rendering → done
                              ↘  error
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings

Stage = Literal["queued", "thinking", "rendering", "done", "error"]


class RunStatus(BaseModel):
    run_id: str
    stage: Stage = "queued"
    message: str = "排队中…"
    progress: float = 0.0                  # 0.0 ~ 1.0，用于前端进度条
    created_at: str = Field(default_factory=lambda: _now_iso())
    updated_at: str = Field(default_factory=lambda: _now_iso())
    elapsed_sec: float = 0.0

    # 请求信息（done/error 后供 /runs 列表展示）
    deck_type: str = ""
    grade: int = 0
    term: int = 0
    unit_name: str = ""
    lesson_name: str = ""
    theme: str = "formal_blue"
    batch_id: str = ""                     # 属于哪个 batch（单生成则为空）

    # 成功结果
    deck_title: str = ""
    slide_count: int = 0
    pptx_filename: str = ""

    # 成本（mock 模式为 0）
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0           # M9: prompt caching 命中
    cache_write_tokens: int = 0          # M9: 写入缓存（第一次跑某 system prompt）
    cost_usd: float = 0.0

    # M9: 重构 — 来源 run（澄清 PPT / 单页重生成都可用）
    parent_run_id: str = ""

    # 失败信息
    error: str = ""
    stop_reason: str = ""

    def pptx_url(self) -> str:
        if self.stage == "done" and self.pptx_filename:
            return f"/download/{self.run_id}/{self.pptx_filename}"
        return ""


def _now_iso() -> str:
    # microseconds 精度，避免同秒内多次 init 排序失稳
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


def _status_path(run_id: str) -> Path:
    return settings.runs_dir / run_id / "status.json"


def init(run_id: str, **fields) -> RunStatus:
    """创建 run 目录 + 写初始 status。"""
    (settings.runs_dir / run_id).mkdir(parents=True, exist_ok=True)
    status = RunStatus(run_id=run_id, **fields)
    write(status)
    return status


def write(status: RunStatus) -> None:
    status.updated_at = _now_iso()
    # elapsed_sec 实时算
    try:
        created = datetime.fromisoformat(status.created_at)
        updated = datetime.fromisoformat(status.updated_at)
        status.elapsed_sec = round((updated - created).total_seconds(), 2)
    except Exception:
        pass
    path = _status_path(status.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(status.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def read(run_id: str) -> RunStatus | None:
    path = _status_path(run_id)
    if not path.exists():
        return None
    try:
        return RunStatus.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def update(run_id: str, **changes) -> RunStatus | None:
    """读 - 改 - 写。stage 切换时自动更新 message 默认值。"""
    status = read(run_id)
    if not status:
        return None
    for k, v in changes.items():
        setattr(status, k, v)
    write(status)
    return status


def list_all() -> list[RunStatus]:
    """按 updated_at 倒序返回所有 run。"""
    if not settings.runs_dir.exists():
        return []
    out: list[RunStatus] = []
    for d in settings.runs_dir.iterdir():
        if not d.is_dir():
            continue
        s = read(d.name)
        if s:
            out.append(s)
    out.sort(key=lambda s: s.updated_at, reverse=True)
    return out


def delete(run_id: str) -> bool:
    import shutil
    d = settings.runs_dir / run_id
    if not d.exists():
        return False
    shutil.rmtree(d)
    return True


def count() -> int:
    return len(list_all())


def find_batch(batch_id: str) -> list[RunStatus]:
    return [s for s in list_all() if s.batch_id == batch_id]


def total_cost_usd() -> float:
    return round(sum(s.cost_usd for s in list_all()), 4)


def total_tokens() -> tuple[int, int]:
    """返回累计 (input, output) token。"""
    items = list_all()
    return sum(s.input_tokens for s in items), sum(s.output_tokens for s in items)
