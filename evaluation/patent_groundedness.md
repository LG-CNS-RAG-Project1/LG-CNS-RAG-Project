# 특허 주장 근거 지지 검토 가이드

이 평가는 구성요소별 분석 주장이 인용된 특허 원문으로 지지되는지를 사람이 확인한다. 특허 검색 관련도 라벨과 별개이며 법률적 판단이 아니다.

## 실행

실제 `PatentReport` JSON을 지정해 검토 CSV를 만든다. 출력 기본 위치는 `evaluation/labels/`이며 기존 파일을 덮어쓰지 않는다.

```bash
python -m evaluation.patent_groundedness export path/to/patent_report.json
```

CSV의 `claim_statement`는 분석기의 구성요소 비교(유사점, 차이점, 미확인, 원문 일치 구절)이고 `citation_contexts`는 citation ID에 연결된 원문, 청구항 번호, 버전, 출처 URL이다. 모든 주장은 함께 묶인 인용 전체를 검토한다.

| 라벨 | 판단 기준 |
|---|---|
| `supported` | 제시된 인용 원문이 주장의 핵심 내용을 직접 뒷받침한다. |
| `partially_supported` | 일부는 근거가 있으나 주장의 다른 부분은 원문에서 확인되지 않거나 표현 범위가 넓다. |
| `unsupported` | 인용 원문이 주장과 무관하거나 주장을 뒷받침하지 않는다. |
| `insufficient_evidence` | 초록만 있거나 원문·상위항·문맥이 부족해 지지 여부를 판단할 수 없다. |

라벨과 `note`를 사람이 직접 채운 뒤 결과를 집계한다. 모든 행에 허용된 라벨이 있어야 하며, 문항 수·라벨별 분포·입력 파일 지문이 결과 JSON에 기록된다.

```bash
python -m evaluation.patent_groundedness score evaluation/labels/patent_groundedness_<hash>.csv
```

결과는 `evaluation/results/`에 저장된다. 집계는 검토 표본의 라벨 분포이며 자동 groundedness 점수나 법률 검토를 대체하지 않는다. 보고서의 구성요소 비교가 없으면 검토 대상으로 내보낼 수 없다.
