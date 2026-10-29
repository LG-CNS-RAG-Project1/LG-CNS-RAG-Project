"""개발자의 공용 Chroma 연결 설정과 API 키를 테스트에서 격리한다."""

import pytest

API_KEY_NAMES = [
    "OPENAI_API_KEY",
    "KIPRIS_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "DART_API_KEY",
    "DATA_GO_KR_SERVICE_KEY",
]


@pytest.fixture(autouse=True)
def no_real_api_keys(monkeypatch):
    """빈 값으로 두어 .env의 실제 키가 로드되지 않게 한다(load_dotenv는 기존 값을 덮어쓰지 않는다).

    키가 필요한 테스트는 가짜 값을 직접 설정한다.
    """
    for name in API_KEY_NAMES:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("IDEALENS_APP_PASSWORD", "")


@pytest.fixture(autouse=True)
def local_chroma_by_default(monkeypatch):
    """원격 연결 테스트가 명시적으로 덮어쓰는 경우 외에는 로컬을 사용한다."""
    monkeypatch.setenv("CHROMA_HOST", "")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_SSL", "false")
    monkeypatch.setenv("CHROMA_API_KEY", "")
