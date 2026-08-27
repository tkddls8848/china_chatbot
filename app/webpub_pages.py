"""공개 웹의 화면. 라우팅(`webpub.py`)과 굽기(`webpub_export.py`)에서 분리한다.

여기에는 정적 문자열만 둔다. 페이지는 프로세스가 뜰 때 한 번 조립되고 요청마다
다시 만들지 않으며, 수치는 브라우저가 `/api/*`를 읽어 채운다. 외부 폰트나 CDN을
쓰지 않는 것도 같은 이유다 - 공개 웹은 자기 프로세스 밖에서 아무것도 부르지
않는다.
"""

from __future__ import annotations

SITE_NAME = "nunchi"
SITE_TAGLINE = "뉴스에서 읽는 시장의 눈치"

_STYLE = """<style>
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light dark;
  --bg:#ffffff; --bg-soft:#f7f8fa; --surface:#ffffff; --surface-2:#f8fafc;
  --border:#e6e8ec; --border-strong:#d6dae1;
  --text:#0f1729; --text-2:#485068; --muted:#8792a4;
  --accent:#2f6fed; --accent-soft:#eef3fe;
  --up:#0f9d76; --down:#e0475b;
  --radius:14px;
  --sans:-apple-system,BlinkMacSystemFont,"Pretendard","Apple SD Gothic Neo",
    "Noto Sans KR","Malgun Gothic",system-ui,sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0b0e14; --bg-soft:#0b0e14; --surface:#11151d; --surface-2:#161b25;
    --border:#222835; --border-strong:#2f3646;
    --text:#e8ecf3; --text-2:#aab3c2; --muted:#6f7c90;
    --accent:#6ea0ff; --accent-soft:#16213a;
    --up:#3ecf9a; --down:#ff6b7d;
  }
}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg-soft);color:var(--text);font-family:var(--sans);
  font-size:16px;line-height:1.72;letter-spacing:-.005em;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.wrap{max-width:880px;margin:0 auto;padding:0 22px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:3px}

/* 헤더 */
.site-head{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 86%,transparent);
  backdrop-filter:saturate(180%) blur(12px);border-bottom:1px solid var(--border)}
.site-head .wrap{display:flex;align-items:center;justify-content:space-between;gap:18px;height:60px}
.brand{display:flex;align-items:baseline;gap:2px;font-size:1.06rem;font-weight:700;
  letter-spacing:-.02em;color:var(--text)}
.brand:hover{text-decoration:none}
.brand em{font-style:normal;color:var(--muted);font-weight:500}
.nav{display:flex;gap:4px}
.nav a{padding:7px 11px;border-radius:8px;font-size:.92rem;font-weight:500;color:var(--text-2)}
.nav a:hover{background:var(--surface-2);text-decoration:none;color:var(--text)}
.nav a[aria-current="page"]{background:var(--accent-soft);color:var(--accent);font-weight:600}

/* 히어로 */
.hero{padding:64px 0 40px;border-bottom:1px solid var(--border);background:var(--bg)}
.eyebrow{font-family:var(--mono);font-size:.72rem;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent);margin:0 0 14px}
.hero h1{margin:0;font-size:clamp(1.85rem,5vw,2.6rem);line-height:1.24;
  letter-spacing:-.035em;font-weight:700}
.lede{margin:16px 0 0;max-width:60ch;font-size:1.06rem;color:var(--text-2)}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin-top:24px}
.pill{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border:1px solid var(--border-strong);
  border-radius:999px;background:var(--surface);font-family:var(--mono);font-size:.76rem;color:var(--text-2)}
.pill b{font-weight:600;color:var(--text)}
.dot{width:6px;height:6px;border-radius:50%;background:var(--up);flex:none}

/* 본문 */
main{padding:44px 0 8px}
section{margin:0 0 44px}
.sec-title{display:flex;align-items:baseline;gap:12px;margin:0 0 18px}
.sec-title h2{margin:0;font-size:1.16rem;font-weight:650;letter-spacing:-.02em}
.sec-title span{font-family:var(--mono);font-size:.74rem;color:var(--muted)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:22px}
.card+.card{margin-top:14px}
.grid2 .card+.card{margin-top:0}
.card h3{margin:0 0 8px;font-size:1rem;font-weight:650;letter-spacing:-.015em}
.card p{margin:0;color:var(--text-2)}
.card p+p{margin-top:10px}
.grid2{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(248px,1fr))}
.muted{color:var(--muted)}
.small{font-size:.86rem}

/* 지표 */
.stats{display:grid;gap:1px;background:var(--border);border:1px solid var(--border);
  border-radius:var(--radius);overflow:hidden;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.stat{background:var(--surface);padding:16px 18px}
.stat dt{margin:0 0 6px;font-size:.74rem;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;color:var(--muted)}
.stat dd{margin:0;font-family:var(--mono);font-size:1.32rem;font-weight:600;
  letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat dd.ts{font-size:1.04rem}
.stat dd.text{font-family:var(--sans);font-size:1rem;letter-spacing:-.015em;
  overflow-wrap:anywhere}
.stat dd small{display:block;margin-top:1px;font-size:.8rem;font-weight:500;color:var(--muted)}

/* 표 */
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface)}
table{border-collapse:collapse;width:100%;min-width:460px}
th,td{text-align:left;padding:12px 18px;border-bottom:1px solid var(--border);vertical-align:middle}
th{font-size:.74rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);background:var(--surface-2)}
tbody tr:last-child td{border-bottom:0}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.pos{color:var(--up)} .neg{color:var(--down)}
.mk{font-weight:600}
.mk small{display:block;font-weight:400;font-size:.76rem;color:var(--muted);font-family:var(--mono)}
.bar{position:relative;width:120px;height:6px;border-radius:3px;background:var(--surface-2)}
.bar::before{content:"";position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--border-strong)}
.bar i{position:absolute;top:0;height:6px;border-radius:3px}

/* 차트 */
.chart{border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);
  padding:12px;overflow:hidden}
.chart img{display:block;width:100%;height:auto;border-radius:8px}
.empty{padding:34px 22px;text-align:center;color:var(--muted);font-size:.92rem}

/* 단계 */
.steps{list-style:none;counter-reset:s;margin:0;padding:0}
.steps li{counter-increment:s;position:relative;padding:0 0 22px 46px}
.steps li::before{content:counter(s,decimal-leading-zero);position:absolute;left:0;top:1px;
  width:28px;height:28px;display:grid;place-items:center;border-radius:8px;
  background:var(--accent-soft);color:var(--accent);font-family:var(--mono);
  font-size:.72rem;font-weight:600}
.steps li::after{content:"";position:absolute;left:13px;top:34px;bottom:2px;width:1px;background:var(--border)}
.steps li:last-child{padding-bottom:0}
.steps li:last-child::after{display:none}
.steps b{display:block;font-weight:650;letter-spacing:-.015em}
.steps p{margin:2px 0 0;color:var(--text-2);font-size:.94rem}

/* 정의 목록 */
.spec{margin:0;display:grid;grid-template-columns:minmax(112px,180px) 1fr}
.spec dt{padding:11px 0;border-top:1px solid var(--border);font-size:.88rem;color:var(--muted)}
.spec dd{padding:11px 0;border-top:1px solid var(--border);margin:0;font-size:.94rem}
.spec dt:first-of-type,.spec dd:first-of-type{border-top:0}
.spec code{font-family:var(--mono);font-size:.86rem;background:var(--surface-2);
  border:1px solid var(--border);border-radius:6px;padding:1px 6px}

/* 안내 상자 */
.note{border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:10px;
  background:var(--surface);padding:16px 18px;color:var(--text-2);font-size:.94rem}
.note b{color:var(--text)}
.checks{margin:0;padding:0;list-style:none}
.checks li{position:relative;padding:0 0 10px 22px;color:var(--text-2);font-size:.94rem}
.checks li:last-child{padding-bottom:0}
.checks li::before{content:"—";position:absolute;left:0;color:var(--muted);font-family:var(--mono)}

/* 리서치 */
.tag{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:6px;
  font-family:var(--mono);font-size:.72rem;font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.tag-add{background:color-mix(in srgb,var(--up) 14%,transparent);color:var(--up)}
.tag-watch{background:var(--accent-soft);color:var(--accent)}
.tag-remove{background:color-mix(in srgb,var(--down) 14%,transparent);color:var(--down)}
.item{border-top:1px solid var(--border);padding:16px 0}
.item:first-of-type{border-top:0;padding-top:0}
.item:last-of-type{padding-bottom:0}
.item-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.item-head strong{font-size:1rem;letter-spacing:-.015em}
.item-head code{font-family:var(--mono);font-size:.8rem;color:var(--muted)}
.scores{margin-left:auto;display:flex;gap:12px;font-family:var(--mono);font-size:.76rem;
  color:var(--muted);font-variant-numeric:tabular-nums}
.item p{margin:8px 0 0;color:var(--text-2);font-size:.94rem}
.body-text{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;color:var(--text-2);font-size:.97rem}

/* 푸터 */
footer{border-top:1px solid var(--border);margin-top:48px;padding:28px 0 46px;
  color:var(--muted);font-size:.86rem}
footer .wrap{display:flex;flex-wrap:wrap;gap:10px 26px;align-items:baseline;justify-content:space-between}
footer nav{display:flex;gap:16px}
@media (max-width:560px){
  .hero{padding:44px 0 32px}
  .scores{margin-left:0;width:100%}
  .spec{grid-template-columns:1fr}
  .spec dd{padding-top:0;border-top:0}
}
</style>"""


