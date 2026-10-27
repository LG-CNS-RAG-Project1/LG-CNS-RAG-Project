# 팀 공용 Chroma

## 역할과 데이터 흐름

GitHub는 코드와 설정을 관리한다. 수집한 벡터·문서·메타데이터는 Chroma 서버의 디스크에 보관한다.

```text
팀원 PC의 수집·색인 코드 → Google IAP 보호 터널 → 공용 Chroma → 서버 영구 디스크
팀원 PC의 검색·분석 코드 → Google IAP 보호 터널 → 같은 Chroma → 검색 결과
```

웹에서 이 흐름을 호출하는 API 연결은 별도 작업이다. 현재 Streamlit 화면은 시연이며 서버를 만들었다고 실제 검색 결과로 바뀌지 않는다. Chroma에는 색인할 문서와 벡터가 저장되며 원본 PDF·이미지 전체가 자동 업로드되는 것은 아니다.

## 서버

- Google Compute Engine의 Debian VM에서 `deploy/chroma-startup.sh`를 시작 스크립트로 실행한다. 팀 서버 이름은 `idealens-chroma`, 영역은 `us-central1-c`이다.
- Chroma 이미지 버전은 `1.5.9`, 데이터 경로는 호스트 `/srv/idealens/chroma` → 컨테이너 `/data`이다.
- 컨테이너가 재시작되어도 같은 디스크를 사용한다. VM 정지 중에는 접속할 수 없지만 디스크는 남는다. 디스크 삭제와 무료체험 종료에 대비해 별도 백업이 필요하다.
- 기본 시작 스크립트는 `8000` 포트를 `127.0.0.1`에만 바인딩한다. IAP 구성 시 `CHROMA_INTERNAL_IP=10.128.0.2`를 추가해 서버 내부 IP에도 바인딩한다. 서버에 할당된 IP인지 검증하며 공개 IP에는 바인딩하지 않는다.
- IAP DB 경로는 방화벽에서 `35.235.240.0/20` → `8000`만 허용한다. 다른 출발지의 DB 접속은 더 높은 우선순위의 차단 규칙으로 막아 기본 내부 통신 허용 규칙을 우회하지 못하게 한다.
- 본인 관리 SSH는 별도 전용 키와 현재 PC의 출발지 IP만 허용한다. PC의 공인 IP가 바뀌면 관리자가 콘솔에서 이 규칙을 갱신한다. 팀원은 SSH 로그인 없이 DB만 이용한다.
- 무료체험 크레딧을 쓰는 구성이며 영구 무료 서비스가 아니다. VM·디스크·외부 IPv4·스냅샷·트래픽은 크레딧을 소비한다. 유료 계정 전환은 별도 결정 사항이다. 예산 알림은 자동 지출 차단이 아니다.

Docker를 이미 설치한 서버라면 `docker compose -f deploy/compose.chroma.yaml up -d`도 사용할 수 있다. Compose는 별도 named volume을 사용하므로 시작 스크립트의 데이터 폴더와 혼용하지 않는다.

## 팀원 접속

GitHub 권한과 Google Cloud 권한은 별개다. 팀원은 `Compute 뷰어`와 `IAP 보안 터널 사용자` 역할을 사용한다. IAP 역할 조건은 `destination.port == 8000 && destination.ip == "10.128.0.2"`로 DB만 허용한다. 서버 관리자·SSH 로그인·결제 역할은 필요 없다. DB 접속자는 같은 컬렉션을 읽고 수정·삭제할 수 있으므로 신뢰하는 팀원만 등록한다.

각 PC에 [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)를 설치한다. 아래 로그인에서는 권한을 받은 본인 Google 계정을 선택한다. 접속 터미널은 사용하는 동안 유지한다. 다른 터미널에서 Python 코드를 실행한다.

```powershell
gcloud auth login
gcloud compute start-iap-tunnel idealens-chroma 8000 --local-host-port=127.0.0.1:18000 --project=project-94e6b659-e0d2-4591-a46 --zone=us-central1-c
```

PC에서 Python을 실행하는 경우 저장소 `.env`에 다음을 입력한다.

```dotenv
CHROMA_HOST=127.0.0.1
CHROMA_PORT=18000
CHROMA_SSL=false
```

PC에서 Python을 직접 실행하는 방법을 기본으로 한다. 서버 자체에서 실행하는 코드는 `127.0.0.1:8000`을 사용한다. IAP 터널이 PC와 Google 사이를 암호화하므로 Chroma HTTP 클라이언트의 SSL은 끈다.

Docker Desktop의 개발 컨테이너에서 PC의 터널을 쓰려면 `host.docker.internal`로 해당 로컬 포트에 도달하는지 먼저 확인한다. 환경에 따라 loopback 바인딩의 터널에 도달하지 못할 수 있으므로 기본 접속 절차는 PC의 Python 실행을 기준으로 한다. 터널을 모든 네트워크 인터페이스에 공개하지 않는다.

`CHROMA_HOST`가 비어 있으면 기존 로컬 저장 방식을 유지한다. 원격 서버 연결이 실패하면 오류를 내며 로컬 DB로 몰래 전환하지 않는다. 컬렉션은 특허 `patents`, 시장 뉴스 `news`를 사용한다. 같은 컬렉션을 사용하는 팀원은 같은 임베딩 모델·차원·색인 규칙을 유지해야 한다. 공용 컬렉션 삭제·초기화는 팀과 협의한다.

## 확인과 기존 자료

터널을 연 뒤 연결과 컬렉션 개수를 확인한다. 아래 명령은 문서를 추가·삭제하거나 임베딩 API를 호출하지 않는다.

```powershell
python -c "import chromadb; c=chromadb.HttpClient(host='127.0.0.1',port=18000); print('heartbeat', c.heartbeat()); print([(x.name,x.count()) for x in c.list_collections()])"
```

기존 PC의 로컬 색인은 자동 복사되지 않는다. 공용 연결을 설정한 다음 수집·색인 작업을 실행하면 새 자료가 서버에 저장된다. 이미 만든 색인을 이전하려면 컬렉션 설정과 임베딩을 보존해 별도로 이관해야 한다. 재수집·재임베딩은 외부 API 비용이 생길 수 있으므로 자료 담당자와 방법을 정한다.

## 백업과 복구

스냅샷은 디스크 보호 수단이며 실행 중 DB의 일관된 백업을 보장하는 것으로 간주하지 않는다. 쓰기 작업을 멈추고 컨테이너를 중지한 상태에서 `/srv/idealens/chroma` 전체를 다른 디스크·보관소로 복사한 뒤 재시작한다. 복구 시 동일 버전의 Chroma를 사용하고 컬렉션 개수와 샘플 검색을 검증한다. 백업과 복구 검증 전에는 원본을 지우지 않는다.
