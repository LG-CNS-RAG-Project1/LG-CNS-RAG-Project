"""같은 브라우저 탭에서만 분석 작업의 불투명 연결 번호를 보관한다."""

from streamlit.components.v2 import component

_bridge = component(
    "workflow_resume",
    js="""
export default function({data,setStateValue}) {
  const key='idealens.workflow.v1';
  try {
    if(data.active) sessionStorage.setItem(key,data.active);
    const saved=sessionStorage.getItem(key);
    setStateValue('saved',saved || '');
  } catch (_) { setStateValue('saved',''); }
}
""",
)


def browser_workflow(active):
    return _bridge(
        data={"active": active or ""},
        key="workflow_resume",
        on_saved_change=lambda: None,
    ).saved
