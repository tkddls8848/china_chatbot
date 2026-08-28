"""공개 웹의 화면. 라우팅(`webpub.py`)과 굽기(`webpub_export.py`)에서 분리한다.

여기에는 정적 문자열만 둔다. 페이지는 프로세스가 뜰 때 한 번 조립되고 요청마다
다시 만들지 않으며, 수치는 브라우저가 `/api/*`를 읽어 채운다. 외부 폰트·CDN을
쓰지 않는 것도 같은 이유다 - 공개 웹은 자기 프로세스 밖에서 아무것도 부르지
않는다. 로고와 아이콘은 파일이 아니라 인라인 SVG다.

색은 종이 바탕에 금색 강조를 얹고 **라이트 전용**으로 고정한다(`color-scheme:light`).
따뜻한 바탕색은 다크로 뒤집으면 같은 인상을 주지 못해, 두 벌을 만드는 대신 한 벌을
끝까지 맞춘다. 감성의 부호는 **빨강이 긍정, 파랑이 부정**이다 - 한국 시장 화면의
관례이고, 이 사이트를 읽는 사람이 다른 화면에서 종일 보는 방향이다.
"""

from __future__ import annotations

SITE_NAME = "nunchi"
SITE_BRAND_KO = "눈치"
SITE_TAGLINE = "뉴스에서 읽는 시장 감성"
SITE_HOST = "nunchi.live"

# ── 아이콘 ──────────────────────────────────────────────────────────────────
# 파일을 두지 않으려고 인라인 SVG로 쓴다. stroke 굵기를 1.6으로 맞춰 본문
# 글자 굵기와 같은 무게로 보이게 한다.

def _icon(path: str, size: int = 18) -> str:
    return (
        "<svg class='ico' width='" + str(size) + "' height='" + str(size) + "'"
        " viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.6'"
        " stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>"
        + path + "</svg>"
    )


_I_DOC = "<path d='M6 3h8l4 4v14H6zM14 3v4h4'/>"
_I_CHART = "<path d='M4 19V5M4 19h16M8 15l3-4 3 2 4-6'/>"
_I_BARS = "<path d='M5 20V10M12 20V4M19 20v-7'/>"
_I_SCALE = "<path d='M4 9h16M4 9l4-4M4 9l4 4M20 15H4M20 15l-4-4M20 15l-4 4'/>"
_I_LAYERS = "<path d='M12 3l9 5-9 5-9-5zM3 13l9 5 9-5'/>"
_I_SHIELD = "<path d='M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z'/>"
_I_SPEC = "<path d='M4 6h16M4 12h16M4 18h9'/>"
_I_PLUG = "<path d='M9 3v6M15 3v6M7 9h10v3a5 5 0 01-10 0zM12 17v4'/>"
_I_EYE = "<path d='M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7zM12 15a3 3 0 100-6 3 3 0 000 6z'/>"