def _head(title: str) -> str:
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='light dark'>"
        "<meta name='robots' content='noindex'>"
        "<title>" + title + " · " + SITE_NAME + "</title>" + _STYLE + "</head><body>"
    )


def _header(active: str) -> str:
    links = (("/", "시장"), ("/research", "리서치"), ("/about", "정보"))
    nav = "".join(
        "<a href='" + href + "'" + (" aria-current='page'" if href == active else "") + ">" + label + "</a>"
        for href, label in links
    )
    return (
        "<header class='site-head'><div class='wrap'>"
        "<a class='brand' href='/'>" + SITE_NAME + "<em>.live</em></a>"
        "<nav class='nav'>" + nav + "</nav>"
        "</div></header>"
    )


_FOOTER = (
    "<footer><div class='wrap'>"
    "<div>" + SITE_NAME + " · " + SITE_TAGLINE + " · 뉴스 감성 관측치이며 투자 조언이 아닙니다.</div>"
    "<nav><a href='/'>시장</a><a href='/research'>리서치</a><a href='/about'>정보</a></nav>"
    "</div></footer></body></html>"
)


def _hero(eyebrow: str, title: str, lede: str, pills: str = "") -> str:
    return (
        "<div class='hero'><div class='wrap'>"
        "<p class='eyebrow'>" + eyebrow + "</p>"
        "<h1>" + title + "</h1>"
        "<p class='lede'>" + lede + "</p>"
        + (("<div class='pills'>" + pills + "</div>") if pills else "")
        + "</div></div>"
    )


