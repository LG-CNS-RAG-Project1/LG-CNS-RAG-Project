"""Streamlit Community Cloud 전용 의존성(frontend/requirements.txt)으로 설치한 환경을 점검한다.

CI의 SCC 재현 job에서 실행한다. 다음 중 하나라도 어긋나면 0이 아닌 코드로 끝난다.
- chromadb가 thin client(chromadb-client)로 설치되었는가(SQLite 버전 검사 없음)
- full chromadb 배포판이 함께 설치되지 않았는가(같은 chromadb 폴더를 덮어쓴다)
- 화면과 분석 파이프라인 모듈을 불러올 수 있는가
"""

import importlib.metadata as metadata
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    print(f"SQLite {sqlite3.sqlite_version}")
    from chromadb.is_thin_client import is_thin_client

    if not is_thin_client:
        print(
            "chromadb가 thin client가 아닙니다. frontend/requirements.txt를 확인하세요."
        )
        return 1
    try:
        metadata.distribution("chromadb")
    except metadata.PackageNotFoundError:
        pass
    else:
        print("full chromadb 배포판이 함께 설치되었습니다.")
        return 1

    import frontend.live  # noqa: F401
    import frontend.planner_view  # noqa: F401
    import src.pipeline  # noqa: F401
    import src.services.planner_service  # noqa: F401

    print("SCC 의존성 점검 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
