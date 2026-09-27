"""Load model connection settings only on the backend."""

from pathlib import Path

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ENV_FILE, ENV_FILE.with_name('.deepseek.env')),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    model_name: str = ""
    llm_timeout_seconds: float = Field(default=120, ge=5, le=600)
    llm_max_retries: int = Field(default=1, ge=0, le=5)
    llm_max_output_tokens: int = Field(default=4096, ge=512, le=16384)
    llm_disable_thinking: bool = True
    agent_max_rounds: int = Field(default=8, ge=2, le=16)
    agent_max_tool_calls: int = Field(default=20, ge=1, le=40)
    agent_max_repeat_calls: int = Field(default=2, ge=1, le=3)
    agent_total_timeout_seconds: float = Field(default=240, ge=10, le=600)
    llm_context_window: int = Field(default=65536, ge=8192, le=65536)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    notes_concurrency: int = Field(default=1, ge=1, le=3)
    notes_queue_capacity: int = Field(default=20, ge=1, le=100)
    notes_data_directory: Path | None = None
    notes_default_provider: Literal['local', 'deepseek'] = 'local'
    deepseek_api_key: SecretStr = SecretStr('')
    deepseek_base_url: str = 'https://api.deepseek.com'
    deepseek_model: str = ''
    notes_deepseek_request_limit: int = Field(default=40, ge=0, le=40)

    @property
    def missing_fields(self) -> list[str]:
        missing = []
        if not self.llm_base_url.strip():
            missing.append("LLM_BASE_URL")
        if not self.llm_api_key.get_secret_value().strip():
            missing.append("LLM_API_KEY")
        if not self.model_name.strip():
            missing.append("MODEL_NAME")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_fields
