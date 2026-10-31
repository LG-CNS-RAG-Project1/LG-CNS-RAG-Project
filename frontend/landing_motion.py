"""실제 제목의 이동과 문서·돋보기의 순차 등장을 한 타임라인으로 연결한다."""

from streamlit.components.v2 import component

_intro_completion = component(
    "landing_intro_completion",
    js="""
export default function({setStateValue}) {
  const complete = () => setStateValue('completed', true);
  window.addEventListener('idealens:intro-completed', complete);
  if (document.querySelector('.st-key-landing[data-intro-state="done"]')) complete();
  return () => window.removeEventListener('idealens:intro-completed', complete);
}
""",
)


def intro_completed():
    """브라우저에서 연출을 끝낸 뒤에만 세션의 재생 완료를 알린다."""
    return (
        _intro_completion(
            key="landing_intro_completion", on_completed_change=lambda: None
        ).completed
        is True
    )


def intro_styles():
    """홈 마크업보다 먼저 적용해 완성 화면이 먼저 번쩍이는 현상을 막는다."""
    return """<style>
    @keyframes introFallback {to {opacity:1;visibility:visible;pointer-events:auto;}}
    @keyframes introFade {from {opacity:0;} to {opacity:1;}}
    @keyframes introReveal {
      from {opacity:0;transform:translateY(10px);}
      to {opacity:1;transform:translateY(0);}
    }
    .st-key-brandbar {opacity:0;visibility:hidden;animation:introFallback 0s 6.5s forwards;}
    [data-testid="stMainBlockContainer"]:has(.st-key-landing[data-intro-state="playing"]) .st-key-brandbar {visibility:visible;animation:introReveal .4s 2.65s both;}
    [data-testid="stMainBlockContainer"]:has(.st-key-landing[data-intro-state="done"]) .st-key-brandbar {opacity:1;visibility:visible;animation:none;}
    .st-key-landing:not([data-intro-state="done"]) .hero-copy h1,
    .st-key-landing:not([data-intro-state="done"]) .hero-copy>.eyebrow,
    .st-key-landing:not([data-intro-state="done"]) .hero-copy>p,
    .st-key-landing:not([data-intro-state="done"]) .hero-note,
    .st-key-landing:not([data-intro-state="done"]) .paper-scene,
    .st-key-landing:not([data-intro-state="done"]) .st-key-lens_start {
      opacity:0;animation:introFallback 0s 6.5s forwards;
    }
    .st-key-landing:not([data-intro-state="done"]) .st-key-lens_start {visibility:hidden;}
    .st-key-landing[data-intro-state="playing"] .hero-copy h1 {animation:none;will-change:transform,opacity;}
    .st-key-landing[data-intro-state="playing"] .hero-title-line:first-child {animation:introReveal .35s .05s both;}
    .st-key-landing[data-intro-state="playing"] .hero-title-line:last-child {animation:introReveal .35s .38s both;}
    .st-key-landing[data-intro-state="playing"] .hero-copy>.eyebrow,
    .st-key-landing[data-intro-state="playing"] .hero-copy>p,
    .st-key-landing[data-intro-state="playing"] .hero-note {animation:introReveal .5s 2.8s both;}
    .st-key-landing[data-intro-state="playing"] .paper-scene {animation:introReveal .6s 3s both;}
    .st-key-landing[data-intro-state="playing"] .st-key-lens_start {visibility:visible;animation:introReveal .5s 3.55s both;}
    .st-key-landing:not([data-intro-state="done"]) .st-key-lens_start button:before {animation-play-state:paused;}
    [data-testid="stMainBlockContainer"]:has(.st-key-landing:not([data-intro-state="done"])) :is(.st-key-research_rail_public,.st-key-research_rail_workspace) {opacity:0;animation:introFallback 0s 6.5s forwards;pointer-events:none;}
    [data-testid="stMainBlockContainer"]:has(.st-key-landing[data-intro-state="playing"]) :is(.st-key-research_rail_public,.st-key-research_rail_workspace) {animation:introFade .35s 3.8s both;}
    @media(prefers-reduced-motion:reduce) {
      .st-key-brandbar,.st-key-landing .hero-title-line,
      .st-key-landing .hero-copy h1,.st-key-landing .hero-copy>.eyebrow,
      .st-key-landing .hero-copy>p,.st-key-landing .hero-note,
      .st-key-landing .paper-scene,.st-key-landing .st-key-lens_start,
      [data-testid="stMainBlockContainer"]:has(.st-key-landing) :is(.st-key-research_rail_public,.st-key-research_rail_workspace) {
        animation:none!important;opacity:1!important;visibility:visible!important;transform:none!important;pointer-events:auto!important;
      }
    }
    </style>"""


