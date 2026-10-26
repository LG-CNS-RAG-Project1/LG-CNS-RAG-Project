"""종이 메타포를 사용하는 홈 비주얼과 단계 안내."""

from base64 import b64encode
from pathlib import Path


def hero():
    photo = b64encode(
        Path(__file__).with_name("assets").joinpath("paper-reference.jpg").read_bytes()
    ).decode("ascii")
    return f"""<section class="paper-hero" aria-label="아이디어를 구체화하는 네 단계">
      <div class="hero-copy"><span class="eyebrow">IDEALENS · IDEA TO EVIDENCE</span>
      <h1>한 장의 생각에서,<br>근거 있는 아이디어로.</h1>
      <p>흩어진 생각을 정리하고, 특허와 시장을 나란히 살펴보세요.<br>한 장씩 넘길수록 다음 질문이 선명해집니다.</p>
      <a class="hero-cta" href="#idea-input" target="_self">내 아이디어 펼치기 <span>↗</span></a>
      <span class="hero-note">입력 → 구체화 → 근거 연결 → 보고서</span></div>
      <div class="paper-scene" style="background-image:url(data:image/jpeg;base64,{photo})">
        <div class="visual-paper back-paper" aria-hidden="true"></div>
        <div class="visual-paper middle-paper" aria-hidden="true"></div>
        <div class="visual-paper front-paper"><span class="paper-number">01 — 04</span>
          <h2>생각을 펼치면,<br>가능성이 보입니다.</h2><div class="paper-rule"></div>
          <div class="mini-row"><b>01</b><span>아이디어를 적고</span></div>
          <div class="mini-row"><b>02</b><span>핵심을 구체화하고</span></div>
          <div class="mini-row"><b>03</b><span>특허 + 시장을 연결해</span></div>
          <div class="mini-row"><b>04</b><span>검토 노트로 완성합니다</span></div>
          <span class="paper-footer">YOUR NEXT IDEA, IN FOCUS.</span>
        </div></div></section>"""
