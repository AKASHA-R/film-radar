"""把一期数据渲染成静态 HTML，并生成 Issue 的标题与正文。纯函数，不碰网络。"""
from __future__ import annotations

import html
from datetime import date, datetime
from pathlib import Path

CATEGORY_LABELS = {
    "scifi": "科幻",
    "thriller": "惊悚",
    "political_historical": "政治历史",
    "chinese": "中国电影",
    "horror": "恐怖",
    "japanese": "日本电影",
    "crime": "犯罪",
    "outside": "口味之外",
}
EVIDENCE_NOTES = {
    "thin": "目前评论很少，下面的判断依据有限。",
    "none": "没有通过校验的来源，下面的内容未经查证。",
}
ISSUE_TITLE_LIMIT = 200

HUES = {"scifi": 217, "thriller": 268, "political_historical": 160, "chinese": 40,
        "horror": 350, "japanese": 322, "crime": 190}

_STYLE_BASE = """
:root{color-scheme:light dark;--bg:#f2f1ee;--surface:#fff;--soft:#f7f6f3;--ink:#16161a;--mute:#5d5e66;--line:#e3e1dc;
--warn-bg:#fff1e6;--warn:#9a3412;--link:#1d4f8f;--accent:#b4232c;--cat-s:62%;--cat-l:38%;--catbg-l:95%;
--shadow:0 1px 2px rgba(20,20,30,.06),0 10px 28px -14px rgba(20,20,30,.22);
--serif:"Iowan Old Style","Palatino Linotype",Palatino,"Songti SC","Noto Serif SC",Georgia,serif}
@media (prefers-color-scheme: dark){:root{--bg:#0e0f11;--surface:#17181c;--soft:#1f2025;--ink:#ececf1;--mute:#a3a4ae;--line:#2c2d34;
--warn-bg:#3b2214;--warn:#fdba74;--link:#8ab4f8;--accent:#f0707a;--cat-s:75%;--cat-l:72%;--catbg-l:20%;
--shadow:0 1px 2px rgba(0,0,0,.5),0 10px 28px -14px rgba(0,0,0,.75)}}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion: reduce){html{scroll-behavior:auto}*{transition:none!important}}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Noto Sans SC","Microsoft YaHei","Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--link)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
main{max-width:1080px;margin:0 auto;padding:0 20px 72px}
[data-cat]{--h:220;--cat:hsl(var(--h) var(--cat-s) var(--cat-l));--cat-bg:hsl(var(--h) 45% var(--catbg-l))}
[data-cat="outside"]{--cat:var(--mute);--cat-bg:var(--soft)}
.hero{background:radial-gradient(900px 320px at 88% -20%,rgba(180,35,44,.38),transparent 62%),#0f1013;color:#f3f3f6}
.hero::before,.hero::after{content:"";display:block;height:8px;margin:12px 0;background:repeating-linear-gradient(90deg,rgba(255,255,255,.15) 0 12px,transparent 12px 22px)}
.hero-in{max-width:1080px;margin:0 auto;padding:10px 20px 14px}
.kicker{margin:0;font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:rgba(255,255,255,.6)}
.hero h1{font:700 clamp(30px,6vw,52px)/1.1 var(--serif);margin:10px 0 12px;letter-spacing:.01em}
.meta{display:flex;flex-wrap:wrap;gap:4px 18px;list-style:none;margin:0;padding:0;font-size:13px;color:rgba(255,255,255,.72)}
.stats{display:flex;flex-wrap:wrap;gap:10px;list-style:none;margin:20px 0 0;padding:0}
.stats li{padding:10px 18px;border-radius:14px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);font-size:14px;color:rgba(255,255,255,.8)}
.stats b{display:block;font:700 30px/1.1 var(--serif);color:#fff}
.stats li.bad{border-color:#f0707a}
.stale{margin:16px 0 0;padding:10px 14px;border-radius:10px;background:var(--warn-bg);color:var(--warn);font-size:14px}
.jump{position:sticky;top:0;z-index:10;background:var(--bg);background:color-mix(in srgb,var(--bg) 86%,transparent);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.jump .wrap{max-width:1080px;margin:0 auto;padding:8px 20px;display:flex;gap:8px;overflow-x:auto}
.jump a{white-space:nowrap;text-decoration:none;color:var(--ink);font-size:14px;padding:6px 14px;border-radius:999px;border:1px solid var(--line);background:var(--surface);transition:border-color .15s}
.jump a:hover{border-color:var(--accent)}
.jump span{color:var(--mute);margin-left:6px}
h2{display:flex;align-items:center;gap:10px;font-size:22px;margin:48px 0 16px;font-weight:700;scroll-margin-top:64px}
h2 .count{font-size:13px;font-weight:600;color:var(--mute);background:var(--soft);border:1px solid var(--line);padding:1px 10px;border-radius:999px}
.empty{color:var(--mute)}
.glance{list-style:none;margin:0;padding:0;background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);overflow:hidden}
.glance li+li{border-top:1px solid var(--line)}
.glance a{display:grid;grid-template-columns:10px minmax(0,1fr) auto;align-items:center;gap:4px 14px;padding:12px 18px;color:inherit;text-decoration:none;transition:background .15s}
.glance a:hover{background:var(--soft)}
.g-dot{width:10px;height:10px;border-radius:50%;background:var(--cat)}
.g-title{font-weight:600;overflow-wrap:anywhere}
.g-title small{margin-left:8px;font-size:13px;font-weight:400;color:var(--mute)}
.g-meta{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;justify-content:flex-end;font-size:13px;color:var(--mute)}
.g-cat{color:var(--cat);font-weight:600}
.g-tier{font-size:12px;font-weight:700;color:var(--accent);border:1px solid var(--accent);border-radius:999px;padding:0 8px}
.g-hot{font-size:12px;font-weight:600;color:var(--warn);background:var(--warn-bg);border-radius:999px;padding:0 8px}
.meter{display:inline-flex;gap:3px;align-items:center}
.meter i{width:14px;height:5px;border-radius:3px;background:var(--line)}
.meter i.on{background:var(--cat)}
.film{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);overflow:hidden;margin:0 0 20px;scroll-margin-top:64px}
.film::before{content:"";position:absolute;inset:0 auto 0 0;width:4px;background:var(--cat)}
.top{display:flex;gap:22px;padding:22px 24px 20px 28px}
.poster{flex:none;align-self:flex-start;width:156px;aspect-ratio:2/3;border-radius:10px;overflow:hidden;background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48' fill='none' stroke='%239a9aa5' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' opacity='.6'%3E%3Crect x='6' y='9' width='36' height='30' rx='4'/%3E%3Cpath d='M20 18l10 6-10 6z'/%3E%3C/svg%3E") center/36% no-repeat,linear-gradient(160deg,var(--cat-bg),var(--soft));border:1px solid var(--line);box-shadow:0 8px 20px -10px rgba(0,0,0,.5)}
.poster img{display:block;width:100%;height:100%;object-fit:cover}
.head{min-width:0;flex:1}
.eyebrow{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.nb{white-space:nowrap}
.film h3{font:700 clamp(21px,3.2vw,30px)/1.2 var(--serif);margin:0;overflow-wrap:anywhere}
.zh{display:block;margin-top:2px;font:400 16px/1.4 -apple-system,"PingFang SC","Noto Sans SC",sans-serif;color:var(--mute)}
.badges{margin:12px 0 0;display:flex;flex-wrap:wrap;gap:6px}
.badge{font-size:12px;line-height:1.35;padding:4px 10px;border-radius:999px;background:var(--soft);border:1px solid var(--line);color:var(--ink);word-break:keep-all}
.badge.cat{background:var(--cat-bg);border-color:transparent;color:var(--cat);font-weight:700}
.badge.warn{background:var(--warn-bg);border-color:transparent;color:var(--warn);font-weight:600}
.badge.new{background:hsl(217 45% var(--catbg-l));border-color:transparent;color:hsl(217 var(--cat-s) var(--cat-l));font-weight:600}
.badge.quiet{background:transparent;color:var(--mute)}
.lead{font-size:18px;line-height:1.55;font-weight:500;margin:14px 0 0}
.compact .lead{font-size:16px}
.facts{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 14px;margin:14px 0 0;font-size:13px;color:var(--mute)}
.facts dt{font-weight:700;color:var(--ink)}
.facts dd{margin:0;overflow-wrap:anywhere}
.nb{white-space:nowrap}
.buy{display:inline-flex;align-items:center;gap:6px;margin-top:16px;padding:9px 18px;border-radius:999px;background:var(--ink);color:var(--bg);font-size:14px;font-weight:600;text-decoration:none;transition:background .15s,color .15s}
.buy:hover{background:var(--accent);color:#fff}
.body{padding:6px 24px 24px 28px;border-top:1px dashed var(--line)}
.sections{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:18px 30px;margin-top:16px}
.sec h4{margin:0 0 4px;font-size:12px;letter-spacing:.08em;color:var(--mute);font-weight:700}
.sec p{margin:0}
.sec.wide{grid-column:1/-1}
.sec.why{background:var(--cat-bg);border-radius:12px;padding:12px 16px}
.sec.why h4{color:var(--cat)}
.sec.risk{border-left:3px solid var(--warn);padding-left:12px}
.note{font-size:13px;color:var(--warn);background:var(--warn-bg);padding:8px 12px;border-radius:10px;margin:14px 0 0}
.links{margin:20px 0 0}
.links h4{margin:0 0 8px;font-size:12px;letter-spacing:.08em;color:var(--mute);font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:8px;list-style:none;margin:0;padding:0}
.chips li{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;border:1px solid var(--line);background:var(--soft);border-radius:999px;padding:4px 12px}
.chips li.score{border-color:var(--cat);background:var(--cat-bg)}
.film details{margin:0}
.film summary{cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center;padding:12px 24px 12px 28px;border-top:1px solid var(--line);color:var(--mute);font-size:14px;font-weight:600}
.film summary::-webkit-details-marker{display:none}
.film summary::after{content:"+";font-size:20px;line-height:1}
.film details[open] summary::after{content:"\2212"}
.film summary:hover{color:var(--ink);background:var(--soft)}
.film details .body{border-top:0;padding-top:0}
.grid{display:grid;grid-template-columns:minmax(0,1fr);gap:20px;align-items:start}
.grid .film{margin:0}
.compact .top{padding:18px 20px 16px 24px;gap:16px}
.compact .poster{width:96px}
.compact h3{font-size:20px}
.compact .badges{margin-top:10px}
.fold{margin:16px 0 0;padding:12px 18px;background:var(--surface);border:1px solid var(--line);border-radius:12px}
.fold>summary{cursor:pointer;color:var(--mute);font-size:14px;font-weight:600}
ul.plain{list-style:none;padding:0;margin:8px 0 0;font-size:14px}
.fold ul.plain{columns:2 340px;column-gap:36px}
ul.plain li{padding:8px 0;border-top:1px solid var(--line);overflow-wrap:anywhere;break-inside:avoid}
.pills{display:flex;flex-wrap:wrap;gap:8px;list-style:none;margin:0;padding:0}
.pills a{display:inline-block;padding:6px 14px;border-radius:999px;border:1px solid var(--line);background:var(--surface);text-decoration:none;font-size:14px}
.pills a:hover{border-color:var(--accent)}
.foot{color:var(--mute);font-size:13px;margin:10px 0}
@media (min-width:900px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:720px){
main{padding:0 14px 56px}
.hero-in,.jump .wrap{padding-left:14px;padding-right:14px}
.top{gap:14px;padding:18px 16px 16px 20px}
.poster{width:108px}
.compact .poster{width:84px}
.glance a{grid-template-columns:10px minmax(0,1fr)}
.g-meta{grid-column:2;justify-content:flex-start}
.body{padding:6px 16px 20px 20px}
.film summary{padding-left:20px;padding-right:16px}
.stats li{padding:8px 14px}
}
"""