_STYLE = """<style>
:root{
color-scheme:light;

--fs-2xs:12px;--fs-xs:12px;--fs-sm:13px;--fs-md:15px;--fs-lg:19px;--fs-xl:26px;--fs-2xl:32px;
--sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-5:24px;--sp-6:32px;--sp-7:48px;--sp-8:64px;
--w-wide:1200px;--w-text:860px;
--fw-1:400;--fw-2:600;--fw-3:700;--fw-4:800;

--bg:#f1eee6;--ink:#2a2a24;--ink-soft:#45443c;--mut:#57554c;--faint:#6d6b60;
--line:rgba(80,74,56,.15);--line2:rgba(80,74,56,.08);
--fill-1:rgba(150,124,70,.06);--fill-2:rgba(150,124,70,.10);
--surface-1:rgba(251,249,244,.94);--surface-2:rgba(248,245,238,.90);--surface-3:#faf7f0;

--gold:#7f5f20;--gold-deep:#655017;--gold-ink:#fdfaf3;--gold-tint:#7c5d1e;
--gold-a05:rgba(127,95,32,.05);--gold-a10:rgba(127,95,32,.10);
--gold-a25:rgba(127,95,32,.25);--gold-a40:rgba(127,95,32,.40);

--acc:#2b64b8;--acc-tint:#27568f;--acc-a10:rgba(43,100,184,.10);--acc-a40:rgba(43,100,184,.40);

/* 한국 시장 관례: 빨강이 오름·호재, 파랑이 내림·악재 */
--pos:#b8323a;--neg:#2f66c0;--ok:#146b48;--warnc:#8f4511;

--ease:cubic-bezier(.2,0,0,1);--dur-1:100ms;--dur-3:250ms;--dur-4:400ms;
--elev-2:0 4px 12px -4px rgba(90,70,30,.10),0 12px 32px -16px rgba(60,55,40,.14);
--elev-3:0 8px 24px -8px rgba(90,70,30,.13),0 24px 56px -24px rgba(60,55,40,.18);
--r1:8px;--r2:12px;--r3:16px;--r-pill:999px;--ctl:40px;--chip-h:24px;--nav-h:64px;

--font-sans:'Pretendard Variable',Pretendard,'Apple SD Gothic Neo','Malgun Gothic',
  system-ui,-apple-system,sans-serif;
--font-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace}
@media(any-pointer:coarse){:root{--ctl:44px}}
*{box-sizing:border-box}

body::before{content:"";position:fixed;top:0;left:0;right:0;height:2px;z-index:60;pointer-events:none;
background:linear-gradient(90deg,transparent,var(--gold) 22%,#c9a24b 50%,var(--gold) 78%,transparent)}
body{margin:0;background:var(--bg);color:var(--ink);font-size:var(--fs-md);line-height:1.7;
font-family:var(--font-sans);text-rendering:optimizeLegibility;letter-spacing:-.01em}
.ico{display:inline-block;vertical-align:-.18em;flex:none}
::selection{background:var(--gold-a25);color:var(--ink)}
a{color:inherit}
:where(a,button,th,input,[tabindex]):focus-visible{outline:2px solid var(--acc);outline-offset:2px}

/* 배경 - 종이 위에 옅은 색 번짐, 격자, 입자를 겹친다. 단색 배경이면 카드와
   본문이 같은 평면에 붙어 보인다. */
.bg{position:fixed;inset:0;z-index:-3;pointer-events:none;background:
radial-gradient(1100px 720px at 12% -8%,rgba(210,190,140,.22),transparent 58%),
radial-gradient(1000px 680px at 92% -4%,rgba(190,205,235,.20),transparent 55%),
radial-gradient(1200px 900px at 50% 118%,rgba(230,215,180,.20),transparent 60%),
linear-gradient(180deg,#f5f2ea,#f1eee6 40%,#ebe7dc)}
.bg-aurora{position:fixed;inset:0;z-index:-2;opacity:.5;pointer-events:none;background:
radial-gradient(60% 45% at 16% 18%,rgba(240,222,180,.30),transparent 70%),
radial-gradient(50% 40% at 84% 10%,rgba(205,220,245,.22),transparent 70%),
radial-gradient(62% 50% at 68% 84%,rgba(238,226,196,.24),transparent 70%)}
.bg-grid{position:fixed;inset:0;z-index:-2;pointer-events:none;opacity:.16;
background-image:linear-gradient(rgba(150,130,90,.06) 1px,transparent 1px),
linear-gradient(90deg,rgba(150,130,90,.06) 1px,transparent 1px);
background-size:52px 52px;
-webkit-mask:radial-gradient(1200px 700px at 50% 0%,#000,transparent 75%);
mask:radial-gradient(1200px 700px at 50% 0%,#000,transparent 75%)}
.bg-grain{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.04;
background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
background-size:200px}

.wrap{max-width:var(--w-wide);margin:0 auto;padding:0 var(--sp-5)}
.skip{position:absolute;left:-9999px;top:0;z-index:100;background:var(--gold);color:var(--gold-ink);
padding:10px var(--sp-4);border-radius:0 0 8px 0;font-weight:var(--fw-3);text-decoration:none}
.skip:focus{left:0}
main#main:focus{outline:none}

/* 내비 - 종이 위에 떠 있는 알약 */
.topnav{position:sticky;top:10px;z-index:30;background:transparent;margin-top:10px}
.navin{display:flex;align-items:center;gap:20px;height:var(--nav-h);
background:rgba(252,250,244,.82);-webkit-backdrop-filter:blur(14px) saturate(150%);
backdrop-filter:blur(14px) saturate(150%);border:1px solid var(--gold-a25);
border-radius:var(--r-pill);padding-left:22px;padding-right:var(--sp-3);
box-shadow:0 10px 30px -16px rgba(90,70,30,.28),0 2px 8px -4px rgba(90,70,30,.12)}
.brand{display:flex;align-items:center;gap:var(--sp-3);color:var(--ink);text-decoration:none;
font-weight:800;font-size:var(--fs-md);letter-spacing:-.02em}
.brand-t{display:flex;flex-direction:column;line-height:1.12}
.brand-t small{font-size:var(--fs-xs);font-weight:600;color:var(--mut);letter-spacing:.04em;margin-top:1px}
.brand b{background:linear-gradient(100deg,var(--gold-deep),var(--gold) 55%,#a57d2b);
-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent}
@supports not ((-webkit-background-clip:text) or (background-clip:text)){
.brand b{color:var(--gold)!important;-webkit-text-fill-color:currentColor}}
.navmark{flex:none;color:var(--gold);filter:drop-shadow(0 2px 8px rgba(232,192,122,.35))}
.links{display:flex;gap:var(--sp-1);margin-left:auto}
.links a{color:var(--mut);text-decoration:none;padding:var(--sp-2) 14px;border-radius:var(--r-pill);
font-size:var(--fs-sm);font-weight:600;white-space:nowrap;
transition:color var(--dur-1) var(--ease),background-color var(--dur-1) var(--ease)}
.links a[aria-current]{color:var(--gold)}
.links a[aria-current]::after{content:'';display:block;height:2px;margin-top:var(--sp-1);
border-radius:2px;background:linear-gradient(90deg,var(--gold),transparent)}

/* 발행 정보 띠 - 이 사이트가 실시간이 아니라는 사실을 상시로 둔다 */
.asof{margin-top:var(--sp-5);background:var(--fill-1);border-top:1px solid var(--gold-a25);
border-bottom:1px solid var(--gold-a25);color:var(--mut);font-size:var(--fs-sm)}
.asofin{display:flex;align-items:center;gap:var(--sp-3);flex-wrap:wrap;
padding-top:var(--sp-3);padding-bottom:var(--sp-3)}
.mh-id{color:var(--gold-deep);font-weight:var(--fw-4);letter-spacing:.01em}
.mh-date{color:var(--ink);font-weight:var(--fw-2);font-variant-numeric:tabular-nums}
.asof-x{color:var(--mut);font-size:var(--fs-2xs);margin-left:auto}
.pubstat{display:inline-flex;align-items:center;gap:5px;font-size:var(--fs-2xs);font-weight:600;
padding:1px var(--sp-2);border-radius:20px;border:1px solid var(--line2);color:var(--ok)}
.pubstat .pubdot{width:7px;height:7px;border-radius:50%;background:var(--ok);display:inline-block}
.pubstat.none{color:var(--warnc)}.pubstat.none .pubdot{background:var(--warnc)}

/* 본문 */
.page{padding-top:var(--sp-7)}
h1.ph{font-size:var(--fs-xl);font-weight:800;letter-spacing:-.03em;display:flex;
align-items:center;gap:var(--sp-3);margin:0}
.phico{color:var(--gold);display:inline-flex;flex:none}
.disc{background:var(--gold-a05);border:1px solid var(--gold-a25);border-radius:var(--r2);
padding:var(--sp-3) var(--sp-4);color:var(--gold-tint);font-size:var(--fs-sm);line-height:1.7;
margin:var(--sp-4) 0}
.disc b{color:var(--ink)}
.sub2{color:var(--mut);font-size:var(--fs-sm);margin:var(--sp-3) 0 var(--sp-4)}
.sub2 b{color:var(--ink)}

.pgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:var(--sp-3);
margin:var(--sp-4) 0 var(--sp-2)}
.pcard{position:relative;background:var(--surface-2);border:1px solid var(--line);
border-radius:var(--r3);padding:var(--sp-4);box-shadow:var(--elev-2);overflow:hidden;
transition:transform var(--dur-3) var(--ease),border-color var(--dur-1) var(--ease)}
.pcard::after{content:'';position:absolute;left:0;right:0;top:0;height:2px;opacity:.8}
.pc-gold::after{background:linear-gradient(90deg,var(--gold),transparent)}
.pc-acc::after{background:linear-gradient(90deg,var(--acc),transparent)}
.pc-ok::after{background:linear-gradient(90deg,var(--ok),transparent)}
.pc-warn::after{background:linear-gradient(90deg,var(--warnc),transparent)}
.pcard-t{font-weight:800;color:var(--gold-tint);font-size:var(--fs-md);margin-bottom:6px;
letter-spacing:-.01em}
.pcard-s{color:var(--mut);font-size:var(--fs-sm);line-height:1.7}

.histbox{margin-top:40px}
.histh{display:flex;align-items:center;gap:var(--sp-2);font-weight:800;font-size:var(--fs-md);
margin-bottom:var(--sp-3);letter-spacing:-.02em}
.histh .phico{color:var(--gold)}
.docbody{color:var(--ink-soft);font-size:var(--fs-sm);line-height:1.9;max-width:var(--w-text)}
.docbody p{margin:6px 0}.docbody b{color:var(--ink)}
.docbody ul,.docbody ol{margin:6px 0;padding-left:22px}
.docbody li{margin:var(--sp-1) 0}
.docbody code{font-family:var(--font-mono);font-size:var(--fs-xs);color:var(--gold-deep);
background:var(--fill-2);border:1px solid var(--line);border-radius:5px;padding:1px 6px}

/* 단계 */
.steps{list-style:none;counter-reset:s;margin:var(--sp-2) 0 0;padding:0;max-width:var(--w-text)}
.steps li{counter-increment:s;position:relative;padding:0 0 var(--sp-4) 44px;margin:0}
.steps li::before{content:counter(s,decimal-leading-zero);position:absolute;left:0;top:2px;
width:28px;height:28px;display:grid;place-items:center;border-radius:var(--r1);
background:var(--gold-a10);color:var(--gold-deep);font-family:var(--font-mono);
font-size:var(--fs-2xs);font-weight:700}
.steps li::after{content:"";position:absolute;left:13px;top:34px;bottom:4px;width:1px;background:var(--line)}
.steps li:last-child{padding-bottom:0}.steps li:last-child::after{display:none}
.steps b{display:block;color:var(--ink);font-weight:800;letter-spacing:-.015em}
.steps p{margin:2px 0 0;color:var(--ink-soft)}

/* 사양 */
.spec{margin:var(--sp-2) 0 0;display:grid;grid-template-columns:minmax(112px,190px) 1fr;
max-width:var(--w-text)}
.spec dt{padding:11px 0;border-top:1px solid var(--line2);color:var(--mut);font-size:var(--fs-sm);
font-weight:var(--fw-2)}
.spec dd{padding:11px 0;border-top:1px solid var(--line2);margin:0;color:var(--ink-soft);
font-size:var(--fs-sm);line-height:1.8}
.spec dt:first-of-type,.spec dd:first-of-type{border-top:0}

/* 지표 */
.statstrip{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
gap:1px;background:var(--line);border:1px solid var(--line);border-radius:var(--r3);
overflow:hidden;box-shadow:var(--elev-2);margin:var(--sp-4) 0}
.st{background:var(--surface-1);padding:16px 18px}
.st .l{color:var(--mut);font-size:var(--fs-2xs);font-weight:var(--fw-2);letter-spacing:.06em;
margin-bottom:5px}
.st .v{font-size:var(--fs-2xl);font-weight:800;letter-spacing:-.03em;color:var(--ink);
font-variant-numeric:tabular-nums;line-height:1.15}
.st .v.ts{font-size:var(--fs-lg)}
.st .v.text{font-size:var(--fs-lg);letter-spacing:-.02em;overflow-wrap:anywhere}
.st .v small{display:block;margin-top:2px;font-size:var(--fs-xs);font-weight:600;color:var(--mut)}

/* 표 */
.tablewrap{background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r3);
overflow-x:auto;box-shadow:var(--elev-3);max-width:760px}
table{width:100%;border-collapse:collapse;font-size:var(--fs-sm);min-width:520px}
thead th{background:var(--surface-3);color:var(--mut);font-weight:600;text-align:left;
padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--line);white-space:nowrap;
font-size:var(--fs-xs);letter-spacing:.06em}
thead th.r{text-align:right}
tbody td{padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--line2);white-space:nowrap;
color:var(--ink-soft)}
tbody tr:last-child td{border-bottom:0}
tbody td.r{text-align:right;font-variant-numeric:tabular-nums}
th.r,td.r{width:104px}
thead th:nth-child(2),tbody td:nth-child(2){width:150px}
.nm{font-weight:700;color:var(--ink)}
.cd{color:var(--faint);font-size:var(--fs-2xs);font-family:var(--font-mono);margin-top:1px}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.bar{position:relative;width:118px;height:7px;border-radius:4px;background:var(--fill-2)}
.bar::before{content:"";position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--gold-a25)}
.bar i{position:absolute;top:0;height:7px;border-radius:4px}

/* 차트 */
.chartcard{background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r3);
padding:var(--sp-3);box-shadow:var(--elev-2);overflow:hidden}
.chartcard img{display:block;width:100%;height:auto;border-radius:10px}
.empty{padding:34px var(--sp-5);text-align:center;color:var(--mut);font-size:var(--fs-sm)}

/* 리서치 */
.tag{display:inline-flex;align-items:center;height:var(--chip-h);padding:0 var(--sp-2);
border-radius:var(--r1);font-size:var(--fs-2xs);font-weight:800;letter-spacing:.04em}
.tag-add{background:rgba(184,50,58,.10);color:var(--pos)}
.tag-watch{background:var(--gold-a10);color:var(--gold-tint)}
.tag-remove{background:rgba(47,102,192,.10);color:var(--neg)}
.rc{position:relative;background:var(--surface-2);border:1px solid var(--line);
border-radius:var(--r3);padding:var(--sp-4);box-shadow:var(--elev-2);overflow:hidden}
.rc+.rc{margin-top:var(--sp-2)}
.rc::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
background:linear-gradient(180deg,var(--gold),transparent)}
.rt{display:flex;gap:var(--sp-2);align-items:center;flex-wrap:wrap}
.rt b{font-size:var(--fs-md);color:var(--ink);letter-spacing:-.015em}
.rt code{font-family:var(--font-mono);font-size:var(--fs-xs);color:var(--faint)}
.sc{margin-left:auto;display:flex;gap:var(--sp-3);color:var(--mut);font-size:var(--fs-xs);
font-variant-numeric:tabular-nums;white-space:nowrap}
.rz{color:var(--ink-soft);font-size:var(--fs-sm);margin:var(--sp-2) 0 0;line-height:1.7}
.body-text{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;color:var(--ink-soft);
font-size:var(--fs-sm);line-height:1.9}
.brief{background:var(--surface-1);border:1px solid var(--line);border-left:2px solid var(--gold);
border-radius:var(--r3);padding:var(--sp-5);box-shadow:var(--elev-2)}
.checks{margin:0;padding:0;list-style:none}
.checks li{position:relative;padding:0 0 10px 20px;color:var(--ink-soft);font-size:var(--fs-sm);
line-height:1.8}
.checks li:last-child{padding-bottom:0}
.checks li::before{content:"—";position:absolute;left:0;color:var(--gold);font-family:var(--font-mono)}

/* 꼬리말 */
.foot{color:var(--faint);font-size:var(--fs-xs);text-align:center;padding:var(--sp-6) 0 var(--sp-7);
line-height:2}
.asof-note{max-width:var(--w-wide);margin:0 auto;padding:0 var(--sp-5) 30px;color:var(--faint);
font-size:var(--fs-2xs);text-align:center}
.sitefoot{border-top:1px solid var(--line);padding:20px 0 36px}
.sf-mast{display:grid;gap:var(--sp-3);padding-bottom:var(--sp-4);margin-bottom:14px;
border-bottom:1px solid var(--line2)}
.sf-brand{color:var(--mut);font-weight:var(--fw-3);font-size:var(--fs-xs)}
.sf-cred{display:grid;grid-template-columns:max-content 1fr;gap:6px var(--sp-4);margin:0;
color:var(--faint);font-size:var(--fs-2xs);line-height:1.55}
.sf-cred dt{color:var(--mut);font-weight:var(--fw-2);white-space:nowrap}
.sf-cred dd{margin:0}
.sf-cred code{font-family:var(--font-mono);color:var(--mut)}
.sfin{display:flex;flex-wrap:wrap;gap:var(--sp-2) var(--sp-5);align-items:center;
justify-content:space-between;color:var(--faint);font-size:var(--fs-xs)}
.sf-links{display:flex;flex-wrap:wrap;gap:var(--sp-1) 18px}
.sf-links a{color:var(--mut);text-decoration:none;transition:color var(--dur-1) var(--ease)}

@media(hover:hover) and (pointer:fine){
.links a:hover{color:var(--ink);background:var(--fill-1)}
.pcard:hover,.rc:hover{transform:translateY(-2px);border-color:var(--gold-a25)}
.sf-links a:hover{color:var(--gold)}}

@media(max-width:760px){
.wrap{padding:0 var(--sp-4)}
.navin{gap:var(--sp-2);padding-left:var(--sp-4)}
.brand-t small{display:none}
.links a{padding:var(--sp-2) 10px}
.page{padding-top:var(--sp-6)}
.histbox{margin-top:var(--sp-6)}
.asof-x{margin-left:0;flex-basis:100%}
tbody td,thead th{padding:var(--sp-3)}}
@media(max-width:520px){
.spec{grid-template-columns:1fr}
.spec dd{padding-top:0;border-top:0}
.sf-cred{grid-template-columns:1fr;gap:0}
.sf-cred dt{margin-top:10px}
.sc{margin-left:0;flex-basis:100%}
.st .v{font-size:var(--fs-xl)}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style>"""


