"""종이 메타포를 사용하는 홈 비주얼과 단계 안내."""

import re
from pathlib import Path
from base64 import b64encode
from functools import lru_cache


def _drawing(match):
    svg = (
        match.group()
        .replace(
            "<svg ",
            '<svg xmlns="http://www.w3.org/2000/svg" stroke="#52715e" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" ',
            1,
        )
        .replace(
            'fill="none" aria-hidden="true">',
            'fill="none"><style>.dimension-line{stroke:#839384;stroke-width:.6;stroke-dasharray:2 3}.market-trace{stroke:#1d7b6a;stroke-width:1.8}.market-bars{stroke:#c4ad68;stroke-width:7}text{fill:#52715e;stroke:none;font:8px Georgia,serif}</style>',
        )
    )
    encoded = b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img class="research-drawing" src="data:image/svg+xml;base64,{encoded}" alt="" />'


def hero():
    markup = """<section class="paper-hero" aria-label="아이디어를 구체화하는 조사 노트">
      <div class="hero-copy"><span class="eyebrow">IDEALENS · IDEA TO EVIDENCE</span>
      <h1><span class="hero-title-line">한 장의 생각에서,</span><span class="hero-title-line">근거 있는 아이디어로.</span></h1>
      <p>흩어진 생각을 정리하고, 특허와 시장을 나란히 살펴보세요.<br>한 장씩 넘길수록 다음 질문이 선명해집니다.</p>
      <span class="hero-note">구체화 → 특허·시장 검토 → 보고서</span>
      </div>
      <div class="paper-scene">
        <div class="visual-paper back-paper" aria-hidden="true"></div>
        <div class="visual-paper middle-paper" aria-hidden="true"></div>
        <div class="visual-paper front-paper">
          <div class="dossier-top"><span>IDEALENS / RESEARCH NOTE</span><span>01—03</span></div>
          <div class="research-panels" aria-label="특허 도면과 시장 흐름을 표현한 개념도">
            <div class="research-panel"><span class="figure-label">FIG. 01 · 특허·기술</span>
              <svg viewBox="0 0 140 95" fill="none" aria-hidden="true">
                <path d="M17 26H53M87 26H123M70 43V68M35 68H105"/>
                <rect x="53" y="12" width="34" height="30" rx="2"/>
                <circle cx="70" cy="27" r="9"/><circle cx="70" cy="27" r="3"/>
                <rect x="20" y="68" width="30" height="17" rx="2"/><rect x="90" y="68" width="30" height="17" rx="2"/>
                <path d="M12 7H128M12 3V11M128 3V11M128 18V83M124 18H132M124 83H132" class="dimension-line"/>
                <text x="15" y="22">A</text><text x="94" y="62">B</text>
              </svg>
            </div>
            <div class="research-panel"><span class="figure-label">FIG. 02 · 시장·수요</span>
              <svg viewBox="0 0 140 95" fill="none" aria-hidden="true">
                <path d="M16 13V82H127M16 60H127M16 38H127M16 16H127" class="dimension-line"/>
                <path d="M25 72L48 54L70 61L93 34L117 23" class="market-trace"/>
                <circle cx="25" cy="72" r="3"/><circle cx="48" cy="54" r="3"/><circle cx="70" cy="61" r="3"/><circle cx="93" cy="34" r="3"/><circle cx="117" cy="23" r="3"/>
                <path d="M25 81V74M48 81V66M70 81V71M93 81V53M117 81V44" class="market-bars"/>
              </svg>
            </div>
          </div>
          <div class="dossier-footer"><span>IDEA → EVIDENCE → INSIGHT</span><span>개념도 · 실제 분석 아님</span></div>
        </div>
        </div></section>"""

    return re.sub(r"<svg\b.*?</svg>", _drawing, markup, flags=re.DOTALL)


@lru_cache(maxsize=1)
def hero_parts():
    """문서와 설명을 독립된 반응형 열에 배치하기 위한 마크업."""
    markup = hero()
    start = markup.index('<div class="hero-copy">')
    scene = markup.index('<div class="paper-scene">')
    return markup[start:scene], markup[scene : markup.rindex("</section>")]


@lru_cache(maxsize=1)
def brand_style():
    """홈 버튼에 벡터 심볼을 적용하고 텍스트 이름과 클릭 동작을 유지한다."""
    symbol = (
        Path(__file__).with_name("assets").joinpath("idealens-symbol.svg").read_bytes()
    )
    encoded = b64encode(symbol).decode("ascii")
    lens = b64encode(
        Path(__file__)
        .with_name("assets")
        .joinpath("idealens-start-lens.svg")
        .read_bytes()
    ).decode("ascii")
    return f"""<style>
.st-key-brandbar .st-key-home button{{display:flex;align-items:center;gap:8px;padding:0;border:0;background:transparent;}}
.st-key-brandbar .st-key-home button:before{{content:"";display:block;flex:0 0 35px;width:35px;height:35px;background:url("data:image/svg+xml;base64,{encoded}") center/contain no-repeat;}}
.st-key-brandbar .st-key-home button p{{font-size:23px;font-weight:750;letter-spacing:-1px;color:#19594c;white-space:nowrap;}}
.st-key-brandbar .st-key-home button:hover{{box-shadow:none;}}
.st-key-lens_start button:before{{background-image:url("data:image/svg+xml;base64,{lens}");}}
</style>"""
