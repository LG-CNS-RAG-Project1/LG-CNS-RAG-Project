"""로컬 기본값·원격 접속·잘못된 공용 DB 설정을 검증한다."""

from unittest.mock import patch
import pytest
from src.retrieval.chroma_client import connect_chroma


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch, local_chroma_by_default):
    monkeypatch.setattr("src.retrieval.chroma_client.load_dotenv", lambda *args: None)
    for key in ("CHROMA_HOST", "CHROMA_PORT", "CHROMA_SSL", "CHROMA_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_local_default_creates_persistent_storage(tmp_path):
    with patch("src.retrieval.chroma_client.chromadb.PersistentClient") as client:
        connect_chroma(tmp_path / "db")
        assert (tmp_path / "db").is_dir()
        assert client.call_args.kwargs["path"] == str(tmp_path / "db")


def test_remote_has_no_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROMA_HOST", "127.0.0.1")
    monkeypatch.setenv("CHROMA_PORT", "18000")
    with patch("src.retrieval.chroma_client.chromadb.HttpClient") as client:
        client.side_effect = ConnectionError("Unavailable")
        with pytest.raises(ConnectionError):
            connect_chroma(tmp_path / "db")
        client.assert_called_once_with(host="127.0.0.1", port=18000, ssl=False)
    assert not (tmp_path / "db").exists()


@pytest.mark.parametrize(
    "key,value",
    [
        ("CHROMA_PORT", "0"),
        ("CHROMA_PORT", "65536"),
        ("CHROMA_PORT", "oops"),
        ("CHROMA_SSL", "yes"),
    ],
)
def test_invalid_remote_settings_fail(monkeypatch, tmp_path, key, value):
    monkeypatch.setenv("CHROMA_HOST", "127.0.0.1")
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        connect_chroma(tmp_path)


def test_https_api_key_headers(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROMA_HOST", "db.example.com")
    monkeypatch.setenv("CHROMA_PORT", "443")
    monkeypatch.setenv("CHROMA_SSL", "true")
    monkeypatch.setenv("CHROMA_API_KEY", "test-token")
    with patch("src.retrieval.chroma_client.chromadb.HttpClient") as client:
        connect_chroma(tmp_path)
        client.assert_called_once_with(
            host="db.example.com",
            port=443,
            ssl=True,
            headers={"Authorization": "Bearer test-token"},
        )


@pytest.mark.parametrize(
    "host,ssl",
    [("", "true"), ("db.example.com", "false"), ("http://db.example.com", "true")],
)
def test_api_key_refuses_local_or_plaintext(monkeypatch, tmp_path, host, ssl):
    monkeypatch.setenv("CHROMA_HOST", host)
    monkeypatch.setenv("CHROMA_SSL", ssl)
    monkeypatch.setenv("CHROMA_API_KEY", "test-token")
    with patch("src.retrieval.chroma_client.chromadb.HttpClient") as client:
        with pytest.raises(ValueError):
            connect_chroma(tmp_path)
        client.assert_not_called()