# ── 뼈대 ────────────────────────────────────────────────────────────────────

_NAV_LINKS = (("/", "시장"), ("/research", "리서치"), ("/about", "정보"))

_MARK = (
    "<svg class='navmark' width='34' height='34' viewBox='0 0 34 34' fill='none'"
    " aria-hidden='true'>"
    "<rect x='1.6' y='1.6' width='30.8' height='30.8' rx='9.5'"
    " fill='currentColor' fill-opacity='.09' stroke='currentColor' stroke-opacity='.4'/>"
    "<path d='M8 22.5l5-6 4 3 4.5-7.5' stroke='currentColor' stroke-width='2'"
    " stroke-linecap='round' stroke-linejoin='round'/>"
    "<circle cx='24.4' cy='11.2' r='2.5' fill='currentColor'/></svg>"
)


def _head(title: str) -> str:
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='light'>"
        "<meta name='robots' content='noindex'>"
        "<title>" + title + " · " + SITE_BRAND_KO + "</title>" + _STYLE + "</head><body>"
        "<a class='skip' href='#main'>본문 바로가기</a>"
        "<div class='bg'></div><div class='bg-aurora'></div>"
        "<div class='bg-grid'></div><div class='bg-grain'></div>"
    )


def _header(active: str) -> str:
    nav = "".join(
        "<a href='" + href + "'" + (" aria-current='page'" if href == active else "") + ">"
        + label + "</a>"
        for href, label in _NAV_LINKS
    )
    return (
        "<nav class='topnav'><div class='wrap navin'>"
        "<a class='brand' href='/'>" + _MARK
        + "<span class='brand-t'><span>" + SITE_BRAND_KO + "<b>.live</b></span>"
        "<small>" + SITE_TAGLINE + "</small></span></a>"
        "<div class='links'>" + nav + "</div>"
        "</div></nav>"
    )