STYLE = _STYLE_BASE + "".join(f'[data-cat="{c}"]{{--h:{h}}}\n' for c, h in HUES.items())


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def safe_url(url) -> str | None:
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url
    return None


def _md(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.month}月{d.day}日"


def status_text(film: dict) -> str:
    if film["status"] == "coming_soon":
        return f"{_md(film['release_date'])}上映"
    if film["weeks_in_release"] is None:
        return f"重映（{film['release_date'][:4]} 年上映）"
    return f"在映第 {film['weeks_in_release']} 周"


def _urgency(film: dict) -> list[str]:
    """放映时间紧的信号。限定放映来自排片事实；「抓紧」是程序推断，文字里标明。"""
    labels = []
    if film["is_event"]:
        days = "、".join(_md(d) for d in film["gta_dates"])
        labels.append(f"限定放映：{days}" if days else "限定放映")
    if film["hurry"]:
        labels.append("抓紧（推断）")
    return labels


def _badges(film: dict) -> str:
    badges = [f'<span class="badge">{esc(status_text(film))}</span>']
    badges.extend(f'<span class="badge warn">{esc(label)}</span>' for label in _urgency(film))
    if film["seen_before"] is True:
        badges.append('<span class="badge quiet">上期已推荐</span>')
    elif film["seen_before"] is False:
        badges.append('<span class="badge new">新</span>')
    return f'<div class="badges">{"".join(badges)}</div>'


