"""개발자의 공용 Chroma 연결 설정을 테스트에서 격리한다."""

import pytest


@pytest.fixture(autouse=True)
def local_chroma_by_default(monkeypatch):
    """원격 연결 테스트가 명시적으로 덮어쓰는 경우 외에는 로컬을 사용한다."""
    monkeypatch.setenv("CHROMA_HOST", "")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_SSL", "false")
    monkeypatch.setenv("CHROMA_API_KEY", "")