# 발행 정보 띠. 이 사이트에서 가장 자주 틀리는 오해가 "지금 값"이라는 것이라,
# 기준 시각과 "실시간 아님"을 화면마다 같은 자리에 둔다.
_ASOF = (
    "<div class='asof' role='note'><div class='wrap asofin'>"
    "<span class='mh-id'>" + SITE_BRAND_KO + " · 뉴스 주기마다 갱신</span>"
    "<span class='mh-date' id='asof-date'>산출물 시각을 확인하는 중…</span>"
    "<span class='pubstat' id='asof-stat' hidden><i class='pubdot'></i><span id='asof-stat-t'></span></span>"
    "<span class='asof-x'>실시간이 아니라 마지막으로 계산된 산출물입니다</span>"
    "</div></div>"
)

_FOOT_NOTE = (
    "<div class='asof-note'>이 페이지의 모든 수치는 실시간이 아니라 마지막 산출물의 "
    "스냅숏입니다. 인용하기 전에 화면 위쪽의 기준 시각을 확인해 주세요.</div>"
)

_SITE_FOOT = (
    "<footer class='sitefoot'><div class='wrap'>"
    "<div class='sf-mast'>"
    "<span class='sf-brand'>" + SITE_BRAND_KO + " · " + SITE_HOST + "</span>"
    "<dl class='sf-cred'>"
    "<dt>다루는 시장</dt><dd>중국 본토 · 홍콩 · 미국 · 한국</dd>"
    "<dt>값의 성격</dt><dd>뉴스 보도의 논조를 집계한 관측치입니다. 시세·수익률·"
    "매매 신호가 아니며, 원시 가격 데이터는 제공하지 않습니다.</dd>"
    "<dt>시각 기준</dt><dd>모든 날짜와 시각은 <code>JST</code>입니다. 소스 타임존은 "
    "수집 단계에서 변환합니다.</dd>"
    "<dt>갱신</dt><dd>뉴스 주기마다 갱신하며, 화면의 값은 마지막 계산 시점에 고정됩니다.</dd>"
    "<dt>제공 형식</dt><dd><code>GET /api/market</code> · <code>GET /api/research</code> · "
    "<code>GET /api/meta</code> · <code>GET /market_chart.png</code> — 쓰기 API는 없습니다.</dd>"
    "</dl></div>"
    "<div class='sfin'><span class='sf-links'>"
    "<a href='/'>시장</a><a href='/research'>리서치</a><a href='/about'>정보</a>"
    "</span><span>정보 제공 목적이며 투자 권유가 아닙니다.</span></div>"
    "</div></footer></body></html>"
)