def _meter(strength: int) -> str:
    n = max(0, min(5, int(strength)))
    dots = '<i class="on"></i>' * n + "<i></i>" * (5 - n)
    return f'<span class="meter" role="img" aria-label="推荐力度 {n}/5">{dots}</span>'


FOLD_THEATRES_OVER = 4


def _fold_theatres(film: dict, compact: bool) -> bool:
    """紧凑卡片上影院多于 4 家时，名单（常常就是全部影院）会撑得比正文还长：首屏只写家数，名单放进展开。"""
    return compact and len(film["gta_theatres"]) > FOLD_THEATRES_OVER


def _facts(film: dict, compact: bool = False) -> str:
    if _fold_theatres(film, compact):
        theatres = f'<span class="nb">{len(film["gta_theatres"])} 家影院</span>（名单在展开里）'
    else:
        theatres = esc("、".join(film["gta_theatres"]) if film["gta_theatres"] else "排片未出")
    rows = [("影院", theatres)]
    if film["runtime"]:
        rows.append(("片长", f'<span class="nb">{esc(film["runtime"])} 分钟</span>'))
    versions = " / ".join(
        v["language"] + (f"（{v['subtitle']} 字幕）" if v["subtitle"] else "")
        for v in film["versions"] if v["language"]
    )
    if versions:
        rows.append(("语言", esc(versions)))
    if film["rating_on"] and film["rating_on"]["rating"]:
        rows.append(("分级", f'<span class="nb">安省分级 {esc(film["rating_on"]["rating"])}</span>'))
    return '<dl class="facts">' + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows) + "</dl>"


