# 특허 청구항 분석 계약

## 입력과 출력

`src.services.patent_service.analyze_patents()`가 특허 분석 진입점이다.

- 입력: 기존 `PatentSearchRequest` (`StructuredIdea`, 최대 검색 문헌 수)
- 출력: 기존 `PatentReport` (`evidence`, `comparisons`, `unknowns`, `search_scope`)
- 검색: 기술 요소별 한국어·영어 질의로 기존 Dense 특허 색인을 검색한다.
- 보충: 색인에서 요청 수보다 적은 문헌을 찾으면 KIPRIS 키워드 검색 결과를 더한다. 중복은 출원번호(`source_id`)로 제거하고 최대 5건만 분석한다.
- 원문: 선택된 문헌에 대해서만 출원번호로 청구항 상세를 조회한다. KIPRIS 상세 청구항 endpoint의 상품 이용 승인이 필요하다. API 권한 오류·빈 응답은 주장항을 만들어 채우지 않고 초록 인용과 미확인 항목으로 남긴다.
- 비교: `compare_patent_evidence()`가 각 인용 근거별 유사점·차이점·미확인을 만들고, 근거 없는 citation id나 누락된 비교를 거부한다. 법적 특허성·신규성·진보성·침해 여부를 판정하지 않는다.

KIPRIS 검색 API는 `openapi/rest/patUtiModInfoSearchSevice/freeSearchInfo`의 `accessKey`를 사용한다. 청구항 상세는 별도 KIPO API인 `kipo-api/kipi/patUtiModInfoSearchSevice/getBibliographyDetailInfoSearch`를 호출하며 `applicationNumber`와 `ServiceKey`를 전달한다. 검색용 `accessKey` 파라미터를 상세 API에 그대로 쓰거나 상세 API를 `openapi/rest/` 아래 호출하면 정상 조회되지 않는다. 상세 응답은 XML의 `body/item/claimInfoArray/claimInfo/claim` 구조이며, 개별 `claim` 텍스트 앞에 포함된 항 번호를 파싱하고 원문 텍스트는 보존한다. 이 연동은 실제 API 호출에서 청구항 15건이 담긴 응답으로 확인했다. KIPRIS Plus 상품별 권한은 계정 설정에 따라 달라질 수 있다. [공개·등록공보 API 안내](https://plus.kipris.or.kr/portal/data/apiClas/DBII_000000000000001/view.do?k=&menuNo=210020), [KIPRIS Plus 서지상세 API 설명](https://plus.kipris.or.kr/portal/popup/DBII_000000000000001/SC002/ADI_0000000000010162/apiDescriptionSearch.do)

## 청구항 표현과 검색 위치

`PatentClaim`은 `claim_number`, 원문 `text`, `claim_type`, `depends_on`, `version_id`를 담는다. 종속 관계는 원문이 명시한 `제N항에 있어서`와 항 범위 참조에서만 추출한다. 식별할 번호 표식이 없는 텍스트는 번호를 추측하지 않아 청구항 단위로 만들지 않는다.

각 청구항은 `PatentChunk` 하나로 색인하며 `chunk_id`는 `{patent_id}_claim_{claim_number}` 형식이다. 공통 `SearchDocument`의 metadata와 `PatentEvidence`에는 청구항 번호·유형·상위항 참조·문헌 식별자·버전이 함께 연결된다. 수집 시각은 UTC ISO 8601 문자열로 문서와 색인 metadata에 보존한다. 이 범위에서는 원문 내 문자 오프셋을 API가 제공하지 않으므로 청구항 번호가 원문 위치의 기준이다.

한 문헌에서 아이디어 기술 표현과 일치하는 청구항을 우선 최대 5개까지 검토 문맥으로 선택한다. 선택 시 종속항의 상위항을 함께 포함하고, 전체 청구항 원문을 약 1,800 토큰으로 추정한 예산 안에 둔다. 분석 프롬프트에는 특허별 문헌 수 균형을 고려해 모든 특허 근거를 합산 약 6,000 토큰까지 원문 단위로 전달하며, 예산을 넘는 근거는 청구항·독립항 우선으로 보존하고 제외한 citation ID를 `unknowns`에 기록한다. 두 예산은 공백 토큰 수와 문자 길이 기반 상한 중 큰 값으로 계산하므로 모델 토크나이저의 정확한 입력 토큰 수가 아닌 보수적 근사치다. 원문을 잘라 인용하지 않으며 상위항이 예산 때문에 제외되면 종속항도 제외한다. 이 문맥 예산은 특허 근거 텍스트에 적용되며 검색어 계획, 프롬프트, 보고서 출력 전체의 모델 입력 한도를 보장하지 않는다. 보고서에는 최대 5개 문헌을 담되, 한 문헌의 독립항·종속항을 함께 인용할 수 있다.

## 실행과 테스트

### 분야별 특허 사전 색인

`configs/technology_areas.yaml`은 시장·특허가 함께 쓰는 SF-01 산업용 로봇, SF-02 AI 비전 품질검사, SF-03 설비 예지보전, SF-04 에너지 관리, SF-05 지능형 공정제어, SF-06 디지털 트윈, SF-07 생산계획 최적화, SF-08 물류 자동화의 표준 분야명·주요 기술·특징·검색어를 관리한다. 시장 키워드와 특허 키워드를 같은 분야 항목에 두며, 초기 특허 수집·색인 대상은 SF-02와 SF-05다.

```bash
python -m src.ingestion.patent_processor --field-id SF-02 --limit 20 --include-claims
python -m src.ingestion.patent_processor --field-id SF-05 --limit 20 --include-claims
```

이 명령은 분야 검색어마다 최대 `--limit`건을 KIPRIS에서 찾아 출원번호로 중복 제거하고, 분야 ID를 문헌과 Chroma 메타데이터에 남긴다. `--include-claims`를 지정하면 청구항 상세 API를 호출하며, 호출이 실패하거나 권한이 없으면 오류를 기록하고 실제 확보된 초록만 색인한다. 새 문서 임베딩은 이 배치 실행 시 생성하고 로컬 `data/patents/chroma/`에 저장한다. 이미 내용과 메타데이터가 같은 청크는 재임베딩하지 않는다. 실행에는 `KIPRIS_API_KEY`, 청구항 조회 권한 및 `OPENAI_API_KEY`가 필요하다.

아이디어 기술 요소 기반 검색어 계획을 사용하려면 `PatentSearchRequest` JSON을 `scripts.collect_patents`에 입력한다. 계획은 1~5개 기술 요소로 검증되며, 한국어·영어 검색어를 KIPRIS 수집에 사용한다. 수집 단계는 원본 응답을 `data/patents/raw/`에 저장하고, `scripts.build_patent_index`는 저장된 JSONL을 별도로 색인한다. 원본 저장 메타데이터에는 API 키를 기록하지 않는다.

KIPRIS 검색 결과에서 출원일·공개일을 보존한다. 청구항 문구의 `청구항 1에 있어서`와 `제1항에 있어서` 형식을 모두 종속항으로 판정하고 참조 항 번호를 연결한다. `getBibliographyDetailInfoSearch`는 KIPRIS Plus의 특허·실용신안 API 목록에 등재되어 있고, 현재 개발환경의 인증정보로 청구항 상세 응답을 받아 색인한 이력이 있다. 계정별 사용 승인 상태는 KIPRIS Plus 계정에서 별도로 확인해야 한다. [KIPRIS Plus 특허·실용신안 API 목록](https://plus.kipris.or.kr/eng/data/service/DBII_000000000000001/view.do?menuNo=300100&subTab=SC001)

`PatentSearchRequest.technology_area_id`에 `SF-02` 또는 `SF-05`를 지정하면 로컬 검색을 해당 분야로 제한한다. 이 필드를 생략하면 기존처럼 전체 특허 컬렉션을 검색한다. 이 설정은 문서 벡터의 사전 생성을 뜻하며, Dense/Hybrid 검색의 질의 임베딩은 요청마다 별도로 생성된다.

분석 함수는 함수 인자로 `collection`, `embed_fn`, `query_llm_fn`, `claim_fetcher`, `kipris_search_fn`, `comparison_fn`을 주입할 수 있다. 자동화 테스트는 Mock을 주입해 검색·폴백·인용 계약을 확인한다. 실제 API 사용 시에는 특허 검색 및 청구항 endpoint의 KIPRIS Plus 상품 이용 권한이 필요하며, 청구항 상세 API는 실제 응답으로 별도 확인했다.

테스트:

```bash
python -m pytest tests/test_patent_claims.py tests/test_patent_analysis_service.py tests/test_patent_eval.py
```

## 특허 검색 품질 평가

`evaluation/patent_cases.json`에는 샘플 아이디어에서 고정한 5개 질의가 있으며, 정답 문헌 라벨은 사람이 판정할 때까지 비어 있다. 특허 수집·색인 후 후보를 내보내 같은 문헌을 검토한다. 라벨링 CSV에는 검색 방식과 순위를 기록하지 않아 판정자가 시스템 순위를 보고 영향을 받지 않도록 한다. 구체적인 관련도 판정 기준은 [특허 평가 라벨링 가이드](../evaluation/patent_labeling.md)를 따른다.

라벨 검토 전 `python -m evaluation.patent_preflight`로 질의와 후보 파일의 케이스별 분포, URL·중복·라벨 상태와 SHA-256을 검사할 수 있다. 이 사전 점검은 외부 API를 호출하지 않는다.

`python -m evaluation.patent_review_context`는 기존 로컬 특허 처리 파일에서 초록·청구항·서지 정보를 후보와 연결해 Git 제외 경로에 JSONL로 만든다. 출원번호·발명의 명칭·후보 청구항 번호의 일치 통계를 출력하며 외부 API를 호출하지 않는다. 이 확인 결과는 기술적 관련도의 자동 판정이 아니다.

```bash
python -m evaluation.patent_labeling export
# evaluation/labels/patent_candidates.csv에서 relevant 열을 1(관련) 또는 0(비관련)으로 채운다.
python -m evaluation.patent_labeling import
python -m evaluation.evaluate patent --mode dense --label baseline
python -m evaluation.evaluate patent --mode bm25 --label baseline
python -m evaluation.evaluate patent --mode hybrid --label baseline
python -m evaluation.evaluate patent --mode hybrid --reranker bi-encoder --label baseline
python -m evaluation.evaluate patent --mode hybrid --reranker cross-encoder --label baseline
python -m evaluation.evaluate patent --mode hybrid --reranker cross-encoder --candidate-k 40 --label candidate40
```

후보 CSV는 기본적으로 세 검색 방식의 상위 20건을 문헌 단위로 합친다. 색인에 원문 URL이 없으면 출원번호로 KIPRIS 검색 링크를 생성하며, 라벨 검토자는 검색 결과의 출원번호와 발명의 명칭을 대조한다. 재정렬 후보도 라벨링하려면 `export --reranker bi-encoder` 또는 `export --reranker cross-encoder`를 사용한다. Bi-Encoder는 OpenAI 임베딩으로 질의와 후보 문헌을 다시 임베딩하므로 API 호출 비용이 추가되고, Cross-Encoder는 `sentence-transformers`와 모델 다운로드가 필요하다. 모든 후보를 판정한 질의만 Hit@K·Recall@K·Precision@K·MRR·nDCG@K에 포함하며, 라벨되지 않은 결과는 `unjudged`로 별도 집계한다. 비용은 자동 집계하지 않는다. 평가셋 라벨링 전에는 특허 검색 성능 수치를 보고하지 않는다.

새 평가 CSV에는 실행 시각, Git 커밋과 작업 트리 상태, 평가 문항·라벨 데이터 해시, 색인 문서 수와 색인 내용·메타데이터 해시, Top-K·후보 수·RRF 상수, 임베딩·reranker 모델, BM25 설정을 함께 기록한다. 이전 결과 파일에는 이 지문이 없으므로 새 실행 결과와 직접 동등한 재현 기록으로 취급하지 않는다.

`--candidate-k`는 재정렬 전에 보유할 후보 문헌 수이며 기본값 20은 평가 Top-5의 4배다. 후보 수를 비교할 때는 평가 질의·사람 라벨·색인 지문·Top-K·reranker를 고정하고 후보 수만 바꾼다. 라벨 후보 CSV는 출력할 상위 20건을 포함하므로, 다른 후보 수에서 새 문헌이 Top-K에 나타나 `unjudged`가 늘면 그 문헌을 추가 판정한 뒤 해당 비교를 다시 실행한다.