def _page(title: str, active: str, main: str, script: str = "") -> str:
    return (
        _head(title)
        + _header(active)
        + _ASOF
        + "<main id='main' tabindex='-1' class='wrap page'>" + main + "</main>"
        + _FOOT_NOTE
        + script
        + _SITE_FOOT
    )


def _h1(icon: str, text: str) -> str:
    return "<h1 class='ph'><span class='phico'>" + _icon(icon, 24) + "</span>" + text + "</h1>"


def _sec(icon: str, title: str, body: str) -> str:
    return (
        "<div class='histbox'><div class='histh'><span class='phico'>" + _icon(icon)
        + "</span>" + title + "</div><div class='docbody'>" + body + "</div></div>"
    )


_DISCLAIMER = (
    "<div class='foot'>정보 제공 목적이며 투자 권유가 아닙니다. 값은 갱신 시점 기준 "
    "스냅숏이며, 투자 판단과 책임은 이용자 본인에게 있습니다.</div>"
)


# ── 공통 스크립트 ────────────────────────────────────────────────────────────
# 값은 산출물에서 오지만 문자열은 모두 텍스트 노드로 넣거나 escape한 뒤 붙인다.
_JS_UTIL = """
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>(
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stamp=v=>{if(!v)return '';const t=String(v).replace('T',' ');
  return t.length>16?t.slice(0,16):t;};
// 지표 칸은 폭이 좁다. 날짜와 시각을 한 줄에 두면 줄바꿈으로 칸 높이가 튄다.
const stampHtml=v=>{const t=stamp(v);if(!t)return '–';const i=t.indexOf(' ');
  return i<0?esc(t):esc(t.slice(0,i))+'<small>'+esc(t.slice(i+1))+'</small>';};
const pct=v=>Math.round((Number(v)||0)*100)+'%';
// 발행 정보 띠는 화면마다 같으므로 한 곳에서 채운다.
fetch('/api/meta').then(r=>r.json()).then(d=>{
  const parts=[];
  if(d.market_generated_at)parts.push('시장 집계 '+stamp(d.market_generated_at));
  if(d.research_generated_at)parts.push('리서치 '+stamp(d.research_generated_at));
  const date=document.getElementById('asof-date');
  const stat=document.getElementById('asof-stat');
  const statT=document.getElementById('asof-stat-t');
  if(parts.length){
    date.textContent=parts.join(' · ')+' JST';
    statT.textContent='산출물 있음';
  }else{
    date.textContent='아직 산출물이 없습니다';
    stat.className='pubstat none';
    statT.textContent='대기 중';
  }
  stat.hidden=false;
}).catch(()=>{
  document.getElementById('asof-date').textContent='산출물 시각을 읽지 못했습니다';
});
"""