def _page(title: str, active: str, hero: str, main: str, script: str = "") -> str:
    return (
        _head(title)
        + _header(active)
        + hero
        + "<main><div class='wrap'>" + main + "</div></main>"
        + script
        + _FOOTER
    )


# ── 공통 스크립트 ────────────────────────────────────────────────────────────
# 값은 산출물에서 오지만 문자열은 모두 텍스트 노드로 넣거나 escape한 뒤 붙인다.
_JS_UTIL = """
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>(
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stamp=v=>{if(!v)return '-';const t=String(v).replace('T',' ');
  return t.length>16?t.slice(0,16):t;};
// 지표 칸은 폭이 좁다. 날짜와 시각을 한 줄에 두면 줄바꿈으로 칸 높이가 튄다.
const stampHtml=v=>{const t=stamp(v);const i=t.indexOf(' ');
  return i<0?esc(t):esc(t.slice(0,i))+'<small>'+esc(t.slice(i+1))+'</small>';};
const pct=v=>Math.round((Number(v)||0)*100)+'%';
"""

# ── 시장 ────────────────────────────────────────────────────────────────────

_MARKET_MAIN = """
<section>
  <dl class='stats' id='stats'>
    <div class='stat'><dt>기준 시각</dt><dd class='ts' id='s-time'>–</dd></div>
    <div class='stat'><dt>조회 기간</dt><dd id='s-days'>–</dd></div>
    <div class='stat'><dt>관측 시장</dt><dd id='s-markets'>–</dd></div>
    <div class='stat'><dt>집계 기사</dt><dd id='s-count'>–</dd></div>
  </dl>
</section>

<section>
  <div class='sec-title'><h2>감성 추이</h2><span>daily average</span></div>
  <div class='chart' id='chart'>
    <img src='/market_chart.png' alt='국가별 시장 감성 추이 차트'
      onerror="this.parentNode.innerHTML=&quot;<p class='empty'>차트가 아직 생성되지 않았습니다.</p>&quot;">
  </div>
</section>

<section>
  <div class='sec-title'><h2>국가별 수치</h2><span>-1.00 … +1.00</span></div>
  <div class='table-wrap'>
    <table>
      <thead><tr><th>시장</th><th>분포</th><th class='num'>감성</th><th class='num'>기사</th><th class='num'>관측일</th></tr></thead>
      <tbody id='rows'><tr><td colspan='5' class='empty'>산출물을 불러오는 중…</td></tr></tbody>
    </table>
  </div>
</section>

<section>
  <p class='note'><b>읽는 법.</b> 값은 해당 기간 뉴스 요약에 매긴 감성 평균이며
  −1(부정)에서 +1(긍정) 사이입니다. 시세·수익률이 아니라 보도 논조의 방향이고,
  표본이 얕은 시장일수록 하루 사이 값이 크게 움직입니다.</p>
</section>
"""

