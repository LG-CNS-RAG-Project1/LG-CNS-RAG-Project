"""OpenAI와 Ollama의 호환 API 설정을 공통으로 관리한다."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_CHAT_MODEL = "qwen3:4b"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "bge-m3"


def load_llm_settings() -> str:
    """환경 설정을 읽고 선택된 provider를 반환한다."""
    load_dotenv(ROOT_DIR / ".env")
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "ollama"}:
        raise ValueError("LLM_PROVIDER must be openai or ollama")
    return provider


def llm_is_configured() -> bool:
    """선택된 LLM provider에 필요한 연결 설정이 있는지 확인한다."""
    provider = load_llm_settings()
    if provider == "ollama":
        return bool(os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip())
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def get_openai_client() -> OpenAI:
    """선택된 provider의 OpenAI 호환 클라이언트를 만든다."""
    provider = load_llm_settings()
    if provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip()
        if not base_url:
            raise RuntimeError("OLLAMA_BASE_URL is required when LLM_PROVIDER=ollama")
        return OpenAI(
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key=os.getenv("OLLAMA_API_KEY", "ollama").strip() or "ollama",
        )

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    return OpenAI(api_key=api_key)


def chat_model(openai_default: str) -> str:
    """선택된 provider에 맞는 채팅 모델명을 반환한다."""
    if load_llm_settings() == "ollama":
        return (
            os.getenv("OLLAMA_CHAT_MODEL", DEFAULT_OLLAMA_CHAT_MODEL).strip()
            or DEFAULT_OLLAMA_CHAT_MODEL
        )
    return os.getenv("OPENAI_CHAT_MODEL", openai_default).strip() or openai_default


def embedding_model(openai_default: str = "text-embedding-3-small") -> str:
    """선택된 provider에 맞는 임베딩 모델명을 반환한다."""
    if load_llm_settings() == "ollama":
        return (
            os.getenv("OLLAMA_EMBEDDING_MODEL", DEFAULT_OLLAMA_EMBEDDING_MODEL).strip()
            or DEFAULT_OLLAMA_EMBEDDING_MODEL
        )
    return os.getenv("OPENAI_EMBEDDING_MODEL", openai_default).strip() or openai_default


def local_chroma_path(path: Path) -> Path:
    """Ollama 임베딩을 OpenAI 벡터와 분리해 저장할 로컬 경로를 반환한다."""
    if load_llm_settings() != "ollama":
        return path
    model = embedding_model().replace(":", "-").replace("/", "-")
    return path / "ollama" / model


def embedding_collection_name(name: str) -> str:
    """원격 Chroma 컬렉션을 임베딩 provider와 모델별로 구분한다."""
    if load_llm_settings() != "ollama":
        return name
    model = embedding_model().replace(":", "-").replace("/", "-")
    suffix = f"_ollama_{model}"
    return name if name.endswith(suffix) else f"{name}{suffix}"
