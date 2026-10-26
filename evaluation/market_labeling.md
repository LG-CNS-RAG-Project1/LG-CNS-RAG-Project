# 시장 검색 평가 라벨링 기준

`evaluation/labels/market_candidates.csv`의 `relevant` 열에 문항(행의 `question`)마다 1 또는 0을 적는다.
판단은 제목(`title`)과 요약(`summary`)으로 하고, 애매할 때만 링크를 연다.

## 1 = 관련

기사가 해당 아이디어의 해당 차원을 판단하는 데 직접 쓸 수 있는 내용을 담고 있다.

| 차원 | 1로 보는 내용 |
|---|---|
| 수요 (`demand`) | 같은 기술 범주의 도입 확대·보급 현황·도입 의향, 대상 고객층의 자동화·전환 수요 |
| 경쟁 (`competition`) | 같은 문제를 푸는 기업·제품·솔루션의 출시·공급, 대체 방식 |
| 가격 (`price`) | 장비·서비스 가격, 도입·구축 비용, 비용 비교 수치 |
| 구매자 (`buyer`) | 실제 도입 기업·현장 사례, 납품·공급 계약 |
| 도입장벽 (`adoption_barrier`) | 비용 부담, 인력·기술 부족, 기존 설비 연동 어려움, 규제 |

## 0 = 비관련

- 주가·시가총액·상장·투자 심리 등 주식 시황 (가격 차원의 "가격"은 제품 가격이다)
- 기술은 같지만 해당 차원과 관계없는 내용 (예: 가격 문항에 신제품 출시만 다룬 기사)
- 다른 기술·산업이 중심인 기사 (예: 협동로봇 문항에 휴머노이드 개발만 다룬 기사)
- 아이디어와 연결되지 않는 일반 정책·행사 소개

## 작성 규칙

- 같은 기사가 여러 문항에 나오면 문항마다 따로 판단한다.
- 애매하면 0으로 두고 `note`에 이유를 짧게 적는다.
- `relevant`·`note` 외의 열은 수정하지 않는다. 행 순서는 검색 순위와 관계없다.
- 엑셀 기본 CSV 형식으로 저장해도 된다.

## LLM 초안과 사람 검토

라벨은 LLM 초안을 사람이 검토하는 방식으로 만든다. 판정 기준은 이 문서와 같은 내용을
[prompts/market_label_judge.md](../prompts/market_label_judge.md)에 담아 `gpt-4o`에 준다.

1. 사람이 일부 문항(예: `SF-01-price`, `SF-03-buyer`)을 LLM 결과를 보지 않고 먼저 라벨링한다.
2. `python -m evaluation.market_judge prelabel`: LLM 판정을 `evaluation/labels/market_llm_labels.csv`에 따로 저장한다.
3. `python -m evaluation.market_judge agreement`: 사람 라벨과 LLM 판정의 일치율·Cohen's kappa를 확인한다.
   일치율이 낮으면 LLM 초안을 쓰지 않고 사람이 전체를 라벨링한다.
4. `python -m evaluation.market_judge merge`: 후보 CSV의 빈 `relevant`만 LLM 판정으로 채운다(기존 파일은 백업).
   - `label_source`: `human`(사람 라벨) / `llm`(LLM 초안)
   - `review`: LLM 확신이 낮은 행은 `확인`. 사람이 검토해 값을 고치면 `label_source`를 `human`으로 바꾼다.
5. `python -m evaluation.market_labeling import`로 문항에 반영한다.
