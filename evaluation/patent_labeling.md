# 특허 검색 평가 라벨링 가이드

이 문서는 특허 검색 평가 후보를 기술적 관련성 기준으로 일관되게 라벨링하는 방법을 설명한다. 라벨은 특정 검색 방식의 순위가 아니라 문헌과 기술 요소의 관계를 평가한다.

## 라벨 정의

- `1` (관련): 특허가 질의의 기술 요소와 같은 기술적 문제·기능·구성 또는 작동 원리 중 핵심 부분을 다룬다. 제목·요약만으로 판단하기 어렵다면 링크의 원문, 특히 청구항을 확인한다.
- `0` (비관련): 산업이나 제품 분야만 같거나 단어가 겹칠 뿐, 해결 과제·기술 기능·구성이 실질적으로 다르다. 시장 동향·고객·사업 모델만 다루는 문헌도 비관련이다.
- 판단이 어려우면 값을 비워두고 `note`에 확인이 필요한 이유를 적는다. 문항의 모든 후보가 판정될 때까지 해당 문항은 평가에서 제외된다.

문헌이 아이디어 전체와 같아야 관련한 것은 아니다. 평가 질의의 `technical_element`에 적힌 구성이나 기능을 구체적으로 다루는지 판단한다. 분야 이름이나 검색어 일치만으로 `1`을 주지 않는다.

## 편향을 줄이는 절차

1. `python -m evaluation.patent_labeling export`로 후보를 만든다.
2. `evaluation/labels/patent_candidates.csv`의 제목·요약·청구항 번호·KIPRIS 검색 링크를 확인한다. 원문 URL이 색인에 없으면 출원번호로 KIPRIS 검색 주소를 만든다. 검색 결과에서 출원번호와 발명의 명칭이 후보 행과 맞는지 확인한다.
3. 사람이 확인한 문헌은 `relevant`에 `0` 또는 `1`을 기록하고 `review_status=reviewed`, `label_source=human`으로 설정한다. 판정이 어려우면 `relevant`를 비운 채 `review_status=hold`, `label_source=human`으로 설정하고 `note`에 확인할 이유를 적는다.
4. AI가 만든 초안은 `label_source=ai_draft`로 표시한다. AI 초안은 `review_status=reviewed`로 바꾸지 않으면 평가 정답에 포함되지 않는다.
5. 후보 라벨을 저장한 뒤 `python -m evaluation.patent_labeling import`로 평가 문항에 반영한다. 케이스의 모든 후보가 사람 검토 완료 상태여야 점수를 계산할 수 있다.

라벨링용 CSV에는 검색 방식, 검색 순위, reranker 점수를 포함하지 않는다. 원문 확인이 필요한 경우에도 검색 순위를 근거로 삼지 않는다. `source_id`는 문헌을 확인하고 중복을 판단하는 식별자로만 사용한다.

## 기록과 해석

- 비교 대상 검색 방식은 동일한 평가 문항·색인·후보 집합으로 평가한다.
- 모든 후보가 판정된 문항만 지표 계산에 포함한다. 라벨링된 후보 집합 밖의 검색 결과는 `unjudged`로 별도 보고한다.
- `review_status=reviewed`만으로는 충분하지 않으며 `label_source=human`과 `relevant=0/1`이 모두 있어야 사람 정답으로 집계한다. `hold`, 빈 값, AI 초안은 미판정으로 센다.
- 라벨 수가 적거나 판단이 불일치하는 경우 이를 함께 기록하고, 작은 평가셋의 평균값을 일반 성능 보장처럼 해석하지 않는다.
- 현재 평가는 사람 관련도 라벨을 기준으로 한다. 자동 판정이나 LLM 초안은 사람 라벨을 대신하지 않는다.

## 청킹·집계·리랭킹 실험

`python -m evaluation.patent_chunk_rerank_experiment run`은 현재 로컬 특허 코퍼스의 질의·분야별 후보를 생성한다. 결과는 Git 제외 경로 `data/patents/processed/chunk_rerank_experiment/candidates.csv`에 기록한다. 이 후보 CSV에는 실험 방식과 순위를 넣지 않으므로, 순위를 보지 말고 질의의 `technical_element`, 발명의 명칭, 초록, 청구항 원문과 종속 관계, KIPRIS 문헌 식별자를 확인해 라벨링한다.

각 후보에 `relevant=0` 또는 `relevant=1`, `review_status=reviewed`, `label_source=human`을 입력한다. 원문 확인이 어렵거나 근거가 모자라면 `relevant`를 비우고 `review_status=hold`, `label_source=human`으로 두고 `note`에 이유를 남긴다. 모든 후보의 사람 판정이 끝나기 전에는 해당 질의·분야 풀의 지표를 계산하지 않는다. AI 초안, 빈 라벨, 보류는 평가 정답에 포함되지 않는다.

`python -m evaluation.patent_chunk_rerank_experiment score`는 완료된 풀에 한해 candidate Recall@K, Hit@5, Precision@5, Recall@5, MRR@5, nDCG@5 및 지연시간을 계산한다. Recall 분모는 이 실험의 로컬 후보 풀에서 판정한 관련 문헌으로 제한된다. 후보 풀 밖 관련 문헌은 확인되지 않으며, 현재 분야별 코퍼스가 14건이면 K=20 후보가 전체 코퍼스와 같아 후보 재현율의 차이가 드러나지 않는다. 결과를 코퍼스 밖의 일반 검색 성능으로 해석하지 않는다.