def _section(label: str, text: str, kind: str = "") -> str:
    if not text or not text.strip():
        return ""
    return f'<div class="sec {kind}"><h4>{esc(label)}</h4><p>{esc(text)}</p></div>'


def _links(film: dict) -> str:
    card = film["card"]
    items = []
    for score in card["scores"]:
        url = safe_url(score["source_url"])
        if url:
            items.append(
                f'<li class="score">{esc(score["name"])}：<a href="{esc(url)}" rel="noopener">'
                f'{esc(score["value"])}（点开核对）</a></li>'
            )
    for source in card["sources"]:
        url = safe_url(source["url"])
        if url:
            label = source["title"] or url
            items.append(f'<li title="{esc(label)}"><a href="{esc(url)}" rel="noopener">{esc(label)}</a></li>')
    if not items:
        return ""
    return f'<div class="links"><h4>评分与来源</h4><ul class="chips">{"".join(items)}</ul></div>'


def _film_card(film: dict, compact: bool) -> str:
    card = film["card"]
    # 海报外面套一个占位块：没有海报、或者海报地址失效（onerror 把 img 移除）时，露出来的是按类别着色的占位块而不是破图标
    poster = safe_url(film["poster_url"])
    image = f'<img src="{esc(poster)}" alt="" loading="lazy" onerror="this.remove()">' if poster else ""
    poster_html = f'<div class="poster">{image}</div>'
    title_zh = f'<span class="zh">{esc(card["title_zh"])}</span>' if card["title_zh"] else ""
    notes = []
    if card["evidence"] in EVIDENCE_NOTES:
        notes.append(EVIDENCE_NOTES[card["evidence"]])
    notes.extend(film["flags"])
    if card.get("sources_dropped"):
        notes.append(f"有 {card['sources_dropped']} 条来源没通过校验，已去掉。")
    sections = (
        (_section("放映影院", "、".join(film["gta_theatres"]), "wide") if _fold_theatres(film, compact) else "")
        + _section("讲什么", card["premise"], "wide")
        + _section("为什么对你胃口", card["why_for_you"], "wide why")
        + _section("口碑", card["reception"])
        + _section("创作背景", card["background"])
        + _section("可能踩雷", card["caveats"], "risk")
    )
    body = (
        "".join(f'<p class="note">{esc(n)}</p>' for n in notes)
        + (f'<div class="sections">{sections}</div>' if sections else "")
        + _links(film)
    )
    body = f'<div class="body">{body}</div>'
    if compact:
        body = f"<details><summary>展开</summary>{body}</details>"
    lead = f'<p class="lead">{esc(card["one_liner"])}</p>' if card["one_liner"].strip() else ""
    category = CATEGORY_LABELS.get(card["category"], card["category"])
    detail = safe_url(film["detail_url"])
    buy = f'<a class="buy" href="{esc(detail)}" rel="noopener">Cineplex 页面与购票</a>' if detail else ""
    fid = int(film["film_id"])
    kind = "compact" if compact else "feature"
    return (
        f'<article class="film {kind}" id="film-{fid}" data-film="{fid}" data-cat="{esc(card["category"])}">'
        f'<div class="top">{poster_html}<div class="head">'
        f'<div class="eyebrow"><span class="badge cat">{esc(category)}</span>{_meter(card["strength"])}</div>'
        f'<h3>{esc(film["title"])}{title_zh}</h3>'
        f"{_badges(film)}{lead}{_facts(film, compact)}{buy}"
        f"</div></div>{body}</article>"
    )


