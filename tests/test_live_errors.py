from frontend.live import friendly_error


def test_connection_error_identifies_configured_ollama_server(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    connection_error = type("APIConnectionError", (Exception,), {})()

    message = friendly_error(connection_error)
    assert "Ollama 서버에 연결하지 못했습니다" in message
    assert "OLLAMA_BASE_URL" in message
