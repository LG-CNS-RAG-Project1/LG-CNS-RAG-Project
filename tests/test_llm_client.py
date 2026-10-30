from types import SimpleNamespace

import pytest

import src.llm_client as llm_client
from src.retrieval import market_search


@pytest.fixture(autouse=True)
def avoid_repository_environment(monkeypatch):
    monkeypatch.setattr(llm_client, "load_dotenv", lambda *_args, **_kwargs: None)


def test_ollama_client_uses_local_openai_compatible_endpoint(monkeypatch):
    captured = {}
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/")
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    monkeypatch.setattr(
        llm_client, "OpenAI", lambda **kwargs: captured.update(kwargs) or kwargs
    )

    client = llm_client.get_openai_client()

    assert client == {
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
    }
    assert llm_client.llm_is_configured()


def test_provider_selects_ollama_models_and_separate_index(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "bge-m3")

    assert llm_client.chat_model("gpt-4o-mini") == "qwen3:8b"
    assert llm_client.embedding_model() == "bge-m3"
    assert llm_client.local_chroma_path(tmp_path) == tmp_path / "ollama" / "bge-m3"
    assert llm_client.embedding_collection_name("patents") == "patents_ollama_bge-m3"


def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert not llm_client.llm_is_configured()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm_client.get_openai_client()


def test_embed_texts_uses_selected_ollama_model_and_batches(monkeypatch):
    calls = []

    class Embeddings:
        def create(self, *, model, input):
            calls.append((model, input))
            return SimpleNamespace(
                data=[
                    SimpleNamespace(embedding=[float(index)])
                    for index, _ in enumerate(input)
                ]
            )

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setattr(market_search, "EMBED_BATCH_SIZE", 2)
    monkeypatch.setattr(
        market_search,
        "get_openai_client",
        lambda: SimpleNamespace(embeddings=Embeddings()),
    )

    vectors = market_search.embed_texts(["a", "b", "c"])

    assert [model for model, _ in calls] == ["bge-m3", "bge-m3"]
    assert [texts for _, texts in calls] == [["a", "b"], ["c"]]
    assert len(vectors) == 3
