"""SCC 전용 의존성 파일(frontend/requirements.txt)이 루트 고정 버전과 어긋나지 않는지 검증한다."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pins(path: Path) -> dict[str, str]:
    """`이름==버전` 줄을 소문자 이름 → 버전 사전으로 모은다. 고정 버전이 아닌 줄은 실패로 본다."""
    result = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, sep, version = line.partition("==")
        assert sep, f"{path.name}: 고정 버전이 아닌 줄 {line!r}"
        result[name.strip().lower()] = version.strip()
    return result


ROOT_PINS = pins(ROOT / "requirements.txt")
SCC_PINS = pins(ROOT / "frontend" / "requirements.txt")


def test_scc_uses_thin_chroma_client_with_same_version():
    assert "chromadb" not in SCC_PINS
    assert SCC_PINS["chromadb-client"] == ROOT_PINS["chromadb"]


def test_scc_excludes_test_tools():
    assert "pytest" not in SCC_PINS


def test_scc_pins_match_root():
    expected = {
        name: version
        for name, version in ROOT_PINS.items()
        if name not in {"chromadb", "pytest"}
    }
    actual = {
        name: version for name, version in SCC_PINS.items() if name != "chromadb-client"
    }
    assert actual == expected
