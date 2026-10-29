# Streamlit Community Cloud 배포 안내

IdeaLens 화면을 Streamlit Community Cloud(이하 SCC)에 올려 팀·시연용으로 쓰는 절차다. `main` 브랜치에 병합되면 SCC가 자동으로 배포한다. 배포 설정은 리더가 SCC 계정에서 직접 한다.

## 자동 배포 흐름

```text
기능 PR ─승인·병합→ develop ─push→ CI(SCC 의존성 검사 포함)
                                     └성공→ [Promote] develop → main 승격 PR 생성·갱신, 리뷰어 요청
승격 PR ─필수 검사 통과 + 1인 승인 + Create a merge commit→ main
main ─push→ SCC가 새 커밋을 자동 반영
      └→ [SCC Smoke] 브라우저로 앱을 열어 비밀번호 화면과 버전(방금 커밋)을 확인
```

- **승격 PR:** `develop → main 배포 승격` 제목의 PR이다. Promote 워크플로(`.github/workflows/promote-main.yml`)가 develop CI 성공 때마다 열거나 본문을 갱신한다. 병합하는 순간 배포된다.
- **병합 방식:** 반드시 **Create a merge commit**을 쓴다. Squash·Rebase는 develop과 main 이력을 어긋나게 한다.
- **스모크 검사:** SCC Smoke 워크플로(`.github/workflows/scc-smoke.yml`)가 main push 뒤 앱을 열어 본다.
  - 비밀번호 화면 아래 `버전 xxxxxxx`가 방금 커밋과 같아지면 성공이다.
  - 오류 화면, 비밀번호 화면 없음, 15분 안에 새 버전이 안 보임은 실패다.
  - SCC 주소는 단순 HTTP 요청에 정적 화면만 돌려주므로 Playwright 브라우저로 확인한다.

## 전제

- **배포 브랜치:** `main`. develop에서 검증을 마친 변경만 승격 PR로 들어간다.
- **SCC 전용 의존성:** [`frontend/requirements.txt`](../frontend/requirements.txt)를 쓴다.
  - SCC는 진입점(`frontend/app.py`) 폴더의 파일을 루트 `requirements.txt`보다 먼저 쓴다.
  - SCC는 Debian 11(SQLite 3.34)이다. full `chromadb`는 import 때 SQLite 3.35 이상을 요구해 실패한다. 그래서 공용 Chroma에 HTTP로만 접속하는 `chromadb-client`를 쓴다.
  - 버전은 루트 파일과 같게 유지하고, `tests/test_requirements_sync.py`가 이를 확인한다.
  - CI `SCC dependency check`는 같은 Debian 11 이미지에서 설치와 import를 검사한다.
- **색인:** 팀 공용 Chroma 서버([공용 Chroma 안내](shared-chroma.md))를 쓴다. SCC 파일 시스템은 앱을 다시 시작하면 지워지므로 로컬 색인을 두지 않는다.
- **접근 통제:** 앱 비밀번호(`IDEALENS_APP_PASSWORD`)뿐이다. 이 저장소는 공개 저장소라 SCC 앱도 기본으로 공개된다. 비밀번호가 새면 누구나 유료 분석(OpenAI·KIPRIS)을 실행할 수 있다.
- **apt 패키지:** `packages.txt`를 두지 않는다. PDF 글꼴은 저장소 안(`frontend/assets/fonts`)에 있다. 2026-09 SCC에서는 apt 단계 빌드 실패가 보고되었다.

## 처음 한 번 설정 (리더)

1. **비용 한도·키 준비**
   - OpenAI 프로젝트에 월 예산 한도를 건다.
   - 공용 Chroma 관리자에게 **호스팅 앱 전용** `CHROMA_API_KEY`를 받는다. 개인 키와 분리해 두면 따로 폐기할 수 있다.
2. **Actions의 PR 생성 허용**
   - 위치: GitHub 저장소 Settings → Actions → General → Workflow permissions
   - "Allow GitHub Actions to create and approve pull requests"를 체크하고 Save한다.
   - 회색으로 막혀 있으면 조직 소유자가 조직 Settings → Actions → General에서 켠다.
   - 켜지 않으면 Promote 실행이 설정 경로를 안내하며 실패한다.