# ── 시장 ────────────────────────────────────────────────────────────────────

_MARKET_MAIN = (
    _h1(_I_CHART, "시장 컨센서스")
    + "<div class='disc'>중국·홍콩·미국·한국 뉴스를 시장별로 묶어 하루치 요약을 만들고, "
    "그 요약에 매긴 <b>−1 ~ +1</b> 감성 점수의 추이를 그립니다. 아래 값은 마지막으로 "
    "계산된 산출물이며, 페이지를 열 때 다시 계산하지 않습니다.</div>"
    + "<div class='sub2'>감성은 보도 논조의 방향이지 시세나 수익률이 아닙니다. "
    "<b>빨강이 긍정, 파랑이 부정</b>입니다.</div>"
    + """
<div class='statstrip'>
  <div class='st'><div class='l'>기준 시각</div><div class='v ts' id='s-time'>–</div></div>
  <div class='st'><div class='l'>조회 기간</div><div class='v' id='s-days'>–</div></div>
  <div class='st'><div class='l'>관측 시장</div><div class='v' id='s-markets'>–</div></div>
  <div class='st'><div class='l'>집계 기사</div><div class='v' id='s-count'>–</div></div>
</div>

<div class='histbox'>
  <div class='histh'><span class='phico'>"""
    + _icon(_I_CHART)
    + """</span>감성 추이</div>
  <div class='chartcard' id='chart'>
    <img src='/market_chart.png' alt='국가별 시장 감성 추이 차트'
      onerror="this.parentNode.innerHTML=&quot;<p class='empty'>차트가 아직 생성되지 않았습니다.</p>&quot;">
  </div>
</div>

<div class='histbox'>
  <div class='histh'><span class='phico'>"""
    + _icon(_I_BARS)
    + """</span>국가별 수치</div>
  <div class='tablewrap'>
    <table>
      <thead><tr><th>시장</th><th>분포</th><th class='r'>감성</th><th class='r'>기사</th><th class='r'>관측일</th></tr></thead>
      <tbody id='rows'><tr><td colspan='5' class='empty'>산출물을 불러오는 중…</td></tr></tbody>
    </table>
  </div>
</div>
"""
    + _DISCLAIMER
)

_MARKET_SCRIPT = (
    "<script>" + _JS_UTIL + """
const LABELS={CN:'중국 본토',HK:'홍콩',US:'미국',KR:'한국',JP:'일본',EU:'유럽',OTHER:'기타'};
function bar(v){const w=Math.min(Math.abs(v),1)*50;const side=v>=0?'left:50%':'right:50%';
  const color=v>=0?'var(--pos)':'var(--neg)';
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
    return "<tr><td><div class='nm'>"+esc(LABELS[code]||code)+"</div><div class='cd'>"+esc(code)+"</div></td>"
      +"<td>"+bar(s)+"</td>"
      +"<td class='r "+(s>=0?'pos':'neg')+"'>"+(s>=0?'+':'')+s.toFixed(2)+"</td>"
      +"<td class='r'>"+(v.count||0)+"</td>"
      +"<td class='r'>"+days+"</td></tr>";
  }).join('');
}).catch(()=>{
  document.getElementById('rows').innerHTML="<tr><td colspan='5' class='empty'>산출물을 읽지 못했습니다.</td></tr>";
});
</script>"""
)

