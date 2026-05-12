from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: Literal["vllm", "ollama", "openai", "mock"] = "mock"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "local-dev-key"
    llm_model: str = "Qwen2.5-72B-Instruct-AWQ"
    llm_temperature: float = 0.1

    # LLM Gateway (LiteLLM)
    llm_gateway_enabled: bool = False
    litellm_base_url: str = "http://localhost:4000"
    litellm_master_key: str = "sk-master-dev-1234"
    litellm_virtual_key: str = "sk-app-dev-1234"
    litellm_model_large: str = "vehicle-finance-large"
    litellm_model_small: str = "vehicle-finance-small"
    litellm_model_guard: str = "vehicle-finance-guard"
    llm_request_timeout_s: int = 30
    enable_cloud_fallback: bool = False

    # Embeddings
    embedding_provider: Literal["hash", "sentence-transformers"] = "hash"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # Vector store
    vectorstore: Literal["faiss", "qdrant"] = "faiss"
    qdrant_url: str = "http://localhost:6333"

    # Database
    database_url: str = "sqlite:///./vehicle_finance.db"

    # Security
    pii_log_masking: bool = True
    audit_log_path: str = "./audit.log"

    # Server
    app_host: str = "0.0.0.0"
    app_port: int = 8080


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