3. **Actions 정책 확인:** Settings → Actions의 정책(Policies)이 새 워크플로를 막지 않는지 본다. 확인할 이벤트는 Promote의 `workflow_run`·`workflow_dispatch`, SCC Smoke의 `push`·`workflow_dispatch`다.
4. **main 보호 규칙 추가:** develop CI에서 `SCC dependency check`가 한 번 돈 뒤에 한다(그래야 검사 이름을 고를 수 있다).
   - 위치: Settings → Rules → Rulesets → New branch ruleset
   - 이름은 `main-release-gate`, 대상은 `main`이다.
   - Require status checks to pass: `Black format check`, `Pytest`, `Automation script tests`, `Docker build`, `SCC dependency check`. 출처는 GitHub Actions로 지정하고, 브랜치 최신 상태 요구는 끈다.
   - Require a pull request before merging:
     - 승인 1명
     - 새 push 시 승인 무효
     - 대화 해결 필수
     - Allowed merge methods는 **Merge**만 둔다.
   - 저장한 뒤 승격 PR 병합 버튼 옆 ▼에 "Create a merge commit"만 보이는지 확인한다.
   - 같은 설정을 명령으로 만들 수도 있다(저장소 admin 권한 필요). 명령은 [부록](#부록-main-보호-규칙-명령)에 있다.
5. **SCC 앱 생성:** main에 `frontend/requirements.txt`가 반영된 뒤에 한다.
   - [share.streamlit.io](https://share.streamlit.io) → Create app → "Yup, I have an app"
   - Repository `LG-CNS-RAG-Project1/LG-CNS-RAG-Project`, Branch `main`, Main file path `frontend/app.py`, App URL은 원하는 서브도메인
   - Advanced settings에서 Python **3.12**를 고른다. 배포 뒤에는 바꿀 수 없어 앱을 지우고 다시 만들어야 한다.
   - Advanced settings의 Secrets 칸에 아래 블록을 붙여 넣는다.
   - 저장소가 목록에 없으면 GitHub 권한 화면에서 조직 접근을 Request한다. 조직 소유자가 승인해야 한다.
6. **스모크 주소 등록**
   - 위치: GitHub 저장소 Settings → Secrets and variables → Actions → Variables → New repository variable
   - `SCC_APP_URL` = `https://<서브도메인>.streamlit.app`

### Secrets 붙여넣기 블록

값은 모두 따옴표로 감싼 문자열로 넣는다. 따옴표 없는 `true`는 환경변수로 전달되지 않는다. 최상위 키는 앱 안에서 환경변수로 읽힌다([Streamlit 문서](https://docs.streamlit.io/develop/concepts/connections/secrets-management)). 형식은 [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example)과 같다.

```toml
OPENAI_API_KEY = "<OpenAI 키>"
KIPRIS_API_KEY = "<KIPRIS 키>"
CHROMA_HOST = "<호스트명만, 예: chroma.example.com (https:// 없이)>"
CHROMA_PORT = "443"
CHROMA_SSL = "true"
CHROMA_API_KEY = "<호스팅 앱 전용 키>"
IDEALENS_APP_PASSWORD = "<접속 비밀번호, 비워 두지 않는다>"
```

- NAVER·DART 키는 넣지 않는다. 화면은 수집을 하지 않는다.
- `IDEALENS_APP_PASSWORD`가 비면 비밀번호 화면이 사라진다. 스모크 검사는 이 상태를 실패로 잡는다. 팀에는 비밀번호를 개인 메시지로 전달한다.

## 평소 배포

1. 기능 PR이 develop에 병합되고 CI가 성공하면 승격 PR이 열리거나 갱신된다. 리뷰어 1명이 자동으로 요청된다.
2. 승격 PR 본문의 "포함된 PR"과 Checks 탭을 확인한다.
   - "Approve workflows to run" 배너가 보이면 눌러 PR 검사를 실행한다.
3. 팀원 1명이 승인하면 병합 버튼 옆 ▼ → **Create a merge commit** → Confirm으로 병합한다.
   - develop이 다시 바뀌면 승인이 무효화되고, 직전 리뷰어에게 다시 요청된다.
4. Actions의 **SCC Smoke** 실행이 성공했는지 본다.

## 배포 직후 확인

- [ ] SCC Smoke가 성공했다. 앱 주소에 접속하면 비밀번호 화면과 `버전 xxxxxxx`가 먼저 나온다.
- [ ] 틀린 비밀번호로는 들어갈 수 없다.
- [ ] 다음 순서로 진행된다: 돋보기로 조사 시작 → 아이디어 입력 → AI 초안 만들기 → 초안 확인 → 특허·시장 근거 조사 시작.
  - "OPENAI_API_KEY를 설정해야 합니다"가 나오면 Secrets를 확인한다(화면 문구의 `.env`는 SCC에서는 Secrets를 뜻한다).
- [ ] 특허·시장 영역 상태가 '실행 안 함'이나 '오류'가 아니고 근거 목록이 나온다. 공용 Chroma에 연결하지 못하면 영역별 오류로 표시된다.
- [ ] 종합 보고서의 PDF·Markdown 다운로드가 동작하고, 파일에 키 문자열(`sk-`, `ServiceKey=` 등)이 없다.
- [ ] 특허 비교가 구성요소와 청구항 인용을 보여주며 법적 판단으로 단정하지 않는다. 시장 화면은 산업 신호와 직접 고객 수요를 구분한다.
- [ ] 메모리: 분석 1회를 실행한 뒤 앱이 재시작되지 않는다(SCC 앱 자원은 690MB~2.7GB, 제한은 예고 없이 바뀔 수 있음).

## 시연 전

- 12시간 동안 접속이 없으면 앱이 잠든다. 시연 전에 Actions → **SCC Smoke** → Run workflow(main)를 실행한다. 잠든 앱이면 깨우기 버튼을 누르고 비밀번호 화면이 뜰 때까지 기다린다.
- 공용 Chroma 서버가 멈추면 실분석이 영역별 오류로 표시된다. 이때는 예시 아이디어(가상 시연 표기) 흐름으로 전환한다.

## 문제가 생기면

| 증상 | 확인할 곳 | 조치 |
|---|---|---|
| Promote 실패: "Allow GitHub Actions to create…" | 처음 한 번 설정 2 | 설정을 켜고 Actions → Promote develop to main → Run workflow(develop) |
| SCC Smoke 실패: 오류 화면 | 앱 오른쪽 아래 Manage app 로그, 실패 실행의 `scc-smoke-screenshot` artifact | 원인 수정 PR 또는 롤백 |
| SCC Smoke 실패: 비밀번호 화면 없음 | SCC 앱 Settings → Secrets | `IDEALENS_APP_PASSWORD`를 채우고 저장 |
| SCC Smoke 실패: 새 커밋이 반영되지 않음 | SCC 앱 상태(빌드 중·오류), Manage app 로그 | Reboot app 후 Run workflow로 다시 확인 |
| 경고: 버전 표시가 없음 | — | SCC 배포에 `.git`이 없는 경우다. 앱이 뜬 것만 확인했으므로 화면에서 변경 반영을 직접 본다. |

**롤백 절차:** SCC에는 이전 버전으로 되돌리는 기능이 없다.
1. 문제가 된 PR을 되돌리는 revert PR을 develop에 올려 병합한다.
2. 갱신된 승격 PR을 병합한다.
3. 급한 시연은 로컬 Docker(`make ui`)로 진행한다.

## 운영 메모

- 비공개 앱은 한 계정에 한 개만 둘 수 있다. 공개 저장소에서 배포한 앱을 비공개로 바꾸려면 앱 설정의 Sharing을 쓴다.
- SCC 앱은 미국 지역에서 실행된다. KIPRIS·공용 Chroma 호출이 그 위치에서 동작하는지는 첫 실분석 때 확인한다.
- **프로젝트를 종료할 때 정리할 것**
  - SCC 앱과 Secrets를 삭제한다.
  - 저장소 변수 `SCC_APP_URL`을 지우고, `main-release-gate` 규칙은 필요하면 해제한다.
  - 호스팅 앱 전용 Chroma 키를 폐기한다.
  - NAVER 자료는 목표 안내서 B-SCOPE-1의 폐기 범위에 따라 정리한다.

## 부록: main 보호 규칙 명령

```bash
gh api --method POST repos/LG-CNS-RAG-Project1/LG-CNS-RAG-Project/rulesets --input - <<'EOF'
{
  "name": "main-release-gate",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
  "rules": [
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [
          {"context": "Black format check", "integration_id": 15368},
          {"context": "Pytest", "integration_id": 15368},
          {"context": "Automation script tests", "integration_id": 15368},
          {"context": "Docker build", "integration_id": 15368},
          {"context": "SCC dependency check", "integration_id": 15368}
        ]
      }
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["merge"]
      }
    }
  ]
}
EOF
```

`integration_id` 15368은 GitHub Actions 앱이다. 다른 앱이 같은 이름의 검사를 보고해도 통과로 치지 않는다.