_MARKET_SCRIPT = (
    "<script>" + _JS_UTIL + """
const LABELS={CN:'중국 본토',HK:'홍콩',US:'미국',KR:'한국',JP:'일본',EU:'유럽',OTHER:'기타'};
function bar(v){const w=Math.min(Math.abs(v),1)*50;const side=v>=0?'left:50%':'right:50%';
  const color=v>=0?'var(--up)':'var(--down)';
  return "<div class='bar'><i style='"+side+";width:"+w.toFixed(1)+"%;background:"+color+"'></i></div>";}
fetch('/api/market').then(r=>r.json()).then(d=>{
  const markets=d.markets||{};
  const entries=Object.entries(markets).sort((a,b)=>(b[1].avg_sentiment||0)-(a[1].avg_sentiment||0));
  document.getElementById('s-time').innerHTML=stampHtml(d.generated_at);
  document.getElementById('s-days').textContent=d.lookback_days?d.lookback_days+'일':'–';
  document.getElementById('s-markets').textContent=entries.length||'–';
  document.getElementById('s-count').textContent=entries.reduce((n,[,v])=>n+(v.count||0),0)||'–';
  const body=document.getElementById('rows');
  if(!entries.length){body.innerHTML="<tr><td colspan='5' class='empty'>산출물이 아직 없습니다.</td></tr>";return;}
  body.innerHTML=entries.map(([code,v])=>{
    const s=Number(v.avg_sentiment||0);
    const days=Array.isArray(v.daily)?v.daily.length:0;
    return "<tr><td class='mk'>"+esc(LABELS[code]||code)+"<small>"+esc(code)+"</small></td>"
      +"<td>"+bar(s)+"</td>"
      +"<td class='num "+(s>=0?'pos':'neg')+"'>"+(s>=0?'+':'')+s.toFixed(2)+"</td>"
      +"<td class='num'>"+(v.count||0)+"</td>"
      +"<td class='num muted'>"+days+"</td></tr>";
  }).join('');
}).catch(()=>{
  document.getElementById('rows').innerHTML="<tr><td colspan='5' class='empty'>산출물을 읽지 못했습니다.</td></tr>";
});
</script>"""
)

