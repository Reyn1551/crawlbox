"""Konfigurasi dari .env."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False
    app_secret_key: str = "change-me"
    database_url: str = "sqlite+aiosqlite:///./data/sentiment.db"
    crawler_max_concurrency: int = 10
    crawler_request_timeout: int = 30
    crawler_max_depth: int = 2
    crawler_delay_seconds: float = 0.5
    crawler_respect_robots: bool = True
    crawler_use_playwright: bool = False
    proxy_url: str | None = None
    nlp_device: str = "cpu"
    nlp_model_path: str = "./models/indobert-sentiment"
    nlp_confidence_threshold: float = 0.75
    nlp_batch_size: int = 8
    nlp_max_text_length: int = 512
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 300
    export_dir: str = "./data/exports"
    log_level: str = "INFO"
    log_file: str | None = None
    @property
    def data_dir(self) -> Path: return Path("./data")
    @property
    def has_llm(self) -> bool: return bool(self.openai_api_key)

settings = Settings()