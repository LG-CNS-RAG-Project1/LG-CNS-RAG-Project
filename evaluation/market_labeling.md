# 시장 검색 평가 라벨링 기준

`evaluation/labels/market_candidates.csv`의 `relevant` 열에 문항(행의 `question`)마다 1 또는 0을 적는다.
판단은 제목(`title`)과 요약(`summary`)으로 하고, 애매할 때만 링크를 연다.

## 1 = 관련

기사가 해당 아이디어의 해당 차원을 판단하는 데 직접 쓸 수 있는 내용을 담고 있다.

| 차원 | 1로 보는 내용 |
|---|---|
| 수요 (`demand`) | 같은 기술 범주의 도입 확대·보급 현황·도입 의향, 대상 고객층의 자동화·전환 수요 |
| 경쟁 (`competition`) | 같은 문제를 푸는 기업·제품·솔루션의 출시·공급, 대체 방식 |
| 가격 (`price`) | 해당 솔루션의 가격·가격대·가격 수준(저렴·고가 비교), 과금 방식(구매·임대·구독), 도입·구축·통합 비용과 그 부담, 솔루션 도입으로 생긴 비용 절감. 수치가 없어도 된다 |
| 구매자 (`buyer`) | 실제 도입 기업·현장 사례, 특정 기업의 도입 계획·확대 발표, 납품·공급 계약 |
| 도입장벽 (`adoption_barrier`) | 비용 부담, 인력·기술 부족, 기존 설비 연동 어려움, 규제 |

- 기술은 같은 종류(예: 예지보전, 협동로봇, AI 비전 검사, FEMS)면 되고 센서·부품·구현 방식까지 같을 필요는 없다.
- 구매자·수요에서는 고객 업종이 아이디어와 달라도 같은 기술을 실제 도입한 사례면 1이다.

## 0 = 비관련

- 주가·시가총액·상장·투자 심리 등 주식 시황 (가격 차원의 "가격"은 제품 가격이다)
- 가격 차원에서 솔루션과 연결되지 않은 일반 비용 압박(인건비·전기요금 상승 등), 기업 매출·이익, 다른 기술의 비용만 다룬 기사 (일반 비용 압박은 수요 차원에서는 1일 수 있다)
- 관련성과 근거의 강도는 다르다. 수치가 없는 기사도 관련(1)일 수 있으며, 강도는 분석 단계의 판정(확인됨·신호만 확인)에서 다룬다.
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

사람·LLM 판정이 다른 행은 `evaluation/labels/market_adjudication.csv`에서 요약과 LLM 판정 이유를
함께 보고 사람이 최종값(`final`)을 정해 후보 CSV에 반영했다.

## 현재 라벨 구성

| 파일 | 내용 |
|---|---|
| `labels/market_candidates.csv` | 최종 라벨 423행 (25문항 × 벡터·차원 표현 후보 12건 = 300행, 검색 방식 비교용 추가 후보 123행) |
| `labels/market_llm_labels_v1.csv` · `_v2.csv` | 판정 기준 보완 전 LLM 판정 (표본 문항) |
| `labels/market_llm_labels.csv` | 현재 프롬프트(v3) LLM 판정 423행 |
| `labels/market_adjudication.csv` | 사람·LLM 불일치 24행과 최종 판정 |

- 사람 라벨 72행(6문항): 블라인드 라벨 후 불일치 행 최종 판정. 최종 판정에서 LLM 판정이 채택된 비율 21/24.
- LLM 라벨 228행: 확신이 낮은 60행을 사람이 검토해 19행 수정(`label_source=human`).
- 검색 방식 비교용 추가 후보 123행(`pool`=`bm25`·`hybrid`·`bm25+hybrid`, `market_labeling extend`): LLM 라벨, 확신이 낮은 9행을 사람이 검토해 수정 0행.
- 블라인드 일치도(사람 vs LLM): 프롬프트 조정에 쓴 3문항 72%(v1) → 78%(v2), 조정에 쓰지 않은 3문항 56%(v2, kappa 0.04).
  문항별 관련성 판단 자체가 모호한 경우가 많아, 최종 라벨은 사람 판정·검토를 거친 값으로 본다.
