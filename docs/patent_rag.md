# 특허 청구항 분석 계약

## 입력과 출력

`src.services.patent_service.analyze_patents()`가 특허 분석 진입점이다.

- 입력: 기존 `PatentSearchRequest` (`StructuredIdea`, 최대 검색 문헌 수)
- 출력: 기존 `PatentReport` (`evidence`, `comparisons`, `unknowns`, `search_scope`)
- 검색: 기술 요소별 한국어·영어 질의로 기존 Dense 특허 색인을 검색한다.
- 보충: 색인에서 요청 수보다 적은 문헌을 찾으면 KIPRIS 키워드 검색 결과를 더한다. 중복은 출원번호(`source_id`)로 제거하고 최대 5건만 분석한다.
- 원문: 선택된 문헌에 대해서만 출원번호로 청구항 상세를 조회한다. KIPRIS 상세 청구항 endpoint의 상품 이용 승인이 필요하다. API 권한 오류·빈 응답은 주장항을 만들어 채우지 않고 초록 인용과 미확인 항목으로 남긴다.
- 비교: `compare_patent_evidence()`가 각 인용 근거별 유사점·차이점·미확인을 만들고, 근거 없는 citation id나 누락된 비교를 거부한다. 법적 특허성·신규성·진보성·침해 여부를 판정하지 않는다.

KIPRIS Plus는 국내 특허·실용 공개/등록공보의 서지·전문 API를 제공하고, 그 상세 항목에 청구항 조회가 안내되어 있다. API 상품은 신청·승인 절차가 적용될 수 있으므로 `KIPRIS_API_KEY`가 있어도 해당 상품의 접근이 허용된다는 보장은 없다. [공개·등록공보 API 안내](https://plus.kipris.or.kr/portal/data/service/DBII_000000000000001/view.do), [KIPRIS Plus 이용 약관 및 서비스 신청 절차](https://plus.kipris.or.kr/portal/data/service/DBII_000000000000001/view.do)

## 청구항 표현과 검색 위치

`PatentClaim`은 `claim_number`, 원문 `text`, `claim_type`, `depends_on`, `version_id`를 담는다. 종속 관계는 원문이 명시한 `제N항에 있어서`와 항 범위 참조에서만 추출한다. 식별할 번호 표식이 없는 텍스트는 번호를 추측하지 않아 청구항 단위로 만들지 않는다.

각 청구항은 `PatentChunk` 하나로 색인하며 `chunk_id`는 `{patent_id}_claim_{claim_number}` 형식이다. 공통 `SearchDocument`의 metadata와 `PatentEvidence`에는 청구항 번호·유형·상위항 참조·문헌 식별자·버전이 함께 연결된다. 이 범위에서는 원문 내 문자 오프셋을 API가 제공하지 않으므로 청구항 번호가 원문 위치의 기준이다.

한 문헌에서 아이디어 기술 표현과 일치하는 청구항을 우선 최대 5개까지 인용한다. 보고서에는 최대 5개 문헌을 담되, 한 문헌의 독립항·종속항을 함께 인용할 수 있다.

## 실행과 테스트

분석 함수는 함수 인자로 `collection`, `embed_fn`, `query_llm_fn`, `claim_fetcher`, `kipris_search_fn`, `comparison_fn`을 주입할 수 있다. 테스트와 외부 API 권한이 없는 환경에서는 Mock을 주입해 검색·폴백·인용 계약을 확인한다. 실제 API 사용 시에는 특허 검색 및 청구항 endpoint의 KIPRIS Plus 상품 이용 권한이 필요하며, 이 저장소 환경에서는 인증된 실호출을 수행하지 않았다.

테스트:

```bash
python -m pytest tests/test_patent_claims.py tests/test_patent_analysis_service.py
```
