# 팀 공용 Chroma

## 역할과 데이터 흐름

GitHub는 코드와 설정을 관리한다. 수집한 벡터·문서·메타데이터는 Chroma 서버의 디스크에 보관한다.

```text
팀원 PC의 수집·색인 코드 → SSH 터널 → 공용 Chroma → 서버 영구 디스크
팀원 PC의 검색·분석 코드 → SSH 터널 → 같은 Chroma → 검색 결과
```

웹에서 이 흐름을 호출하는 API 연결은 별도 작업이다. 현재 Streamlit 화면은 시연이며 서버를 만들었다고 실제 검색 결과로 바뀌지 않는다. Chroma에는 색인할 문서와 벡터가 저장되며 원본 PDF·이미지 전체가 자동 업로드되는 것은 아니다.

## 서버

- Google Compute Engine의 Debian VM에서 `deploy/chroma-startup.sh`를 시작 스크립트로 실행한다. 팀 서버 이름은 `idealens-chroma`, 영역은 `us-central1-c`이다.
- Chroma 이미지 버전은 `1.5.9`, 데이터 경로는 호스트 `/srv/idealens/chroma` → 컨테이너 `/data`이다.
- 컨테이너가 재시작되어도 같은 디스크를 사용한다. VM 정지 중에는 접속할 수 없지만 디스크는 남는다. 디스크 삭제와 무료체험 종료에 대비해 별도 백업이 필요하다.
- 서버의 `8000` 포트는 `127.0.0.1`에만 바인딩한다. 인터넷에 공개하거나 방화벽에서 모든 IP에 허용하지 않는다.
- 무료체험 크레딧을 쓰는 구성이며 영구 무료 서비스가 아니다. VM·디스크·외부 IPv4·스냅샷·트래픽은 크레딧을 소비한다. 유료 계정 전환은 별도 결정 사항이다. 예산 알림은 자동 지출 차단이 아니다.

Docker를 이미 설치한 서버라면 `docker compose -f deploy/compose.chroma.yaml up -d`도 사용할 수 있다. Compose는 별도 named volume을 사용하므로 시작 스크립트의 데이터 폴더와 혼용하지 않는다.

## 팀원 접속

GitHub 권한과 Google Cloud 권한은 별개다. 관리자가 팀원 Google 계정의 VM 접속 권한을 설정해야 한다. 프로젝트 Owner·Editor를 모든 팀원에게 줄 필요는 없다. IAP 경유 접속은 IAP 터널 권한, 해당 VM의 SSH 접속 권한, IAP IP 대역의 SSH 방화벽 규칙이 준비되어야 한다.

Google Cloud CLI 설치와 본인 로그인 후 아래 명령에서 실제 VM 영역을 입력한다. 이 터미널은 사용하는 동안 유지한다.

```powershell
gcloud compute ssh idealens-chroma --project=project-94e6b659-e0d2-4591-a46 --zone=us-central1-c --tunnel-through-iap -- -N -L 18000:127.0.0.1:8000
```

PC에서 Python을 실행하는 경우 저장소 `.env`에 다음을 입력한다.

```dotenv
CHROMA_HOST=127.0.0.1
CHROMA_PORT=18000
CHROMA_SSL=false
```

개발 컨테이너에서 실행할 때는 PC의 터널에 도달하도록 `CHROMA_HOST=host.docker.internal`을 사용한다(Docker Desktop). 서버 자체에서 실행하는 코드는 `127.0.0.1:8000`을 사용한다. 터널로 암호화하므로 터널 내부 HTTP는 SSL을 끈다.

`CHROMA_HOST`가 비어 있으면 기존 로컬 저장 방식을 유지한다. 원격 서버 연결이 실패하면 오류를 내며 로컬 DB로 몰래 전환하지 않는다. 컬렉션은 특허 `patents`, 시장 뉴스 `news`를 사용한다. 같은 컬렉션을 사용하는 팀원은 같은 임베딩 모델·차원·색인 규칙을 유지해야 한다. 공용 컬렉션 삭제·초기화는 팀과 협의한다.

## 확인과 기존 자료

터널을 연 뒤 연결과 컬렉션 개수를 확인한다. 아래 명령은 문서를 추가·삭제하거나 임베딩 API를 호출하지 않는다.

```powershell
python -c "import chromadb; c=chromadb.HttpClient(host='127.0.0.1',port=18000); print('heartbeat', c.heartbeat()); print([(x.name,x.count()) for x in c.list_collections()])"
```

기존 PC의 로컬 색인은 자동 복사되지 않는다. 공용 연결을 설정한 다음 수집·색인 작업을 실행하면 새 자료가 서버에 저장된다. 이미 만든 색인을 이전하려면 컬렉션 설정과 임베딩을 보존해 별도로 이관해야 한다. 재수집·재임베딩은 외부 API 비용이 생길 수 있으므로 자료 담당자와 방법을 정한다.

## 백업과 복구

스냅샷은 디스크 보호 수단이며 실행 중 DB의 일관된 백업을 보장하는 것으로 간주하지 않는다. 쓰기 작업을 멈추고 컨테이너를 중지한 상태에서 `/srv/idealens/chroma` 전체를 다른 디스크·보관소로 복사한 뒤 재시작한다. 복구 시 동일 버전의 Chroma를 사용하고 컬렉션 개수와 샘플 검색을 검증한다. 백업과 복구 검증 전에는 원본을 지우지 않는다.