INDEX_HTML = _page(
    "시장 컨센서스",
    "/",
    _hero(
        "market consensus",
        "국가별 뉴스 감성을<br>하루 단위로 모읍니다",
        "중국·홍콩·미국·한국 뉴스를 수집해 시장별로 하루치 요약을 만들고, "
        "그 요약에 매긴 감성 점수의 추이를 그립니다. 아래 수치는 마지막으로 "
        "계산된 산출물이며 페이지를 열 때 다시 계산하지 않습니다.",
        "<span class='pill'><span class='dot'></span>읽기 전용</span>"
        "<span class='pill'>JST 기준</span>"
        "<span class='pill'><b>GET</b> /api/market</span>",
    ),
    _MARKET_MAIN,
    _MARKET_SCRIPT,
)


# ── 리서치 ──────────────────────────────────────────────────────────────────

_RESEARCH_MAIN = """
<section>
  <dl class='stats'>
    <div class='stat'><dt>관심 주제</dt><dd class='text' id='r-sight'>–</dd></div>
    <div class='stat'><dt>기준 시각</dt><dd class='ts' id='r-time'>–</dd></div>
    <div class='stat'><dt>분석 뉴스</dt><dd id='r-news'>–</dd></div>
    <div class='stat'><dt>후보 종목</dt><dd id='r-cand'>–</dd></div>
  </dl>
</section>

<section>
  <div class='sec-title'><h2>요약</h2><span>summary</span></div>
  <div class='card'><p class='body-text' id='r-summary'>산출물을 불러오는 중…</p></div>
</section>

<section id='sec-actions' hidden>
  <div class='sec-title'><h2>종목 판단</h2><span>add · watch · remove</span></div>
  <div class='card' id='r-actions'></div>
</section>

<section id='sec-risks' hidden>
  <div class='sec-title'><h2>리스크</h2><span>risks</span></div>
  <div class='card'><ul class='checks' id='r-risks'></ul></div>
</section>

<section id='sec-critique' hidden>
  <div class='sec-title'><h2>내 뷰 반론</h2><span>view critique</span></div>
  <div class='card' id='r-critique'></div>
</section>

<section>
  <p class='note'><b>실행은 여기서 하지 않습니다.</b> 리서치는 텔레그램에서만
  실행하며 이 페이지는 마지막으로 저장된 결과를 그대로 보여 줍니다.
  종목 판단은 관심종목 정리를 돕는 메모이지 매매 권유가 아닙니다.</p>
</section>
"""

_RESEARCH_SCRIPT = (
    "<script>" + _JS_UTIL + """
const TAGS={add:['tag-add','추가'],watch:['tag-watch','주목'],remove:['tag-remove','제외']};
const ORDER={add:0,watch:1,remove:2};
function actionItem(a){
  const t=TAGS[a.action]||['tag-watch',esc(a.action)];
  const scores=[];
  if(a.relevance!=null)scores.push('관련도 '+pct(a.relevance));
  if(a.confidence!=null)scores.push('판단 '+pct(a.confidence));
  return "<div class='item'><div class='item-head'>"
    +"<span class='tag "+t[0]+"'>"+esc(t[1])+"</span>"
    +"<strong>"+esc(a.name||a.ticker||'')+"</strong>"
    +"<code>"+esc(a.ticker||'')+"</code>"
    +(scores.length?"<span class='scores'>"+scores.map(esc).join('<span>·</span>')+"</span>":"")
    +"</div>"+(a.reason?"<p>"+esc(a.reason)+"</p>":"")+"</div>";
}
fetch('/api/research').then(r=>r.json()).then(d=>{
  const res=d.last_result||{};
  document.getElementById('r-sight').textContent=d.sight||'없음';
  document.getElementById('r-time').innerHTML=stampHtml(d.generated_at);
  document.getElementById('r-news').textContent=res.news_count!=null?res.news_count:'–';
  document.getElementById('r-cand').textContent=res.candidate_count!=null?res.candidate_count:'–';
  document.getElementById('r-summary').textContent=res.summary||'저장된 분석이 없습니다.';

  const actions=(res.actions||[]).filter(a=>a&&TAGS[a.action])
    .sort((a,b)=>ORDER[a.action]-ORDER[b.action]||(b.relevance||0)-(a.relevance||0));
  if(actions.length){
    document.getElementById('r-actions').innerHTML=actions.map(actionItem).join('');
    document.getElementById('sec-actions').hidden=false;
  }
  const risks=(res.risks||[]).filter(Boolean);
  if(risks.length){
    document.getElementById('r-risks').innerHTML=risks.map(r=>"<li>"+esc(r)+"</li>").join('');
    document.getElementById('sec-risks').hidden=false;
  }
  const critique=(res.view_critique||[]).filter(c=>c&&c.point);
  if(critique.length){
    document.getElementById('r-critique').innerHTML=critique.map(c=>
      "<div class='item'><div class='item-head'><strong>"+esc(c.point)+"</strong>"
      +(c.severity!=null?"<span class='scores'>강도 "+pct(c.severity)+"</span>":"")
      +"</div></div>").join('');
    document.getElementById('sec-critique').hidden=false;
  }
}).catch(()=>{
  document.getElementById('r-summary').textContent='산출물을 읽지 못했습니다.';
});
</script>"""
)

