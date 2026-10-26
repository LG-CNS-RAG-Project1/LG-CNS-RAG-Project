# 빠른 조사 화면 실행·시연

```powershell
python -m pip install -r requirements-ui.txt
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8505
```

1. 큰 입력란에 아이디어를 작성하거나 예시를 불러온다. 우측은 세션의 최근 입력이다.
2. 핵심 구성 확인에서 최대 7개 항목을 편집·이동·삭제한 뒤 조사를 시작한다.
3. 좌측 구성, 중앙 특허·시장 후보, 우측 선택 목록을 확인한다. 문헌 상세를 읽고 자료를 추가한다.
4. 최소 2건 선택 후 종합 보고서 생성. 양쪽 조사 자료가 있는지 확인한다.
5. 보고서는 선택 문헌만 담는다. 메모 입력 후 Markdown을 내려받는다.

AI 추출·실제 검색·가격 수집·병렬 분석은 미연결이다. 예시는 가상 자료이며 사용자 입력에는 예시 분석을 적용하지 않는다. [참고 구조·구현 경계](quick-research-ui.md)를 확인한다.
