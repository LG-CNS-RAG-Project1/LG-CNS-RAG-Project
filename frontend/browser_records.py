"""사용자가 선택한 조사 기록만 현재 브라우저 저장소에 보관한다."""

import json

import streamlit as st
from streamlit.components.v2 import component

_storage = component(
    "idealens_browser_records",
    html="""<div><button id="save">이 브라우저에 저장</button>
    <button id="restore">저장한 기록 불러오기</button>
    <button id="clear">브라우저 기록 삭제</button><p id="status" role="status"></p></div>""",
    css="""button {padding:.6rem .8rem;margin:.2rem;border:1px solid #bdcec5;
    border-radius:8px;background:#fffef7;color:#19564e;cursor:pointer;font:inherit;}
    button:focus-visible {outline:3px solid #19796f;} p {font:inherit;color:#42675e;}""",
    js="""export default function({data, parentElement, setTriggerValue}) {
      const key = 'idealens.records.v1';
      const status = parentElement.querySelector('#status');
      const show = text => { status.textContent = text; };
      parentElement.querySelector('#save').onclick = () => {
        try {
          const raw = JSON.stringify(data);
          if (new TextEncoder().encode(raw).length > 5000000) {
            show('저장 용량을 초과했습니다. JSON 파일로 보관해 주세요.'); return;
          }
          localStorage.setItem(key, raw);
          show('이 브라우저에 저장했습니다. 공용 기기라면 사용 후 삭제하세요.');
        } catch (_) { show('브라우저 저장이 차단되었거나 공간이 부족합니다. JSON 파일로 보관해 주세요.'); }
      };
      parentElement.querySelector('#restore').onclick = () => {
        try {
          const raw = localStorage.getItem(key);
          if (!raw) { show('이 브라우저에 저장한 기록이 없습니다.'); return; }
          if (new TextEncoder().encode(raw).length > 5000000) {
            show('저장된 기록이 너무 큽니다.'); return;
          }
          setTriggerValue('restored', raw);
        } catch (_) { show('브라우저 기록을 읽을 수 없습니다.'); }
      };
      parentElement.querySelector('#clear').onclick = () => {
        try {
          localStorage.removeItem(key);
          show('브라우저에 보관한 기록을 삭제했습니다. 현재 세션 기록은 별도로 지울 수 있습니다.');
        } catch (_) { show('브라우저 기록을 삭제할 수 없습니다.'); }
      };
    }""",
)


def render_browser_records(s, validate):
    """기록 복원은 파일 가져오기와 같은 검증을 거쳐 세션에 반영한다."""
    st.caption(
        "직접 저장한 기록만 이 기기의 현재 브라우저에 남습니다. 다른 기기·브라우저와 동기화하지 않습니다. "
        "비공개 모드·브라우저 데이터 삭제 시 사라질 수 있습니다. 불러온 내용은 화면 표시를 위해 현재 앱 세션에 전달됩니다."
    )
    result = _storage(
        data={"format": "idealens-records-v1", "records": s.records},
        key="browser_records",
        on_restored_change=lambda: None,
    )
    if result.restored:
        try:
            s.records = validate(result.restored.encode("utf-8"))
            st.success("이 브라우저에 저장한 기록을 불러왔습니다.")
            st.rerun()
        except (ValueError, UnicodeError, TypeError, json.JSONDecodeError):
            st.error("기록 형식이 올바르지 않습니다. JSON 백업 파일을 확인해 주세요.")
