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
    "outside": "口味之外",
}
EVIDENCE_NOTES = {
    "thin": "目前评论很少，下面的判断依据有限。",
    "none": "没有通过校验的来源，下面的内容未经查证。",
}
ISSUE_TITLE_LIMIT = 200

STYLE = """
:root{--bg:#f4f4f2;--card:#fff;--ink:#1c1c1c;--mute:#6b6b6b;--line:#e2e2de;--warn:#9a3412;--new:#1d4ed8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:20px 16px 56px}
header h1{font-size:22px;margin:0 0 4px}
.meta,.foot{color:var(--mute);font-size:13px;margin:4px 0}
.stale{background:#fff7ed;border:1px solid #fdba74;color:var(--warn);padding:10px 12px;border-radius:8px;margin:12px 0;font-size:14px}
h2{font-size:15px;letter-spacing:.08em;color:var(--mute);margin:32px 0 12px;font-weight:600}
.film{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:0 0 14px}
.top{display:flex;gap:14px}
.top>div{min-width:0}
.poster{width:92px;height:138px;border-radius:6px;background:var(--line);flex:none;overflow:hidden}
.poster img{display:block;width:100%;height:100%;object-fit:cover}
.nb{white-space:nowrap}
.film h3{font-size:19px;margin:0;line-height:1.3;overflow-wrap:anywhere}
.zh{display:block;font-size:15px;color:var(--mute);font-weight:400}
.badges{margin:8px 0 6px;display:flex;flex-wrap:wrap;gap:6px}
.badge{font-size:11.5px;line-height:1.35;padding:5px 8px;border-radius:12px;background:#ececea;color:#333;word-break:keep-all}
.badge.warn{background:#ffedd5;color:var(--warn)}
.badge.new{background:#dbeafe;color:var(--new)}
.badge.quiet{background:transparent;border:1px solid var(--line);color:var(--mute)}
.facts{font-size:13px;color:var(--mute);margin:0}
.lead{font-size:17px;margin:14px 0 4px}
.sec h4{font-size:13px;color:var(--mute);margin:14px 0 2px;font-weight:600}
.sec p{margin:0}
.note{font-size:13px;color:var(--warn);margin:12px 0 0}
.links{font-size:13px;margin:12px 0 0;padding:0;list-style:none}
.links li{margin:2px 0;overflow-wrap:anywhere}
a{color:#0f4c81}
details{margin-top:10px}
summary{cursor:pointer;color:var(--mute);font-size:14px}
ul.plain{list-style:none;padding:0;margin:0;font-size:14px}
ul.plain li{padding:8px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}
.empty{color:var(--mute)}
"""


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
    return f"在映第 {film['weeks_in_release']} 周"


def _badges(film: dict, category: str | None) -> str:
    badges = []
    if category:
        badges.append(f'<span class="badge">{esc(category)}</span>')
    badges.append(f'<span class="badge">{esc(status_text(film))}</span>')
    if film["is_event"]:
        days = "、".join(_md(d) for d in film["gta_dates"])
        label = f"限定放映：{days}" if days else "限定放映"
        badges.append(f'<span class="badge warn">{esc(label)}</span>')
    if film["hurry"]:
        badges.append('<span class="badge warn">抓紧（推断）</span>')
    if film["seen_before"] is True:
        badges.append('<span class="badge quiet">上期已推荐</span>')
    elif film["seen_before"] is False:
        badges.append('<span class="badge new">新</span>')
    return f'<div class="badges">{"".join(badges)}</div>'


def _facts(film: dict) -> str:
    parts = [esc("、".join(film["gta_theatres"]) if film["gta_theatres"] else "排片未出")]
    if film["runtime"]:
        parts.append(f'<span class="nb">{esc(film["runtime"])} 分钟</span>')
    versions = " / ".join(
        v["language"] + (f"（{v['subtitle']} 字幕）" if v["subtitle"] else "")
        for v in film["versions"] if v["language"]
    )
    if versions:
        parts.append(esc(versions))
    if film["rating_on"] and film["rating_on"]["rating"]:
        parts.append(f'<span class="nb">安省分级 {esc(film["rating_on"]["rating"])}</span>')
    return f'<p class="facts">{" · ".join(parts)}</p>'


def _section(label: str, text: str) -> str:
    if not text or not text.strip():
        return ""
    return f'<div class="sec"><h4>{esc(label)}</h4><p>{esc(text)}</p></div>'


