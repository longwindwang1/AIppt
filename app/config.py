"""环境变量、路径常量的单一来源。其他模块不要直接读 os.environ。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="AIPPT_",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    model: str = "claude-sonnet-4-6"
    host: str = "127.0.0.1"
    port: int = 8000
    enable_web_search: bool = True
    max_tokens: int = 8192
    mock: bool = False                 # AIPPT_MOCK=1 时不调 Sonnet，返回示例 Deck

    @property
    def kb_dir(self) -> Path:
        return PROJECT_ROOT / "knowledge_base"

    @property
    def textbooks_dir(self) -> Path:
        return self.kb_dir / "textbooks"

    @property
    def standards_dir(self) -> Path:
        return self.kb_dir / "standards"

    @property
    def index_path(self) -> Path:
        return self.kb_dir / "index.json"

    @property
    def runs_dir(self) -> Path:
        return PROJECT_ROOT / "runs"

    @property
    def template_pptx(self) -> Path:
        return PROJECT_ROOT / "pptx_assets" / "template.pptx"

    @property
    def prompts_dir(self) -> Path:
        return PROJECT_ROOT / "app" / "prompts"


def load_settings() -> Settings:
    s = Settings()
    # 读 ANTHROPIC_API_KEY 时没有 AIPPT_ 前缀，单独处理
    import os
    if not s.anthropic_api_key:
        s.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    return s


settings = load_settings()