def intro_markup():
    """레이아웃을 기다린 뒤 제목 자체를 움직이고 중단 시 즉시 최종 배치를 복원한다."""
    return """<script>(() => {
      let root, titleAnimation, revealTimer, waitTimer, pendingObserver, removalObserver;
      let finished = false;
      const events = new AbortController();
      const finish = () => {
        if (finished) return;
        finished = true;
        if (root) {
          root.dataset.introState = 'done';
          window.dispatchEvent(new Event('idealens:intro-completed'));
        }
        titleAnimation?.cancel();
        clearTimeout(revealTimer);
        clearTimeout(waitTimer);
        pendingObserver?.disconnect();
        removalObserver?.disconnect();
        events.abort();
      };
      const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
      const start = async () => {
        root = document.querySelector('.st-key-landing');
        const title = root?.querySelector('.hero-copy h1');
        const lens = root?.querySelector('.st-key-lens_start button');
        if (!title || !lens) return false;
        pendingObserver?.disconnect();
        clearTimeout(waitTimer);
        if (root.dataset.introState) return true;
        root.dataset.introState = 'preparing';
        if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
          finish();return true;
        }
        document.querySelector('[data-testid="stMain"]')?.scrollTo({top:0,behavior:'instant'});
        const initialWidth = innerWidth;
        window.addEventListener('resize', () => {
          if (Math.abs(innerWidth - initialWidth) > 80) finish();
        }, {passive:true,signal:events.signal});
        for (const event of ['pointerdown','keydown','wheel','touchstart']) {
          window.addEventListener(event, finish, {once:true,passive:true,signal:events.signal});
        }
        removalObserver = new MutationObserver(() => {if (!root.isConnected) finish();});
        removalObserver.observe(document.body,{childList:true,subtree:true});
        try {
          await Promise.race([
            Promise.allSettled([
              document.fonts.ready,
              ...[...root.querySelectorAll('img')].map(image => image.decode()),
            ]),
            new Promise(resolve => setTimeout(resolve,300)),
          ]);
          await frame();await frame();
          if (finished || !root.isConnected) {finish();return true;}
          const rect = title.getBoundingClientRect();
          if (!rect.width || !rect.height) {finish();return true;}
          const scale = Math.max(1,Math.min(innerWidth < 700 ? 1.08 : 1.45,(innerWidth-48)/rect.width));
          const dx = innerWidth/2 - (rect.left+rect.width/2);
          const dy = innerHeight*.43 - (rect.top+rect.height/2);
          const opening = `translate(${dx}px,${dy}px) scale(${scale})`;
          root.dataset.introState = 'playing';
          titleAnimation = title.animate([
            {opacity:1,transform:opening,offset:0},
            {opacity:1,transform:opening,offset:.68,easing:'cubic-bezier(.22,.7,.2,1)'},
            {opacity:1,transform:'translate(0,0) scale(1)',offset:1},
          ],{duration:2900,easing:'linear',fill:'both'});
          revealTimer = setTimeout(finish,4300);
        } catch {finish();}
        return true;
      };
      start().then(started => {
        if (started || finished) return;
        pendingObserver = new MutationObserver(() => {start();});
        pendingObserver.observe(document.body,{childList:true,subtree:true});
        waitTimer = setTimeout(finish,1000);
      });
    })();</script>"""