INDEX_HTML = _page("시장 컨센서스", "/", _MARKET_MAIN, _MARKET_SCRIPT)


# ── 리서치 ──────────────────────────────────────────────────────────────────

_RESEARCH_MAIN = (
    _h1(_I_LAYERS, "리서치")
    + "<div class='disc'>관심 주제를 놓고 후보 종목의 <b>추가·주목·제외</b>와 리스크, "
    "그리고 그 주제를 약화시키는 반론을 정리합니다. 아래는 마지막으로 저장된 분석 "
    "한 건입니다.</div>"
    + "<div class='sub2'>리서치 실행은 텔레그램에만 있습니다. 이 페이지는 결과를 "
    "<b>보여 주기만</b> 하며 분석을 시작시키지 않습니다.</div>"
    + """
<div class='statstrip'>
  <div class='st'><div class='l'>관심 주제</div><div class='v text' id='r-sight'>–</div></div>
  <div class='st'><div class='l'>기준 시각</div><div class='v ts' id='r-time'>–</div></div>
  <div class='st'><div class='l'>분석 뉴스</div><div class='v' id='r-news'>–</div></div>
  <div class='st'><div class='l'>후보 종목</div><div class='v' id='r-cand'>–</div></div>
</div>

<div class='histbox'>
  <div class='histh'><span class='phico'>"""
    + _icon(_I_DOC)
    + """</span>요약</div>
  <div class='brief'><p class='body-text' id='r-summary'>산출물을 불러오는 중…</p></div>
</div>

<div class='histbox' id='sec-actions' hidden>
  <div class='histh'><span class='phico'>"""
    + _icon(_I_LAYERS)
    + """</span>종목 판단</div>
  <div id='r-actions'></div>
</div>

<div class='histbox' id='sec-risks' hidden>
  <div class='histh'><span class='phico'>"""
    + _icon(_I_SHIELD)
    + """</span>리스크</div>
  <div class='brief'><ul class='checks' id='r-risks'></ul></div>
</div>

<div class='histbox' id='sec-critique' hidden>
  <div class='histh'><span class='phico'>"""
    + _icon(_I_SCALE)
    + """</span>내 뷰 반론</div>
  <div id='r-critique'></div>
</div>

<div class='histbox'><div class='docbody'>
  <p>종목 판단은 관심종목을 정리하기 위한 메모이며 매매 권유가 아닙니다.
  관련도와 판단 수치는 모델이 매긴 값이라 사실 확인을 대신하지 않습니다.</p>
</div></div>
"""
    + _DISCLAIMER
)

_RESEARCH_SCRIPT = (
    "<script>" + _JS_UTIL + """
const TAGS={add:['tag-add','추가'],watch:['tag-watch','주목'],remove:['tag-remove','제외']};
const ORDER={add:0,watch:1,remove:2};
function actionCard(a){
  const t=TAGS[a.action];
  const scores=[];
  if(a.relevance!=null)scores.push('관련도 '+pct(a.relevance));
  if(a.confidence!=null)scores.push('판단 '+pct(a.confidence));
  return "<div class='rc'><div class='rt'>"
    +"<span class='tag "+t[0]+"'>"+esc(t[1])+"</span>"
    +"<b>"+esc(a.name||a.ticker||'')+"</b>"
    +"<code>"+esc(a.ticker||'')+"</code>"
    +(scores.length?"<span class='sc'>"+scores.map(s=>"<span>"+esc(s)+"</span>").join('')+"</span>":"")
    +"</div>"+(a.reason?"<p class='rz'>"+esc(a.reason)+"</p>":"")+"</div>";
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
    document.getElementById('r-actions').innerHTML=actions.map(actionCard).join('');
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
      "<div class='rc'><div class='rt'><b>"+esc(c.point)+"</b>"
      +(c.severity!=null?"<span class='sc'><span>강도 "+pct(c.severity)+"</span></span>":"")
      +"</div></div>").join('');
    document.getElementById('sec-critique').hidden=false;
  }
}).catch(()=>{
  document.getElementById('r-summary').textContent='산출물을 읽지 못했습니다.';
});
</script>"""
)

RESEARCH_HTML = _page("리서치", "/research", _RESEARCH_MAIN, _RESEARCH_SCRIPT)


# ── 정보 ────────────────────────────────────────────────────────────────────

