# UI 담당 작업 가이드

## 담당 범위

아이디어 입력·결과 화면, 경영진/R&D 관점의 정보 구성, 시연 시나리오와 사용 안내를 담당한다.
백엔드 API, 실제 검색, 시장 판정·점수 계산은 담당 모듈의 응답을 사용한다.

## 로컬 실행 (Windows PowerShell)

저장소 루트에서 실행한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

현재 화면은 API 키 없이 작동하는 시연이다. 가상 문헌을 실제 분석과 혼동하지 않도록
화면·다운로드에 표시하며, 외부 API를 호출하거나 입력을 파일에 저장하지 않는다.
실행 중인 프로세스의 메모리에 세션 입력이 존재하므로 실제 비밀정보는 입력하지 않는다.
Python 인터프리터는 VS Code에서 `.venv\Scripts\python.exe`를 선택한다.

## 시연 순서

1. 빈 화면에서 필수 항목 없이 제출해 안내를 확인한다.
2. '설비 이상 탐지 예시' 선택 후 '시연 결과 보기'를 누른다.
3. 경영진 요약에서 사용자 입력과 판단 보류를 설명한다.
4. R&D 상세에서 가상 근거와 실제 출처 미연결 상태를 확인한다.
5. 다음 검증 탭에서 각 담당자의 후속 작업을 확인한다.
6. 시연 보고서를 다운로드하고 결과 초기화를 확인한다.

## 다음 개발 순서

- 1번 담당자와 `docs/api_contract.md`의 요청·응답·오류 형식을 합의한다(현재 비어 있음).
- 현재 입력은 `StructuredIdea`, 특허 결과는 `PatentReport`를 재사용한다.
- 통합 결과와 시장 결과 표시 형식은 담당자와 합의한 뒤 추가한다.
- 실제 API 연결 시 시연 모드와 명확히 분리하고 타임아웃·빈 결과·부분 실패를 처리한다.
- API 결과 없이 신뢰도·사업성·특허성 점수를 생성하지 않는다.
- 기업 비교 화면으로 범위를 확장할지는 팀의 입력 모델 합의 후 결정한다.

## 수정할 파일

- `frontend/app.py`: 화면 배치와 입력·결과 표시
- `frontend/demo.py`: 외부 호출 없는 시연 예시와 다운로드
- `tests/test_frontend.py`: 입력 검증·제출·초기화 테스트

## 검증·공유

```powershell
.\.venv\Scripts\python.exe -m black frontend tests/test_frontend.py
.\.venv\Scripts\python.exe -m pytest
```

기능 브랜치에 커밋·푸시한 뒤 develop 대상 PR로 공유한다. main에는 직접 반영하지 않는다.