RESEARCH_HTML = _page(
    "리서치",
    "/research",
    _hero(
        "research",
        "관심 주제를 놓고<br>반대편 근거까지 세어 봅니다",
        "관심종목과 뉴스에서 후보를 모아 추가·주목·제외를 제안하고, 세워 둔 "
        "뷰를 약화시키는 근거를 함께 남깁니다. 아래는 마지막으로 저장된 "
        "분석 한 건입니다.",
        "<span class='pill'><span class='dot'></span>읽기 전용</span>"
        "<span class='pill'>실행은 텔레그램</span>"
        "<span class='pill'><b>GET</b> /api/research</span>",
    ),
    _RESEARCH_MAIN,
    _RESEARCH_SCRIPT,
)


# ── 정보 ────────────────────────────────────────────────────────────────────

_ABOUT_MAIN = """
<section>
  <div class='sec-title'><h2>무엇을 보여 주나</h2><span>what it is</span></div>
  <div class='grid2'>
    <div class='card'>
      <h3>시장 컨센서스</h3>
      <p>중국·홍콩·미국·한국 뉴스를 시장별로 묶어 하루치 요약을 만들고,
      그 요약에 매긴 −1~+1 감성 점수의 추이를 그립니다. 개별 기사가 아니라
      하루·시장 단위의 집계만 공개합니다.</p>
    </div>
    <div class='card'>
      <h3>리서치</h3>
      <p>관심 주제를 놓고 후보 종목의 추가·주목·제외와 리스크, 그리고 그
      주제를 약화시키는 반론을 정리합니다. 마지막 결과 한 건만 보관합니다.</p>
    </div>
  </div>
</section>

<section>
  <div class='sec-title'><h2>어떻게 만들어지나</h2><span>pipeline</span></div>
  <div class='card'>
    <ol class='steps'>
      <li><b>수집</b><p>정해진 주기마다 시장별 뉴스 소스를 읽습니다. 소스 한 곳이
        실패해도 나머지 주기는 그대로 진행합니다.</p></li>
      <li><b>사전선별</b><p>번역 전에 원문을 사건 단위로 묶습니다. 최근에 이미 다룬
        사건, 이번 주기에 다른 소스가 이미 집은 사건, 같은 소스 안의 중복을 후보에서
        빼 같은 발표를 두 번 옮기지 않습니다.</p></li>
      <li><b>번역과 채점</b><p>남은 후보를 한국어로 옮기고 영향도와 감성을 매깁니다.
        원문을 그대로 되돌려준 응답이나 제목만 되풀이한 응답은 표시 전에 걸러냅니다.</p></li>
      <li><b>일자별 집계</b><p>채점된 기사를 시장과 날짜로 묶어 하루치 평균을 냅니다.
        표본이 기준에 못 미치는 시장은 선을 그리지 않고 비워 둡니다.</p></li>
      <li><b>공개</b><p>계산이 끝난 결과만 파일로 구워 두고, 이 사이트는 그 파일을
        그대로 내보냅니다. 방문이 분석을 실행시키지 않습니다.</p></li>
    </ol>
  </div>
</section>

<section>
  <div class='sec-title'><h2>사양</h2><span>spec</span></div>
  <div class='card'>
    <dl class='spec'>
      <dt>대상 시장</dt><dd>중국 본토 · 홍콩 · 미국 · 한국</dd>
      <dt>감성 척도</dt><dd><code>-1.00</code> 부정 … <code>+1.00</code> 긍정. 시세나 수익률이 아닙니다.</dd>
      <dt>시각 기준</dt><dd>모든 날짜와 시각은 <code>JST</code>입니다. 소스 타임존은 수집 단계에서 변환합니다.</dd>
      <dt>갱신</dt><dd>뉴스 주기마다 수집하고, 화면의 수치는 마지막 계산 시점에 고정됩니다. 실시간이 아닙니다.</dd>
      <dt>제공 형식</dt><dd><code>GET /api/market</code> · <code>GET /api/research</code> · <code>GET /api/meta</code> · <code>GET /market_chart.png</code></dd>
      <dt>쓰기</dt><dd>없습니다. 이 사이트는 <code>GET</code>만 가집니다.</dd>
    </dl>
  </div>
</section>

<section>
  <div class='sec-title'><h2>이 사이트가 아닌 것</h2><span>limits</span></div>
  <div class='card'>
    <ul class='checks'>
      <li>투자 조언도 매매 신호도 아닙니다. 보도 논조를 세어 본 관측치입니다.</li>
      <li>실시간 시세를 제공하지 않습니다. 원시 가격 데이터는 다루지 않습니다.</li>
      <li>계정도 회원가입도 없습니다. 방문자별로 저장되는 상태가 없습니다.</li>
      <li>분석을 실행할 수 없습니다. 갱신은 운영자의 텔레그램에서만 일어납니다.</li>
      <li>과거 전체 이력을 보관하지 않습니다. 화면마다 마지막 산출물 한 개만 남습니다.</li>
    </ul>
  </div>
</section>

<section>
  <p class='note'><b>운영.</b> 개인이 혼자 쓰려고 만든 봇의 산출물을 읽기 전용으로
  열어 둔 페이지입니다. 가용성을 약속하지 않으며, 값이 오래되었을 수 있으니
  화면의 기준 시각을 먼저 확인해 주세요.</p>
  <p class='small muted' style='margin-top:14px'>마지막 갱신
  <span class='muted' id='a-meta'>확인 중…</span></p>
</section>
"""

