"""첫 홈 방문의 문구 이동과 순차 등장 연출. 축소 동작 설정에서는 즉시 표시한다."""


def intro_markup():
    return """<style>
    @keyframes landingReveal{from{opacity:0;visibility:hidden;transform:translateY(14px)}to{opacity:1;visibility:visible;transform:translateY(0)}}
    @keyframes landingTitleReveal{from{opacity:0}to{opacity:1}}
    .st-key-landing .hero-copy h1{opacity:0;animation:landingTitleReveal .16s ease 1.8s forwards;}
    .st-key-brandbar{opacity:0;animation:landingReveal .45s ease 1.55s forwards;}
    .st-key-landing .hero-copy>.eyebrow,.st-key-landing .hero-copy>p,.st-key-landing .hero-note{opacity:0;animation:landingReveal .55s ease 1.95s forwards;}
    .st-key-hero_art .paper-scene{opacity:0;animation:landingReveal .65s ease 2.15s forwards;}
    .st-key-hero_art .st-key-lens_start{opacity:0;visibility:hidden;animation:landingReveal .65s ease 2.8s forwards;}
    @media(prefers-reduced-motion:reduce){.st-key-brandbar,.st-key-landing .hero-copy h1,.st-key-landing .hero-copy>.eyebrow,.st-key-landing .hero-copy>p,.st-key-landing .hero-note,.st-key-hero_art .paper-scene,.st-key-hero_art .st-key-lens_start{animation:none!important;opacity:1!important;visibility:visible!important;transform:none!important;}}
    </style><script>(() => {
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        document.querySelectorAll('[data-idealens-intro]').forEach(el => el.remove());
        const start = () => {
            const title = document.querySelector('.st-key-landing .hero-copy h1');
            if (!title) return false;
            const rect = title.getBoundingClientRect();
            if (!rect.width || !rect.height) return false;
            const styles = getComputedStyle(title);
            const ghost = title.cloneNode(true);
            ghost.querySelectorAll('a').forEach(el => el.remove());
            ghost.setAttribute('aria-hidden', 'true');
            ghost.setAttribute('data-idealens-intro', '');
            ghost.removeAttribute('id');
            Object.assign(ghost.style, {position:'fixed',left:rect.left+'px',top:rect.top+'px',width:rect.width+'px',height:'auto',margin:'0',padding:'0',font:styles.font,letterSpacing:styles.letterSpacing,lineHeight:styles.lineHeight,color:styles.color,opacity:'1',zIndex:'100',pointerEvents:'none',transformOrigin:'center center',animation:'none'});
            ghost.style.setProperty('font-size', styles.fontSize, 'important');
            ghost.style.setProperty('font-weight', styles.fontWeight, 'important');
            ghost.style.setProperty('line-height', styles.lineHeight, 'important');
            document.body.appendChild(ghost);
            const scale = Math.max(1, Math.min(1.7, (innerWidth - 40) / rect.width));
            const dx = innerWidth / 2 - (rect.left + rect.width / 2);
            const dy = innerHeight * .43 - (rect.top + rect.height / 2);
            const opening = `translate(${dx}px,${dy}px) scale(${scale})`;
            const animation = ghost.animate([{transform:opening,offset:0},{transform:opening,offset:.32},{transform:'translate(0,0) scale(1)',offset:1}], {duration:1800,easing:'cubic-bezier(.22,.7,.2,1)',fill:'forwards'});
            animation.onfinish = () => ghost.remove();
            setTimeout(() => ghost.remove(), 2300);
            return true;
        };
        if (!start()) {
            const observer = new MutationObserver(() => {if (start()) observer.disconnect();});
            observer.observe(document.body, {childList:true,subtree:true});
            setTimeout(() => observer.disconnect(), 1200);
        }
    })();</script>"""