def _by_strength(films: list[dict]) -> list[dict]:
    return sorted(films, key=lambda f: (-f["card"]["strength"], f["title"], f["film_id"]))


def _by_title(films: list[dict]) -> list[dict]:
    return sorted(films, key=lambda f: (f["title"], f["film_id"]))


def _glance_row(film: dict, tier: str) -> str:
    card = film["card"]
    fid = int(film["film_id"])
    title_zh = f"<small>{esc(card['title_zh'])}</small>" if card["title_zh"] else ""
    tier_tag = '<span class="g-tier">重点</span>' if tier == "must" else ""
    hot = "".join(f'<span class="g-hot">{esc(label)}</span>' for label in _urgency(film))
    category = CATEGORY_LABELS.get(card["category"], card["category"])
    return (
        f'<li data-cat="{esc(card["category"])}"><a href="#film-{fid}"><i class="g-dot"></i>'
        f'<span class="g-title">{esc(film["title"])}{title_zh}</span>'
        f'<span class="g-meta">{tier_tag}<span class="g-cat">{esc(category)}</span>'
        f'<span>{esc(status_text(film))}</span>{hot}{_meter(card["strength"])}</span></a></li>'
    )


def _glance_section(must: list[dict], ok: list[dict]) -> str:
    if not must and not ok:
        return ""
    rows = "".join(_glance_row(f, "must") for f in _by_strength(must)) + "".join(_glance_row(f, "ok") for f in _by_strength(ok))
    return f'<section id="glance"><h2>本期速览</h2><ul class="glance">{rows}</ul></section>'


def _count(n: int) -> str:
    return f'<span class="count">{n}</span>'


def _must_section(films: list[dict]) -> str:
    if not films:
        return '<h2 id="must">重点推荐</h2><p class="empty">本期没有重点推荐。</p>'
    return f'<h2 id="must">重点推荐{_count(len(films))}</h2>' + "".join(_film_card(f, compact=False) for f in _by_strength(films))


def _ok_section(films: list[dict]) -> str:
    if not films:
        return ""
    cards = "".join(_film_card(f, compact=True) for f in _by_strength(films))
    return f'<h2 id="ok">可以看{_count(len(films))}</h2><div class="grid">{cards}</div>'


def _failed_section(films: list[dict]) -> str:
    if not films:
        return ""
    rows = "".join(
        f'<li data-film="{int(f["film_id"])}"><b>{esc(f["title"])}</b>（{esc(status_text(f))}）<br>'
        f'粗筛时的判断：{esc(f["verdict"]["reason"])}<br>没评成的原因：{esc(f["review_error"])}</li>'
        for f in _by_title(films)
    )
    return f'<h2>本期未能评估</h2><ul class="plain">{rows}</ul>'