def _links(film: dict) -> str:
    card = film["card"]
    items = []
    for score in card["scores"]:
        url = safe_url(score["source_url"])
        if url:
            items.append(
                f'<li>{esc(score["name"])}：<a href="{esc(url)}" rel="noopener">'
                f'{esc(score["value"])}（点开核对）</a></li>'
            )
    for source in card["sources"]:
        url = safe_url(source["url"])
        if url:
            items.append(f'<li><a href="{esc(url)}" rel="noopener">{esc(source["title"] or url)}</a></li>')
    detail = safe_url(film["detail_url"])
    if detail:
        items.append(f'<li><a href="{esc(detail)}" rel="noopener">Cineplex 页面与购票</a></li>')
    return f'<ul class="links">{"".join(items)}</ul>' if items else ""


def _film_card(film: dict, compact: bool) -> str:
    card = film["card"]
    # 海报外面套一个灰色占位块：没有海报、或者海报地址失效（onerror 把 img 移除）时，露出来的是占位块而不是破图标
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
    body = (
        "".join(f'<p class="note">{esc(n)}</p>' for n in notes)
        + _section("讲什么", card["premise"])
        + _section("为什么对你胃口", card["why_for_you"])
        + _section("口碑", card["reception"])
        + _section("创作背景", card["background"])
        + _section("可能踩雷", card["caveats"])
        + _links(film)
    )
    if compact:
        body = f"<details><summary>展开</summary>{body}</details>"
    lead = f'<p class="lead">{esc(card["one_liner"])}</p>' if card["one_liner"].strip() else ""
    category = CATEGORY_LABELS.get(card["category"], card["category"])
    return (
        f'<article class="film" data-film="{int(film["film_id"])}">'
        f'<div class="top">{poster_html}<div>'
        f'<h3>{esc(film["title"])}{title_zh}</h3>'
        f"{_badges(film, category)}{_facts(film)}"
        f"</div></div>{lead}{body}</article>"
    )


def _by_strength(films: list[dict]) -> list[dict]:
    return sorted(films, key=lambda f: (-f["card"]["strength"], f["title"], f["film_id"]))


def _by_title(films: list[dict]) -> list[dict]:
    return sorted(films, key=lambda f: (f["title"], f["film_id"]))


def _must_section(films: list[dict]) -> str:
    if not films:
        return '<h2>重点推荐</h2><p class="empty">本期没有重点推荐。</p>'
    return "<h2>重点推荐</h2>" + "".join(_film_card(f, compact=False) for f in _by_strength(films))


def _ok_section(films: list[dict]) -> str:
    if not films:
        return ""
    return "<h2>可以看</h2>" + "".join(_film_card(f, compact=True) for f in _by_strength(films))


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
    return f'<details><summary>跳过的片（{len(films)}）</summary><ul class="plain">{rows}</ul></details>'


def _events_section(events: list[dict]) -> str:
    if not events:
        return ""
    rows = "".join(
        f'<li>{esc(e["name"])}（{esc("、".join(e["categories"]))}）</li>'
        for e in sorted(events, key=lambda e: e["name"])
    )
    return (
        f"<details><summary>已过滤的非电影活动（{len(events)}）</summary>"
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


def _footer(edition: dict, archive: list[tuple[str, int]], is_latest: bool, prefix: str) -> str:
    usage = edition["usage"]
    lines = [
        f'<p class="foot">本期用量：{usage["calls"]} 次模型调用，'
        f'输入 {usage["input_tokens"]:,} / 输出 {usage["output_tokens"]:,} token，'
        f'联网搜索 {usage["searches"]} 次；token 费用估算 ${usage["estimated_token_cost_usd"]:.2f}'
        "（不含搜索费，以账单为准）。</p>"
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
    return f'<h2>往期</h2><ul class="plain">{rows}</ul>{latest}{"".join(lines)}'


def render_edition(edition: dict, number: int, archive: list[tuple[str, int]], *,
                   is_latest: bool, prefix: str) -> str:
    films = edition["films"]

    def of(outcome: str) -> list[dict]:
        return [f for f in films if f["outcome"] == outcome]

    title = f"多伦多院线 · 第 {number} 期"
    made = edition["generated_at"][:16].replace("T", " ")
    meta = (
        f'{esc(edition["edition_id"])} · GTA {edition["settings"]["radius_km"]:g} 公里内的 Cineplex · '
        f'数据抓取于 {esc(made)} · 下期 {esc(edition["next_edition_date"])}'
    )
    body = (
        f"<header><h1>{esc(title)}</h1><p class=\"meta\">{meta}</p>"
        f"{_stale_banner(edition) if is_latest else ''}</header>"
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
        '<meta name="robots" content="noindex">'
        f"<title>{esc(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
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
