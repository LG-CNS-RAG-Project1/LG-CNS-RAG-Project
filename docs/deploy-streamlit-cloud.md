# Streamlit Community Cloud 배포 안내

IdeaLens 화면을 Streamlit Community Cloud(이하 SCC)에 올려 팀·시연용으로 쓰는 절차다. 배포는 리더가 SCC 계정에서 직접 한다.

## 전제

- **배포 브랜치:** `main`을 쓴다. develop에서 검증을 마친 뒤 develop→main PR을 병합해야 반영된다.
- **색인:** 팀 공용 Chroma 서버([공용 Chroma 안내](shared-chroma.md))를 쓴다. SCC 파일 시스템은 앱을 다시 시작하면 지워지므로 로컬 색인을 두지 않는다.
- **접근 통제:** 앱 비밀번호(`IDEALENS_APP_PASSWORD`)뿐이다. 이 저장소는 공개 저장소라 SCC 앱도 기본으로 공개된다. 비밀번호가 새면 누구나 유료 분석(OpenAI·KIPRIS)을 실행할 수 있다.

## 배포 순서

1. **main 반영:** develop→main PR을 병합한다(사용자 작업).
2. **앱 생성:** SCC에서 새 앱을 만든다.
   - Repository: `LG-CNS-RAG-Project1/LG-CNS-RAG-Project`
   - Branch: `main`
   - Main file path: `frontend/app.py`
   - Advanced settings에서 Python 3.12를 고른다.
3. **Secrets 입력:** Advanced settings의 Secrets 칸에 [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example) 형식으로 값을 넣는다.
   - 최상위 키는 앱 안에서 환경변수로도 읽힌다([Streamlit 문서](https://docs.streamlit.io/develop/concepts/connections/secrets-management)). 그래서 코드를 고치지 않고 `.env`와 같은 이름을 쓴다.
   - `CHROMA_API_KEY`는 공용 Chroma 관리자에게 **호스팅 앱 전용 키**를 받아 넣는다. 개인 키와 분리해 두면 따로 폐기할 수 있다.
   - NAVER·DART 키는 넣지 않는다. 화면은 수집을 하지 않는다.
   - `IDEALENS_APP_PASSWORD`는 반드시 넣는다. 팀에는 개인 메시지로 전달한다.
4. **비용 한도:** OpenAI 프로젝트에 월 예산 한도를 걸어 둘 것을 권장한다.

## 배포 직후 확인

- [ ] 앱 주소에 접속하면 비밀번호 화면이 먼저 나오고, 틀린 비밀번호로는 들어갈 수 없다.
- [ ] 상단 상태가 'AI 구조화 후 실제 분석'이다. 'OPENAI 키 없음'으로 나오면 Secrets를 확인한다.
- [ ] 직접 입력 → 재질문 → 3단계 `특허·시장 조사 실행` 순서로 진행한다. 이때 다음을 확인한다.
  - 색인이 '팀 공용 Chroma'로 표시된다.
  - 영역별 상태가 '실행 안 함'이 아니다.
- [ ] 4단계 보고서 다운로드가 동작하고, 보고서에 키 문자열(`sk-`, `ServiceKey=` 등)이 없다.
- [ ] 메모리: 분석 1회를 실행한 뒤 앱이 재시작되지 않는다(SCC 앱 자원은 690MB~2.7GB, 제한은 예고 없이 바뀔 수 있음).

## 운영 메모

- 12시간 동안 접속이 없으면 앱이 잠든다. 시연 전에 미리 접속해 깨운다.
- 비공개 앱은 한 계정에 한 개만 둘 수 있다. 공개 저장소에서 배포한 앱을 비공개로 바꾸려면 앱 설정의 Sharing을 쓴다.
- 공용 Chroma 서버가 멈추면 실분석이 영역별 오류로 표시된다. 이때는 '예시 불러오기' 흐름(가상 시연)으로 전환한다.
- **프로젝트를 종료할 때 정리할 것**
  - SCC 앱과 Secrets를 삭제한다.
  - 호스팅 앱 전용 Chroma 키를 폐기한다.
  - NAVER 자료는 목표 안내서 B-SCOPE-1의 폐기 범위에 따라 정리한다.