def _skip_section(films: list[dict]) -> str:
    if not films:
        return ""
    rows = "".join(
        f'<li data-film="{int(f["film_id"])}"><b>{esc(f["title"])}</b>：{esc(f["outcome_reason"])}</li>'
        for f in _by_title(films)
    )
    return f'<details class="fold" id="skip"><summary>跳过的片（{len(films)}）</summary><ul class="plain">{rows}</ul></details>'


def _events_section(events: list[dict]) -> str:
    if not events:
        return ""
    rows = "".join(
        f'<li>{esc(e["name"])}（{esc("、".join(e["categories"]))}）</li>'
        for e in sorted(events, key=lambda e: e["name"])
    )
    return (
        f'<details class="fold"><summary>已过滤的非电影活动（{len(events)}）</summary>'
        f'<ul class="plain">{rows}</ul></details>'
    )


def _stale_banner(edition: dict) -> str:
    made = datetime.fromisoformat(edition["generated_at"]).isoformat()
    days = int(edition["settings"]["stale_after_days"])
    return (
        '<p id="stale" class="stale" hidden>这一期已过期，新一期可能生成失败。</p>'
        "<script>(function(){"
        f'var made=new Date("{made}");'
        f"if((Date.now()-made.getTime())/864e5>{days})"
        '{document.getElementById("stale").hidden=false;}'
        "})();</script>"
    )


def cost_text(usage: dict) -> str:
    """费用一句话。早期的期数据没有搜索费字段（当时没核实过单价），保持原来的说法，不把没算过的数说成算过。"""
    if "estimated_cost_usd" in usage:
        return (f'费用估算 ${usage["estimated_cost_usd"]:.2f}'
                f'（token ${usage["estimated_token_cost_usd"]:.2f} + 搜索 ${usage["estimated_search_cost_usd"]:.2f}）')
    return f'token 费用估算 ${usage["estimated_token_cost_usd"]:.2f}（不含搜索费）'


def _footer(edition: dict, archive: list[tuple[str, int]], is_latest: bool, prefix: str) -> str:
    usage = edition["usage"]
    lines = [
        f'<p class="foot">本期用量：{usage["calls"]} 次模型调用，'
        f'输入 {usage["input_tokens"]:,} / 输出 {usage["output_tokens"]:,} token，'
        f'联网搜索 {usage["searches"]} 次；{cost_text(usage)}，以账单为准。</p>'
    ]
    if edition["orphan_ids"]:
        ids = "、".join(str(i) for i in edition["orphan_ids"])
        lines.append(
            f'<p class="foot">排片里有 {len(edition["orphan_ids"])} 个片单没有的影片编号（{esc(ids)}），'
            "这些片没有进入候选。</p>"
        )
    lines.append('<p class="foot">推荐由模型生成。评分和口碑请点来源核对。</p>')
    rows = "".join(
        f'<li><a href="{esc(prefix)}editions/{esc(edition_id)}.html">第 {number} 期 · {esc(edition_id)}</a></li>'
        for edition_id, number in archive
    )
    latest = "" if is_latest else f'<p class="foot"><a href="{esc(prefix)}index.html">回到最新一期</a></p>'
    return f'<h2 id="archive">往期</h2><ul class="pills">{rows}</ul>{latest}{"".join(lines)}'


def _hero(edition: dict, title: str, is_latest: bool) -> str:
    made = edition["generated_at"][:16].replace("T", " ")
    meta = "".join(f"<li>{item}</li>" for item in (
        esc(edition["edition_id"]),
        f'GTA {edition["settings"]["radius_km"]:g} 公里内的 Cineplex',
        f"数据抓取于 {esc(made)}",
        f'下期 {esc(edition["next_edition_date"])}',
    ))
    counts = edition["counts"]
    stats = [("must", "重点推荐"), ("ok", "可以看"), ("skip", "跳过")]
    items = "".join(f"<li><b>{counts[key]}</b> {label}</li>" for key, label in stats)
    if counts["review_failed"]:
        items += f'<li class="bad"><b>{counts["review_failed"]}</b> 未能评估</li>'
    return (
        '<header class="hero"><div class="hero-in">'
        '<p class="kicker">Film Radar · Toronto</p>'
        f"<h1>{esc(title)}</h1><ul class=\"meta\">{meta}</ul><ul class=\"stats\">{items}</ul>"
        f"{_stale_banner(edition) if is_latest else ''}</div></header>"
    )