_ABOUT_SCRIPT = (
    "<script>" + _JS_UTIL + """
fetch('/api/meta').then(r=>r.json()).then(d=>{
  const parts=[];
  if(d.market_generated_at)parts.push('시장 '+stamp(d.market_generated_at));
  if(d.research_generated_at)parts.push('리서치 '+stamp(d.research_generated_at));
  document.getElementById('a-meta').textContent=parts.length?parts.join(' · '):'산출물이 아직 없습니다.';
}).catch(()=>{document.getElementById('a-meta').textContent='확인할 수 없습니다.';});
</script>"""
)

ABOUT_HTML = _page(
    "정보",
    "/about",
    _hero(
        "about",
        "뉴스가 무엇을 말했는지<br>세어서 남깁니다",
        "예측을 파는 사이트가 아닙니다. 어떤 시장의 보도가 어느 쪽으로 기울었는지를 "
        "매일 같은 방식으로 집계하고, 그 계산이 어떻게 만들어졌는지 이 페이지에 "
        "적어 둡니다.",
        "<span class='pill'><span class='dot'></span>읽기 전용 · GET only</span>"
        "<span class='pill'>계정 없음</span>"
        "<span class='pill'>JST 기준</span>",
    ),
    _ABOUT_MAIN,
    _ABOUT_SCRIPT,
)
