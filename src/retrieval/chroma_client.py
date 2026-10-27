"""로컬 영구 저장소 또는 팀 공용 Chroma HTTP 서버 연결."""

import os
from pathlib import Path

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv


def connect_chroma(local_path: Path):
    """CHROMA_HOST가 지정된 경우에만 원격 서버를 사용한다."""
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    host = os.getenv("CHROMA_HOST", "").strip()
    if host:
        port = int(os.getenv("CHROMA_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("CHROMA_PORT must be between 1 and 65535")
        ssl = os.getenv("CHROMA_SSL", "false").strip().lower()
        if ssl not in {"true", "false"}:
            raise ValueError("CHROMA_SSL must be true or false")
        return chromadb.HttpClient(host=host, port=port, ssl=ssl == "true")
    local_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(local_path), settings=Settings(anonymized_telemetry=False)
    )