def _nav(has_glance: bool, must: int, ok: int, skip: int) -> str:
    links = []
    if has_glance:
        links.append('<a href="#glance">速览</a>')
    if must:
        links.append(f'<a href="#must">重点推荐<span>{must}</span></a>')
    if ok:
        links.append(f'<a href="#ok">可以看<span>{ok}</span></a>')
    if skip:
        links.append(f'<a href="#skip">跳过<span>{skip}</span></a>')
    links.append('<a href="#archive">历史期数</a>')
    return f'<nav class="jump" aria-label="本期章节"><div class="wrap">{"".join(links)}</div></nav>'


def render_edition(edition: dict, number: int, archive: list[tuple[str, int]], *,
                   is_latest: bool, prefix: str) -> str:
    films = edition["films"]

    def of(outcome: str) -> list[dict]:
        return [f for f in films if f["outcome"] == outcome]

    title = f"多伦多院线 · 第 {number} 期"
    glance = _glance_section(of("must"), of("ok"))
    body = (
        glance
        + _must_section(of("must"))
        + _ok_section(of("ok"))
        + _failed_section(of("review_failed"))
        + _skip_section(of("skip"))
        + _events_section(edition["filtered_events"])
        + _footer(edition, archive, is_latest, prefix)
    )
    return (
        '<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="robots" content="noindex">'
        f"<title>{esc(title)}</title><style>{STYLE}</style></head>"
        f"<body>{_hero(edition, title, is_latest)}"
        f"{_nav(bool(glance), len(of('must')), len(of('ok')), len(of('skip')))}"
        f"<main>{body}</main></body></html>"
    )


def render_site(editions: list[dict], out_dir: Path) -> None:
    if not editions:
        raise ValueError("没有任何一期数据，无法生成站点")
    ordered = sorted(editions, key=lambda e: e["edition_id"])
    numbered = [(edition, i + 1) for i, edition in enumerate(ordered)]
    archive = [(edition["edition_id"], number) for edition, number in reversed(numbered)]
    pages = out_dir / "editions"
    pages.mkdir(parents=True, exist_ok=True)
    for edition, number in numbered:
        page = render_edition(edition, number, archive, is_latest=False, prefix="../")
        (pages / f'{edition["edition_id"]}.html').write_text(page, encoding="utf-8")
    latest, number = numbered[-1]
    index = render_edition(latest, number, archive, is_latest=True, prefix="")
    (out_dir / "index.html").write_text(index, encoding="utf-8")


def _no_mention(text: str) -> str:
    """在 @ 后面插一个零宽空格（U+200B），免得 Issue 里的文字通知到不相干的 GitHub 用户。"""
    return text.replace("@", "@​")


def issue_title(edition: dict, number: int) -> str:
    day = date.fromisoformat(edition["edition_id"])
    musts = _by_strength([f for f in edition["films"] if f["outcome"] == "must"])
    picks = "、".join(f["title"] for f in musts) if musts else "本期没有重点推荐"
    title = _no_mention(f"第 {number} 期 {day.month}/{day.day}：{picks}")
    if len(title) > ISSUE_TITLE_LIMIT:
        title = title[: ISSUE_TITLE_LIMIT - 1] + "…"
    return title


def issue_body(edition: dict, number: int, page_url: str) -> str:
    musts = _by_strength([f for f in edition["films"] if f["outcome"] == "must"])
    lines = []
    if musts:
        lines.append(f"第 {number} 期重点推荐：")
        lines.append("")
        for film in musts:
            lines.append(_no_mention(
                f"- **{film['title']}**（{status_text(film)}）：{film['card']['one_liner']}"
            ))
    else:
        lines.append("本期没有重点推荐。")
    counts = edition["counts"]
    summary = f"可以看 {counts['ok']} 部，跳过 {counts['skip']} 部"
    if counts["review_failed"]:
        summary += f"，未能评估 {counts['review_failed']} 部"
    lines += ["", summary + "。", "", f"完整页面：{page_url}"]
    return "\n".join(lines) + "\n"