_ABOUT_MAIN = (
    _h1(_I_DOC, SITE_BRAND_KO + "는 어떤 사이트인가요?")
    + "<div class='disc'>정해진 주기마다 기계가 중국·홍콩·미국·한국 뉴스를 읽어 "
    "시장별 하루치 요약과 <b>−1 ~ +1</b> 감성 점수를 만들고, 관심 주제에 대한 리서치 "
    "결과를 남기는 <b>자동 관측 기록</b>입니다. 정보 제공 목적이며 투자 권유가 "
    "아닙니다.</div>"
    + "<div class='sub2'>개인이 쓰려고 만든 봇의 산출물을 읽기 전용으로 열어 둔 "
    "페이지입니다. 화면의 수치는 <b>마지막 계산 시점</b>에 고정되며 실시간이 아닙니다.</div>"
    + "<div class='pgrid'>"
    "<div class='pcard pc-gold'><div class='pcard-t'>광고 없음 · 가입 없음</div>"
    "<div class='pcard-s'>배너·팝업·회원가입·유료 구간이 없습니다. 방문자별로 "
    "저장되는 상태도 없습니다.</div></div>"
    "<div class='pcard pc-acc'><div class='pcard-t'>주기마다 자동 갱신</div>"
    "<div class='pcard-s'>수집부터 공개까지 사람 손이 들어가지 않습니다. 봇이 계산을 "
    "끝낼 때마다 산출물을 파일로 구워 두고, 이 사이트는 그 파일을 내보냅니다.</div></div>"
    "<div class='pcard pc-ok'><div class='pcard-t'>집계만 공개</div>"
    "<div class='pcard-s'>개별 기사가 아니라 하루·시장 단위의 집계를 공개합니다. "
    "원시 가격 데이터는 다루지 않습니다.</div></div>"
    "</div>"
    + _sec(
        _I_DOC,
        "무엇을 보여 주나요",
        "<ul>"
        "<li><b>시장 컨센서스</b> — 중국 본토·홍콩·미국·한국의 하루치 감성 평균과 "
        "그 추이. 표본이 기준에 못 미치는 시장은 선을 그리지 않고 비워 둡니다.</li>"
        "<li><b>리서치</b> — 관심 주제에 대한 요약, 후보 종목의 추가·주목·제외, "
        "리스크, 그리고 그 주제를 약화시키는 반론. 마지막 결과 한 건만 보관합니다.</li>"
        "<li>같은 값을 <code>/api/market</code>·<code>/api/research</code>·"
        "<code>/api/meta</code>에서 JSON으로도 읽을 수 있습니다.</li>"
        "</ul>",
    )
    + _sec(
        _I_LAYERS,
        "어떻게 만들어지나요",
        "<ol class='steps'>"
        "<li><b>수집</b><p>정해진 주기마다 시장별 뉴스 소스를 읽습니다. 소스 한 곳이 "
        "실패해도 나머지 주기는 그대로 진행합니다.</p></li>"
        "<li><b>사전선별</b><p>번역 전에 원문을 사건 단위로 묶습니다. 최근에 이미 다룬 "
        "사건, 이번 주기에 다른 소스가 이미 집은 사건, 같은 소스 안의 중복을 후보에서 "
        "빼 같은 발표를 두 번 옮기지 않습니다.</p></li>"
        "<li><b>번역과 채점</b><p>남은 후보를 한국어로 옮기고 영향도와 감성을 매깁니다. "
        "원문을 그대로 되돌려준 응답이나 제목만 되풀이한 응답은 표시 전에 걸러냅니다.</p></li>"
        "<li><b>일자별 집계</b><p>채점된 기사를 시장과 날짜로 묶어 하루치 평균을 냅니다. "
        "표본이 기준에 못 미치는 시장은 비워 둡니다.</p></li>"
        "<li><b>공개</b><p>계산이 끝난 결과만 파일로 구워 두고, 이 사이트는 그 파일을 "
        "그대로 내보냅니다. 방문이 분석을 실행시키지 않습니다.</p></li>"
        "</ol>",
    )
    + _sec(
        _I_SPEC,
        "사양",
        "<dl class='spec'>"
        "<dt>대상 시장</dt><dd>중국 본토 · 홍콩 · 미국 · 한국</dd>"
        "<dt>감성 척도</dt><dd><code>-1.00</code> 부정 ~ <code>+1.00</code> 긍정. "
        "화면에서는 <b>빨강이 긍정, 파랑이 부정</b>입니다.</dd>"
        "<dt>시각 기준</dt><dd>모든 날짜와 시각은 <code>JST</code>입니다. 소스 타임존은 "
        "수집 단계에서 변환합니다.</dd>"
        "<dt>갱신</dt><dd>뉴스 주기마다 수집하고, 화면의 수치는 마지막 계산 시점에 "
        "고정됩니다.</dd>"
        "<dt>제공 형식</dt><dd><code>GET /api/market</code> · "
        "<code>GET /api/research</code> · <code>GET /api/meta</code> · "
        "<code>GET /market_chart.png</code></dd>"
        "<dt>쓰기</dt><dd>없습니다. 이 사이트는 <code>GET</code>만 가집니다.</dd>"
        "</dl>",
    )
    + _sec(
        _I_SHIELD,
        "무엇을 하지 않나요",
        "<ul>"
        "<li>특정 종목의 매매 권유·상담을 하지 않습니다. '추가·주목' 표시는 관심종목 "
        "정리를 돕는 메모이며 투자 추천이나 등급이 아닙니다.</li>"
        "<li>실시간 시세를 제공하지 않습니다. 원시 가격 데이터는 다루지 않습니다.</li>"
        "<li>회원가입이 없습니다 — 계정 절차 자체가 없습니다.</li>"
        "<li>웹에서 분석을 실행할 수 없습니다. 갱신은 운영자의 텔레그램에서만 "
        "일어납니다.</li>"
        "<li>과거 전체 이력을 보관하지 않습니다. 화면마다 마지막 산출물 한 개만 "
        "남습니다.</li>"
        "</ul>",
    )
    + _sec(
        _I_PLUG,
        "운영과 가용성",
        "<p>개인이 혼자 운영합니다. 가용성을 약속하지 않으며, 봇이 멈춘 동안에는 "
        "직전 산출물이 그대로 남아 있습니다. 값이 오래되었을 수 있으니 화면 위쪽의 "
        "<b>기준 시각</b>을 먼저 확인해 주세요.</p>",
    )
    + _DISCLAIMER
)

_ABOUT_SCRIPT = "<script>" + _JS_UTIL + "</script>"

ABOUT_HTML = _page("정보", "/about", _ABOUT_MAIN, _ABOUT_SCRIPT)
