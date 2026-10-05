import html as htmllib
import re
from datetime import date

import pytest

from film_radar.render import (
    CATEGORY_LABELS, ISSUE_TITLE_LIMIT, issue_body, issue_title, render_edition, render_site, status_text,
)
from helpers import broken, build_edition, failed_review, make_candidate, make_verdict, recommended, skipped

PAGE_URL = "https://akasha-r.github.io/film-radar/"
SRC = "https://example.com/review"


def page(edition, number=1, latest=True):
    archive = [(edition["edition_id"], number)]
    return render_edition(edition, number, archive, is_latest=latest, prefix="" if latest else "../")


def card_html(html, film_id):
    """取出某一部片的那张卡片。"""
    match = re.search(rf'<article class="film[^"]*"[^>]*data-film="{film_id}"[^>]*>.*?</article>', html, re.S)
    assert match, f"页面上没有 film {film_id} 的卡片"
    return match.group(0)


@pytest.fixture
def mixed(settings):
    return build_edition(settings, [
        recommended(1, "Must One", tier="must", category="horror"),
        recommended(2, "Ok Two", tier="ok", category="japanese"),
        recommended(3, "Card Skip", tier="skip", skip_reason="其实是砍杀片"),
        skipped(4, "Triage Skip", reason="儿童动画"),
        broken(5, "Broken Five", error="联网搜索没有返回任何结果"),
    ], filtered_events=[{"film_id": 61729, "name": "Così fan tutte", "categories": ["Opera"]}])


# ---- 每部片恰好出现一次 ----

def test_every_candidate_appears_exactly_once(mixed):
    html = page(mixed)
    for film in mixed["films"]:
        assert html.count(f'data-film="{film["film_id"]}"') == 1, film["title"]


def test_sections_are_in_order(mixed):
    html = page(mixed)
    order = [html.index(marker) for marker in ("重点推荐", "可以看", "本期未能评估", "跳过的片（2）", "已过滤的非电影活动（1）", "往期")]
    assert order == sorted(order)


# ---- 重点推荐卡片 ----

def test_must_card_shows_every_field(settings):
    candidate = {"gta_theatres": ["Cineplex Cinemas Varsity and VIP", "Scotiabank Theatre Toronto"],
                 "runtime": 129, "rating_on": {"rating": "14A", "warnings": []}}
    edition = build_edition(settings, [recommended(
        1, "Must One", candidate, category="horror", title_zh="第一部", title_zh_source=SRC,
        scores=[{"name": "Metacritic", "value": "81", "source_url": SRC}],
        sources=[{"title": "RogerEbert 影评", "url": SRC}],
    )])
    card = card_html(page(edition), 1)
    for text in ("Must One", "第一部", "恐怖", "在映第 1 周",
                 "Cineplex Cinemas Varsity and VIP、Scotiabank Theatre Toronto", "129 分钟", "安省分级 14A",
                 "一句话定位。", "讲什么", "为什么对你胃口", "口碑", "创作背景", "可能踩雷",
                 "Metacritic", "点开核对", "RogerEbert 影评", "Cineplex 页面与购票"):
        assert text in card, text
    assert f'href="{SRC}"' in card
    assert 'href="https://www.cineplex.com/movie/film-1"' in card
    assert "<details>" not in card


def test_ok_card_body_is_collapsed(mixed):
    card = card_html(page(mixed), 2)
    assert "日本电影" in card
    assert "<details><summary>展开</summary>" in card
    assert card.index("一句话定位。") < card.index("<details>")


def test_no_must_says_so(settings):
    html = page(build_edition(settings, [skipped(1, "A")]))
    assert "本期没有重点推荐。" in html
    assert "可以看</h2>" not in html


def test_cards_are_sorted_by_strength(settings):
    edition = build_edition(settings, [
        recommended(1, "Weak", tier="must", strength=2),
        recommended(2, "Strong", tier="must", strength=5),
    ])
    html = page(edition)
    assert html.index('data-film="2"') < html.index('data-film="1"')


def test_category_labels_cover_every_category():
    from film_radar.triage import CATEGORIES
    assert set(CATEGORY_LABELS) == set(CATEGORIES)


# ---- 未能评估、跳过、已过滤 ----

def test_failed_section_shows_both_reasons(mixed):
    html = page(mixed)
    assert "本期未能评估" in html
    row = re.search(r'<li data-film="5">.*?</li>', html, re.S).group(0)
    assert "Broken Five" in row
    assert "粗筛理由" in row
    assert "联网搜索没有返回任何结果" in row


def test_failed_section_absent_without_failures(settings):
    assert "本期未能评估" not in page(build_edition(settings, [recommended(1, "A")]))


def test_skip_list_shows_reasons(mixed):
    html = page(mixed)
    assert "其实是砍杀片" in re.search(r'<li data-film="3">.*?</li>', html, re.S).group(0)
    assert "儿童动画" in re.search(r'<li data-film="4">.*?</li>', html, re.S).group(0)


def test_filtered_events_are_listed_with_categories(mixed):
    html = page(mixed)
    assert "已过滤的非电影活动（1）" in html
    assert "Così fan tutte（Opera）" in html


def test_empty_optional_sections_are_absent(settings):
    html = page(build_edition(settings, [recommended(1, "A")]))
    assert "跳过的片" not in html
    assert "已过滤的非电影活动" not in html


# ---- 徽标与事实行 ----

def test_coming_soon_without_showtimes(settings):
    candidate = {"status": "coming_soon", "release_date": "2026-10-09", "weeks_in_release": None,
                 "gta_theatres": [], "gta_dates": []}
    card = card_html(page(build_edition(settings, [recommended(1, "Soon", candidate)])), 1)
    assert "10月9日上映" in card
    assert "排片未出" in card


def test_event_badge_lists_screening_dates(settings):
    candidate = {"is_event": True, "status": "coming_soon", "release_date": "2026-10-04",
                 "weeks_in_release": None, "gta_dates": ["2026-10-04", "2026-10-06"]}
    card = card_html(page(build_edition(settings, [recommended(1, "Ninja Scroll 4K", candidate)])), 1)
    assert "限定放映：10月4日、10月6日" in card


def test_event_badge_without_dates(settings):
    candidate = {"is_event": True, "gta_dates": [], "gta_theatres": []}
    card = card_html(page(build_edition(settings, [recommended(1, "Event", candidate)])), 1)
    assert "限定放映</span>" in card


def test_hurry_badge_is_marked_as_inference(settings):
    card = card_html(page(build_edition(settings, [recommended(1, "Old", {"hurry": True, "weeks_in_release": 4})])), 1)
    assert "抓紧（推断）" in card
    assert "在映第 4 周" in card


def test_seen_before_badges(settings):
    previous = build_edition(settings, [recommended(1, "Again")], run_date=date(2026, 9, 24))
    edition = build_edition(settings, [recommended(1, "Again"), recommended(2, "Fresh")], previous=previous)
    html = page(edition)
    assert "上期已推荐" in card_html(html, 1)
    assert '<span class="badge new">新</span>' in card_html(html, 2)

    first = page(build_edition(settings, [recommended(1, "Again")]))
    assert "上期已推荐" not in first
    assert 'badge new' not in first


def test_all_language_versions_are_shown(settings):
    versions = [
        {"film_id": 61994, "name": "Ninja Scroll 4K", "language": "English", "subtitle": ""},
        {"film_id": 61995, "name": "Ninja Scroll 4K (Japanese w.e.s.t.)", "language": "Japanese", "subtitle": "English"},
    ]
    card = card_html(page(build_edition(settings, [recommended(1, "Ninja Scroll 4K", {"versions": versions})])), 1)
    assert "English / Japanese（English 字幕）" in card


# ---- 提示 ----

@pytest.mark.parametrize("evidence, note", [
    ("thin", "目前评论很少"),
    ("none", "没有通过校验的来源"),
])
def test_evidence_notes(settings, evidence, note):
    edition = build_edition(settings, [recommended(1, "A", tier="ok", evidence=evidence)])
    assert note in card_html(page(edition), 1)


def test_ample_evidence_has_no_note(settings):
    card = card_html(page(build_edition(settings, [recommended(1, "A")])), 1)
    assert 'class="note"' not in card


def test_flags_and_dropped_sources_are_shown(settings):
    edition = build_edition(settings, [recommended(1, "A", tier="must", sources=[], sources_dropped=2)])
    card = card_html(page(edition), 1)
    assert "无有效来源，不能列入重点推荐" in card
    assert "有 2 条来源没通过校验" in card


def test_empty_card_fields_are_omitted(settings):
    edition = build_edition(settings, [recommended(1, "A", caveats="", background="   ")])
    card = card_html(page(edition), 1)
    assert "可能踩雷" not in card
    assert "创作背景" not in card
    assert "讲什么" in card


# ---- 安全 ----

def test_model_and_cineplex_text_is_escaped(settings):
    edition = build_edition(settings, [recommended(
        1, "<b>Bold</b> Title", one_liner='<script>alert("x")</script>', premise="a < b & c",
        sources=[{"title": "<i>来源</i>", "url": SRC}],
    )])
    html = page(edition)
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "<b>Bold</b>" not in html
    assert "&lt;b&gt;Bold&lt;/b&gt; Title" in html
    assert "a &lt; b &amp; c" in html
    assert "<i>来源</i>" not in html


def test_non_http_urls_are_never_linked(settings):
    candidate = {"poster_url": "javascript:alert(1)", "detail_url": "data:text/html,x"}
    edition = build_edition(settings, [recommended(
        1, "A", candidate,
        sources=[{"title": "坏来源", "url": "javascript:alert(2)"}, {"title": "好来源", "url": SRC}],
        scores=[{"name": "X", "value": "9", "source_url": "javascript:alert(3)"}],
    )])
    html = page(edition)
    assert "javascript:" not in html
    assert "data:text/html" not in html
    assert "好来源" in html
    assert "坏来源" not in html


def test_missing_poster_renders_a_placeholder(settings):
    edition = build_edition(settings, [
        recommended(1, "No Poster", {"poster_url": ""}),
        recommended(2, "Has Poster"),
    ])
    html = page(edition)
    assert 'src=""' not in html
    assert html.count("<img ") == 1
    assert "<img " not in card_html(html, 1)


# ---- 页头、页脚、过期提示 ----

def test_header_and_meta(mixed):
    html = page(mixed, number=3)
    assert html.startswith("<!DOCTYPE html>")
    assert '<html lang="zh-Hans">' in html
    assert 'name="viewport"' in html
    assert 'content="noindex"' in html
    assert "第 3 期" in html
    assert "2026-10-08" in html
    assert "40 公里" in html
    assert "下期 2026-10-22" in html
    assert "2026-10-08 07:05" in html


def test_stale_banner_only_on_latest_page(mixed):
    latest = page(mixed, latest=True)
    assert 'id="stale"' in latest
    assert 'new Date("2026-10-08T07:05:00-04:00")' in latest
    assert ">16)" in latest
    archived = page(mixed, latest=False)
    assert 'id="stale"' not in archived
    assert "getElementById(\"stale\")" not in archived       # 往期页没有过期提示脚本（但有「我已经看过」的脚本，见下）


def test_footer_shows_usage_and_disclaimer(mixed):
    html = page(mixed)
    assert "3 次模型调用" in html
    assert "输入 1,000 / 输出 500 token" in html
    assert "联网搜索 4 次" in html
    assert "$0.01" in html
    assert "不含搜索费" in html
    assert "评分和口碑请点来源核对" in html


def test_orphan_ids_are_reported_in_footer(settings):
    with_orphans = page(build_edition(settings, [recommended(1, "A")], orphan_ids=[999998, 999999]))
    assert "排片里有 2 个片单没有的影片编号（999998、999999）" in with_orphans
    assert "片单没有的影片编号" not in page(build_edition(settings, [recommended(1, "A")]))


# ---- 整站 ----

def test_render_site_writes_index_and_one_page_per_edition(settings, tmp_path):
    older = build_edition(settings, [recommended(1, "Older Pick")], run_date=date(2026, 9, 24),
                          generated_at="2026-09-24T07:05:00-04:00")
    newer = build_edition(settings, [recommended(2, "Newer Pick")])
    render_site([newer, older], tmp_path)   # 故意乱序传入

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "第 2 期" in index and "Newer Pick" in index
    assert 'id="stale"' in index
    assert 'href="editions/2026-10-08.html"' in index
    assert 'href="editions/2026-09-24.html"' in index
    assert index.index("2026-10-08.html") < index.index("2026-09-24.html")

    first = (tmp_path / "editions" / "2026-09-24.html").read_text(encoding="utf-8")
    assert "第 1 期" in first and "Older Pick" in first
    assert 'id="stale"' not in first
    assert 'href="../index.html"' in first
    assert 'href="../editions/2026-10-08.html"' in first
    assert (tmp_path / "editions" / "2026-10-08.html").exists()


def test_render_site_needs_at_least_one_edition(tmp_path):
    with pytest.raises(ValueError, match="没有任何一期"):
        render_site([], tmp_path)


# ---- Issue 文本 ----

def test_status_text():
    assert status_text({"status": "now_playing", "weeks_in_release": 2, "release_date": "2026-10-02"}) == "在映第 2 周"
    assert status_text({"status": "coming_soon", "weeks_in_release": None, "release_date": "2026-11-06"}) == "11月6日上映"


def test_issue_title_lists_must_films(settings):
    edition = build_edition(settings, [
        recommended(1, "Weak Pick", tier="must", strength=2),
        recommended(2, "Strong Pick", tier="must", strength=5),
        recommended(3, "Just Ok", tier="ok"),
    ])
    assert issue_title(edition, 4) == "第 4 期 10/8：Strong Pick、Weak Pick"


def test_issue_title_without_must(settings):
    assert issue_title(build_edition(settings, [skipped(1, "A")]), 1) == "第 1 期 10/8：本期没有重点推荐"


def test_issue_title_is_truncated(settings):
    entries = [recommended(i, f"A Very Long Film Title Number {i} " + "x" * 40, tier="must") for i in range(1, 7)]
    title = issue_title(build_edition(settings, entries), 1)
    assert len(title) <= ISSUE_TITLE_LIMIT
    assert title.endswith("…")
    assert title.startswith("第 1 期 10/8：")


def test_issue_body(settings):
    edition = build_edition(settings, [
        recommended(1, "Pick", {"status": "coming_soon", "release_date": "2026-10-09", "weeks_in_release": None},
                    tier="must", one_liner="一部民俗恐怖片。"),
        recommended(2, "Fine", tier="ok"),
        skipped(3, "Nope"),
        broken(4, "Broken"),
    ])
    body = issue_body(edition, 1, PAGE_URL)
    assert "- **Pick**（10月9日上映）：一部民俗恐怖片。" in body
    assert "可以看 1 部，跳过 1 部，未能评估 1 部。" in body
    assert f"完整页面：{PAGE_URL}" in body
    assert "Fine" not in body


def test_issue_body_without_must_or_failures(settings):
    body = issue_body(build_edition(settings, [skipped(1, "A")]), 1, PAGE_URL)
    assert "本期没有重点推荐。" in body
    assert "未能评估" not in body


def test_issue_text_never_mentions_github_users(settings):
    edition = build_edition(settings, [recommended(1, "Film by @someone", tier="must", one_liner="导演 @octocat 的新作。")])
    assert "@someone" not in issue_title(edition, 1)
    assert "@octocat" not in issue_body(edition, 1, PAGE_URL)
    assert "octocat" in issue_body(edition, 1, PAGE_URL)


def test_status_text_for_a_rerelease_does_not_invent_a_week_count():
    film = {"status": "now_playing", "weeks_in_release": None, "release_date": "2020-07-10"}
    assert status_text(film) == "重映（2020 年上映）"


def test_hostile_text_is_escaped_in_every_sink(settings):
    """每一处会写进页面的模型 / Cineplex 文本都带上同一个恶意串，页面里不能出现未转义的标签。
    不能只测几处：漏转义往往就漏在没人想到的那一处。"""
    mark = "<x-mark>&\"'"
    escaped = htmllib.escape(mark, quote=True)
    candidate = {
        "gta_theatres": [mark], "runtime": 100, "rating_on": {"rating": mark, "warnings": []},
        "versions": [{"film_id": 1, "name": "n", "language": mark, "subtitle": mark}],
        "poster_url": 'https://example.com/p.jpg"><x-mark>', "detail_url": 'https://example.com/d"><x-mark>',
    }
    edition = build_edition(settings, [
        recommended(
            1, mark, candidate, category="horror", title_zh=mark, title_zh_source=SRC, evidence="thin",
            one_liner=mark, premise=mark, why_for_you=mark, reception=mark, background=mark, caveats=mark,
            scores=[{"name": mark, "value": mark, "source_url": SRC}],
            sources=[{"title": mark, "url": SRC}],
        ),
        skipped(3, mark, reason=mark),
        (make_candidate(4, mark), make_verdict(4, reason=mark), failed_review(4, mark)),
    ], filtered_events=[{"film_id": 9, "name": mark, "categories": [mark]}])
    html = page(edition)
    assert "<x-mark" not in html
    assert html.count(escaped) == 25      # 每个字段都真的被渲染了，且都被转义了
    # 22 → 25（2026-10-04 视觉改版）：新增三处输出——速览里的片名、速览里的中文名、来源胶囊的 title 属性。
    glance = re.search(r'<section id="glance".*?</section>', html, re.S).group(0)
    assert glance.count(escaped) == 2 and f'title="{escaped}"' in html


def test_footer_shows_search_cost_when_the_edition_has_it(settings):
    edition = build_edition(settings, [recommended(1, "One")])
    edition["usage"] = {**edition["usage"], "estimated_token_cost_usd": 3.0,
                        "estimated_search_cost_usd": 0.5, "estimated_cost_usd": 3.5}
    html = page(edition)
    assert "费用估算 $3.50（token $3.00 + 搜索 $0.50" in html
    assert "不含搜索费" not in html
    assert "以账单为准" in html


def test_footer_of_an_older_edition_still_says_search_is_not_included(settings):
    edition = build_edition(settings, [recommended(1, "One")])
    assert "estimated_search_cost_usd" not in edition["usage"]
    assert "不含搜索费" in page(edition)


# ---- 视觉改版（2026-10-04）：速览、导航、推荐力度、分类色 ----

def test_glance_lists_must_and_ok_films_with_anchors(mixed):
    html = page(mixed)
    glance = re.search(r'<section id="glance".*?</section>', html, re.S).group(0)
    assert 'href="#film-1"' in glance and 'href="#film-2"' in glance
    assert "Must One" in glance and "Ok Two" in glance
    assert "Card Skip" not in glance and "Triage Skip" not in glance and "Broken Five" not in glance
    assert glance.index("Must One") < glance.index("Ok Two")          # 与正文同序：重点推荐在前
    assert 'id="film-1"' in card_html(html, 1)
    assert "data-film" not in glance                                   # 每部片的 data-film 在整页只能出现一次


def test_glance_shows_when_and_urgency(settings):
    candidate = {"is_event": True, "status": "coming_soon", "release_date": "2026-10-04",
                 "weeks_in_release": None, "gta_dates": ["2026-10-04", "2026-10-06"]}
    html = page(build_edition(settings, [recommended(1, "Ninja Scroll 4K", candidate, tier="must")]))
    glance = re.search(r'<section id="glance".*?</section>', html, re.S).group(0)
    assert "限定放映：10月4日、10月6日" in glance


def test_glance_absent_when_nothing_is_recommended(settings):
    html = page(build_edition(settings, [skipped(1, "A")]))
    assert 'id="glance"' not in html


def test_glance_escapes_titles(settings):
    html = page(build_edition(settings, [recommended(1, "<b>Bold</b> Title")]))
    glance = re.search(r'<section id="glance".*?</section>', html, re.S).group(0)
    assert "<b>Bold</b>" not in glance and "&lt;b&gt;Bold&lt;/b&gt; Title" in glance


def test_jump_nav_only_links_to_sections_that_exist(settings, mixed):
    html = page(mixed)
    nav = re.search(r'<nav class="jump".*?</nav>', html, re.S).group(0)
    for anchor in ("#must", "#ok", "#skip"):
        assert f'href="{anchor}"' in nav
        assert f'id="{anchor[1:]}"' in html
    only_ok = page(build_edition(settings, [recommended(1, "A", tier="ok")]))
    nav = re.search(r'<nav class="jump".*?</nav>', only_ok, re.S).group(0)
    assert 'href="#must"' not in nav and 'href="#skip"' not in nav
    assert 'href="#ok"' in nav


def test_hero_shows_counts(mixed):
    hero = re.search(r"<header.*?</header>", page(mixed), re.S).group(0)
    counts = mixed["counts"]
    for key, label in (("must", "重点推荐"), ("ok", "可以看"), ("skip", "跳过")):
        assert re.search(rf'<b>{counts[key]}</b>\s*{label}', hero), (key, label)


def test_strength_meter_matches_the_card(settings):
    html = page(build_edition(settings, [recommended(1, "A", strength=4, tier="must")]))
    card = card_html(html, 1)
    assert 'aria-label="推荐力度 4/5"' in card
    assert card.count('<i class="on"></i>') == 4 and card.count("<i></i>") == 1


def test_card_carries_its_category_for_styling(settings):
    html = page(build_edition(settings, [recommended(1, "A", category="horror")]))
    assert 'data-cat="horror"' in card_html(html, 1)


def test_every_category_has_a_colour():
    from film_radar.render import STYLE
    for category in CATEGORY_LABELS:
        assert f'[data-cat="{category}"]' in STYLE, category


def test_cta_and_chips_replace_the_link_wall(settings):
    edition = build_edition(settings, [recommended(1, "A", tier="must", scores=[{"name": "Metacritic", "value": "81", "source_url": SRC}],
                                                   sources=[{"title": "影评", "url": SRC}])])
    card = card_html(page(edition), 1)
    assert 'class="buy" href="https://www.cineplex.com/movie/film-1"' in card
    assert card.count("Cineplex 页面与购票") == 1
    assert 'class="chips"' in card


def test_page_is_light_only_and_keeps_its_accessibility_hooks():
    """用户嫌黑底对比度太高（他的系统是暗色，页面曾经会整页变黑）：页面始终是浅色，不跟随系统暗色。"""
    from film_radar.render import STYLE
    assert "prefers-color-scheme" not in STYLE
    assert re.search(r"^\s*:root\{color-scheme:light;", STYLE) and "light dark" not in STYLE
    assert "rgba(255,255,255" not in STYLE                       # 深底上用的半透明白，浅色页面上看不见
    assert "prefers-reduced-motion" in STYLE
    assert ":focus-visible" in STYLE
    assert "[hidden]{display:none!important}" in STYLE.replace(" ", "")      # 过期提示靠 hidden 属性，别被 display 盖掉


def _resolve(value):
    value = value.strip()
    token = re.fullmatch(r"var\(--([a-z-]+)\)", value)
    return SCOPES["light"][token.group(1)] if token else value


def test_every_large_surface_is_light(mixed):
    """顶部英雄区、页面、吸顶导航、卡片、速览：底色亮度都要够高，不能再出现大块的黑。"""
    rules = {}
    for selector, body in _css_rules():
        rules.setdefault(selector.strip(), body)
    for selector in ("body", ".hero", ".jump", ".film", ".glance"):
        found = re.search(r"(?<![-\w])background:([^;}]+)", rules[selector])
        assert found, selector
        colour = _resolve(found.group(1))
        assert colour.startswith("#"), (selector, colour)
        assert _luminance(colour) >= 0.6, (selector, colour)
    assert '<meta name="color-scheme" content="light">' in page(mixed)


def test_style_has_no_tiny_text():
    from film_radar.render import STYLE
    sizes = [float(s) for s in re.findall(r"font-size:\s*([\d.]+)px", STYLE)]
    sizes += [float(s) for s in re.findall(r"(?<![-\w])font:[^;}]*?(?<![\d.])(\d+(?:\.\d+)?)px", STYLE)]       # font: 简写里的第一个 px 值
    sizes += [float(s) for s in re.findall(r"font(?:-size)?:[^;}]*?clamp\((\d+(?:\.\d+)?)px", STYLE)]           # clamp 的最小值
    assert len(sizes) >= 20 and min(sizes) >= 11.5, sorted(sizes)[:3]
    # 相对单位（em）的字号要折算：序号取标题字号的一半，标题最小 26px，所以不小于 13px
    assert re.search(r"h2::before\{[^}]*font-size:\.5em", STYLE) and re.search(r"font:800 clamp\(26px", STYLE)


# ---- 紧凑卡片的影院名单（2026-10-04 视觉改版）----

MANY = [f"Cineplex Cinemas Place {i}" for i in range(1, 7)]


def test_compact_card_with_many_theatres_shows_a_count_and_folds_the_list(settings):
    html = page(build_edition(settings, [recommended(1, "A", {"gta_theatres": MANY}, tier="ok")]))
    card = card_html(html, 1)
    before, after = card.split("<details>", 1)
    assert "6 家影院" in before
    assert "Place 1" not in before                     # 名单不在首屏
    assert "、".join(MANY) in after                    # 但完整名单一个字不少地在展开里


def test_compact_card_with_few_theatres_lists_them_inline(settings):
    few = MANY[:4]
    card = card_html(page(build_edition(settings, [recommended(1, "A", {"gta_theatres": few}, tier="ok")])), 1)
    before = card.split("<details>", 1)[0]
    assert "、".join(few) in before and "家影院" not in before


def test_feature_card_always_lists_every_theatre(settings):
    card = card_html(page(build_edition(settings, [recommended(1, "A", {"gta_theatres": MANY}, tier="must")])), 1)
    assert "、".join(MANY) in card and "<details>" not in card and "6 家影院" not in card


def test_missing_poster_placeholder_has_an_inline_glyph():
    """没有海报的片不能露出一块空白色块：占位块自带内联 SVG 图标，不依赖任何外部资源。"""
    from film_radar.render import STYLE
    poster_rule = re.search(r"\.poster\{[^}]*\}", STYLE).group(0)
    assert "data:image/svg+xml" in poster_rule and "http://www.w3.org" in poster_rule
    assert "url(http" not in STYLE and "@import" not in STYLE      # 样式里没有外部请求


# ---- 瑞士风配色与「我已经看过」（2026-10-04）----

import json as _json
import shutil as _shutil
import subprocess as _subprocess
import tempfile as _tempfile
import threading as _threading
from functools import partial as _partial
from http.server import SimpleHTTPRequestHandler as _Handler, ThreadingHTTPServer as _Server
from pathlib import Path as _Path

import pytest as _pytest

from film_radar.render import SEEN_SCRIPT, STYLE as _STYLE

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BRAND = ("red", "blue", "yellow", "green")


def _scope(pattern):
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6}|\d+%)(?=[;}\s]|$)", re.search(pattern, _STYLE, re.S).group(1)))


SCOPES = {"light": _scope(r"^\s*:root\{([^}]*)\}")}       # 页面始终是浅色：不跟随系统暗色，英雄区也是浅色（用户嫌黑底对比度太高）


def _luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@_pytest.mark.parametrize("scope", sorted(SCOPES))
@_pytest.mark.parametrize("colour", BRAND)
def test_every_brand_colour_is_readable_with_its_text_colour(scope, colour):
    """品牌色做底色时，文字必须用配套的 --on-* 色，且对比度达到 WCAG AA（4.5）。"""
    tokens = SCOPES[scope]
    assert colour in tokens and f"on-{colour}" in tokens, (scope, colour)
    assert _contrast(tokens[colour], tokens[f"on-{colour}"]) >= 4.5, (scope, colour)


@_pytest.mark.parametrize("scope", ["light"])
def test_body_text_and_links_are_readable(scope):
    t = SCOPES[scope]
    assert _contrast(t["ink"], t["bg"]) >= 7 and _contrast(t["ink"], t["surface"]) >= 7
    assert _contrast(t["mute"], t["surface"]) >= 4.5 and _contrast(t["mute"], t["bg"]) >= 4.5
    assert _contrast(t["link"], t["surface"]) >= 4.5 and _contrast(t["link"], t["bg"]) >= 4.5


def test_hero_has_geometric_art_and_coloured_stat_tiles(mixed):
    hero = re.search(r"<header.*?</header>", page(mixed), re.S).group(0)
    assert hero.count('class="art"') == 1 and 'aria-hidden="true"' in hero
    for kind in ("must", "ok", "skip"):
        assert f'class="stat {kind}"' in hero, kind


def test_urgency_badges_say_which_kind_they_are(settings):
    candidate = {"is_event": True, "status": "now_playing", "weeks_in_release": 4, "hurry": True,
                 "gta_dates": ["2026-10-04"]}
    card = card_html(page(build_edition(settings, [recommended(1, "A", candidate)])), 1)
    assert 'class="badge warn event">限定放映：10月4日</span>' in card
    assert 'class="badge warn hurry">抓紧（推断）</span>' in card


# ---- 我已经看过：标记 ----

def test_every_recommended_card_has_one_hidden_seen_button(mixed):
    html = page(mixed)
    for film_id in (1, 2):                      # mixed 里 1 是重点推荐、2 是可以看
        card = card_html(html, film_id)
        button = re.findall(rf'<button[^>]*data-seen="{film_id}"[^>]*>[^<]*</button>', card)
        assert len(button) == 1, film_id
        assert "hidden" in button[0] and 'aria-pressed="false"' in button[0] and "我已经看过" in button[0]
        assert 'aria-label="我已经看过"' in button[0]          # 无障碍名称固定，状态只由 aria-pressed 表达
    assert html.count("data-seen=") == 2                         # 跳过、未能评估的片没有这个按钮


def test_glance_rows_carry_the_film_id_for_seen_state(mixed):
    glance = re.search(r'<section id="glance".*?</section>', page(mixed), re.S).group(0)
    assert 'data-fid="1"' in glance and 'data-fid="2"' in glance and "data-film" not in glance


def test_nav_has_a_hidden_hide_seen_chip(mixed):
    nav = re.search(r'<nav class="jump".*?</nav>', page(mixed), re.S).group(0)
    assert re.search(r'<button type="button" class="chip" data-hide-seen aria-label="隐藏已看过（0 部）" aria-pressed="false" hidden>', nav)


def test_seen_script_is_on_every_page_but_the_stale_script_only_on_the_latest(mixed):
    latest, archived = page(mixed), page(mixed, latest=False)
    for html in (latest, archived):
        assert "film-radar:seen:v1" in html
    assert 'getElementById("stale")' in latest and 'getElementById("stale")' not in archived
    assert 'id="stale"' not in archived


def test_seen_script_is_static_and_carries_no_page_data(settings):
    def script_of(edition):
        return re.search(r"<script>(\(function\(\)\{var KEY=.*?)</script>", page(edition), re.S).group(1)
    one = build_edition(settings, [recommended(1, "First Title")])
    two = build_edition(settings, [recommended(2, "Another <b>Title</b>")])
    assert script_of(one) == script_of(two) == SEEN_SCRIPT
    assert "First Title" not in SEEN_SCRIPT


@_pytest.mark.skipif(not _shutil.which("node"), reason="需要 node 做语法检查")
def test_seen_script_is_valid_javascript(tmp_path):
    path = tmp_path / "seen.js"
    path.write_text(SEEN_SCRIPT, encoding="utf-8")
    result = _subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ---- 我已经看过：真实浏览器里的行为 ----

def _run_in_chrome(html, before="", after=""):
    """用 headless Chrome 打开页面。before 插在 <head> 里、先于页面脚本执行；after 插在 </body> 前、后于页面脚本执行。
    after 里把结果写进 document.title（以 RESULT: 开头的 JSON），这里读回来。走本机 http 服务而不是 file://，和线上同源规则一致。
    Chrome 的 --dump-dom 打印完 DOM 之后不会自己退出（实测跑满超时），所以读到 </html> 就杀掉整个进程组。"""
    import os, signal, time
    with _tempfile.TemporaryDirectory() as directory:
        root = _Path(directory)
        (root / "index.html").write_text(
            html.replace("</head>", f"<script>{before}</script></head>").replace("</body>", f"<script>{after}</script></body>"),
            encoding="utf-8")
        server = _Server(("127.0.0.1", 0), _partial(_Handler, directory=str(root)))
        server.RequestHandlerClass.log_message = lambda *args: None
        _threading.Thread(target=server.serve_forever, daemon=True).start()
        command = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={root / 'profile'}",
                   "--virtual-time-budget=4000", "--dump-dom", f"http://127.0.0.1:{server.server_address[1]}/index.html"]
        process = _subprocess.Popen(command, stdout=_subprocess.PIPE, stderr=_subprocess.DEVNULL, text=True, start_new_session=True)
        output, deadline = [], time.time() + 45
        try:
            for line in process.stdout:
                output.append(line)
                if "</html>" in line or time.time() > deadline:
                    break
        finally:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            server.shutdown()
    dumped = "".join(output)
    found = re.search(r"<title>RESULT:(.*?)</title>", dumped, re.S)
    assert found, dumped[-600:]
    import html as _html
    return _json.loads(_html.unescape(found.group(1)))


browser = _pytest.mark.skipif(not _Path(CHROME).exists(), reason="需要本机 Chrome 做浏览器端到端测试")

PROBE = """
var q=function(s){return document.querySelector(s)};
var state=function(id){var b=q('[data-seen="'+id+'"]');var c=document.getElementById("film-"+id);var g=q('[data-fid="'+id+'"]');
 return {pressed:b.getAttribute("aria-pressed"),label:b.textContent,hidden:b.hidden,card:c.classList.contains("is-seen"),row:g.classList.contains("is-seen")}};
"""


@browser
def test_browser_a_seen_film_is_restored_from_storage_on_load(mixed):
    result = _run_in_chrome(
        page(mixed),
        before='localStorage.setItem("film-radar:seen:v1", JSON.stringify({"1": 1700000000000}));',
        after=PROBE + 'var chip=q("[data-hide-seen]");document.title="RESULT:"+JSON.stringify({one:state(1),two:state(2),'
                      'chipHidden:chip.hidden,chipCount:chip.querySelector("span.n").textContent});')
    assert result["one"] == {"pressed": "true", "label": "✓ 已看过", "hidden": False, "card": True, "row": True}
    assert result["two"] == {"pressed": "false", "label": "我已经看过", "hidden": False, "card": False, "row": False}
    assert result["chipHidden"] is False and result["chipCount"] == "1"


@browser
def test_browser_clicking_toggles_and_persists(mixed):
    result = _run_in_chrome(
        page(mixed),
        after=PROBE + 'q(\'[data-seen="2"]\').click();var afterMark=state(2);var stored=JSON.parse(localStorage.getItem("film-radar:seen:v1"));'
                      'q(\'[data-seen="2"]\').click();var afterUndo=state(2);var storedAfterUndo=localStorage.getItem("film-radar:seen:v1");'
                      'document.title="RESULT:"+JSON.stringify({afterMark:afterMark,keys:Object.keys(stored),'
                      'afterUndo:afterUndo,storedAfterUndo:storedAfterUndo,chipHidden:q("[data-hide-seen]").hidden});')
    assert result["afterMark"]["pressed"] == "true" and result["afterMark"]["card"] and result["afterMark"]["row"]
    assert result["keys"] == ["2"]
    assert result["afterUndo"]["pressed"] == "false" and not result["afterUndo"]["card"]
    assert result["storedAfterUndo"] == "{}" and result["chipHidden"] is True


@browser
def test_browser_corrupted_storage_does_not_break_the_page(mixed):
    result = _run_in_chrome(
        page(mixed),
        before='localStorage.setItem("film-radar:seen:v1", "{not json");',
        after=PROBE + 'var before=state(1);q(\'[data-seen="1"]\').click();var after=state(1);'
                      'document.title="RESULT:"+JSON.stringify({before:before,after:after,stored:localStorage.getItem("film-radar:seen:v1")});')
    assert result["before"]["hidden"] is False and result["before"]["pressed"] == "false"      # 坏数据当作「没看过」，按钮照常出现
    assert result["after"]["pressed"] == "true"
    assert list(_json.loads(result["stored"])) == ["1"]                                           # 点击后写回合法 JSON


@browser
def test_browser_hide_seen_chip_hides_and_remembers(mixed):
    result = _run_in_chrome(
        page(mixed),
        before='localStorage.setItem("film-radar:seen:v1", JSON.stringify({"1": 1}));',
        after=PROBE + 'var chip=q("[data-hide-seen]");chip.click();var hiddenNow=getComputedStyle(document.getElementById("film-1")).display;'
                      'var rowHidden=getComputedStyle(q(\'[data-fid="1"]\')).display;var other=getComputedStyle(document.getElementById("film-2")).display;'
                      'var pressed=chip.getAttribute("aria-pressed");var label=chip.querySelector(".lbl").textContent;var remembered=localStorage.getItem("film-radar:hide-seen:v1");'
                      'chip.click();document.title="RESULT:"+JSON.stringify({hiddenNow:hiddenNow,rowHidden:rowHidden,other:other,pressed:pressed,'
                      'label:label,remembered:remembered,shownAgain:getComputedStyle(document.getElementById("film-1")).display});')
    assert result["hiddenNow"] == "none" and result["rowHidden"] == "none" and result["other"] != "none"
    assert result["pressed"] == "true" and result["label"] == "显示已看过" and result["remembered"] == "1"
    assert result["shownAgain"] != "none"


@browser
def test_browser_storage_failure_still_lets_you_mark_for_this_visit(mixed):
    result = _run_in_chrome(
        page(mixed),
        before='Object.defineProperty(window,"localStorage",{get:function(){throw new Error("denied")}});',
        after=PROBE + 'q(\'[data-seen="1"]\').click();document.title="RESULT:"+JSON.stringify({one:state(1)});')
    assert result["one"]["pressed"] == "true" and result["one"]["card"] is True



# ---- 评审后加固（2026-10-04）：样式字符串、对比度、触控目标 ----

def test_css_escapes_survive_python_string_handling():
    """CSS 里的 \2713 / \2212 写在普通 Python 字符串里会被当成八进制（\271 → "¹"，\221 → 控制字符）：
    已看过的角标曾经渲染成「¹3 已看过」，展开后的 summary 符号曾经是「2」。"""
    assert not [c for c in _STYLE if 0x80 <= ord(c) <= 0xBF]
    assert "\\2713" in _STYLE and "\\2212" in _STYLE


def _hsl(h, s, l):
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return "#%02x%02x%02x" % tuple(round(v * 255) for v in (r, g, b))


@_pytest.mark.parametrize("scheme", ["light"])
def test_category_colours_are_readable_on_every_background_they_sit_on(scheme):
    """七个类别色相：类别色文字压在卡片底色和自己的淡底上，链接压在评分胶囊的淡底上，都要 >= 4.5。
    这个测试是评审后补的：亮色下政治历史 / 中国电影 / 犯罪不达标，暗色下评分胶囊里的链接不达标，之前的测试都没覆盖到。"""
    from film_radar.render import HUES
    t = SCOPES[scheme]
    s, l, tint = int(t["cat-s"][:-1]), int(t["cat-l"][:-1]), int(t["catbg-l"][:-1])
    assert "hsl(var(--h) 45% var(--catbg-l))" in _STYLE            # 测试按这个公式还原淡底
    for category, h in HUES.items():
        cat, wash = _hsl(h, s, l), _hsl(h, 45, tint)
        assert _contrast(cat, t["surface"]) >= 4.5, (scheme, category, "类别色文字 / 卡片底色")
        assert _contrast(cat, wash) >= 4.5, (scheme, category, "类别色文字 / 淡底")
        assert _contrast(t["link"], wash) >= 4.5, (scheme, category, "链接 / 淡底")
        assert _contrast(t["ink"], wash) >= 7, (scheme, category, "正文 / 淡底")


@_pytest.mark.parametrize("scheme", ["light"])
def test_red_is_readable_when_it_is_used_as_text(scheme):
    t = SCOPES[scheme]
    assert _contrast(t["red-ink"], t["bg"]) >= 4.5 and _contrast(t["red-ink"], t["surface"]) >= 4.5
    assert re.search(r"h2::before\{[^}]*color:var\(--red-ink\)", _STYLE)       # 章节序号用文字红，不用底色红


def _css_rules():
    flat = re.sub(r"@media[^{]*\{", "", _STYLE)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", flat)


def test_brand_backgrounds_always_come_with_their_text_colour():
    """令牌的对比度达标，不等于规则用对了文字色。把 .stat.must 的字改成白色，旧的令牌测试照样全绿——所以直接查规则。"""
    offenders = []
    for selector, body in _css_rules():
        if ".art" in selector or 'content:""' in body:                 # 纯装饰的色块，里面没有文字
            continue
        for colour in BRAND:
            if re.search(rf"(?<![-\w])background:var\(--{colour}\)\s*(;|$)", body) and f"color:var(--on-{colour})" not in body.replace("border-color", ""):
                offenders.append((selector.strip(), colour))
    assert not offenders, offenders
    for selector, body in _css_rules():                                  # 品牌底色不能直接拿来当文字色（红用 --red-ink，链接用 --link）
        assert not re.search(r"(?<![-\w])color:var\(--(red|blue|green)\)", body), selector.strip()


def test_touch_targets_scroll_margin_and_nav_scrollbar():
    rules = dict((s.strip(), b) for s, b in _css_rules())
    for selector in (".seen", ".buy", ".jump a,.chip"):
        assert "min-height:44px" in rules[selector], selector
    assert "scroll-margin-top:76px" in rules["[id]"]                      # 吸顶导航不能盖住锚点跳转的目标
    assert "scrollbar-width:none" in rules[".jump .wrap"]


def test_seen_state_is_not_expressed_with_a_category_hue():
    """已看过的状态不用绿色圆点/绿色边条：绿色和「政治历史」「犯罪」两个类别撞色，分不出来。靠中性色、空心圆点和删除线。"""
    for selector, body in _css_rules():
        if "is-seen" in selector and ("::before" in selector or ".g-dot" in selector):
            assert "var(--green)" not in body, selector.strip()


def test_page_has_a_polite_live_region_for_seen_announcements(mixed):
    html = page(mixed)
    assert html.count('<div class="sr-only" role="status" aria-live="polite" data-live></div>') == 1 and "sr-only" in _STYLE


# ---- 评审后加固：浏览器里的行为 ----

QUOTA = 'Storage.prototype.setItem=function(){throw new DOMException("full","QuotaExceededError")};'
DENIED = 'Object.defineProperty(window,"localStorage",{get:function(){throw new Error("denied")}});'
SEED = lambda o, hide=None: ('localStorage.setItem("film-radar:seen:v1", JSON.stringify(%s));' % _json.dumps(o)
                             + ('localStorage.setItem("film-radar:hide-seen:v1","%s");' % hide if hide is not None else ""))


@browser
def test_browser_marking_works_when_only_writing_fails(mixed):
    """配额满了或旧版 Safari 无痕：getItem 正常、setItem 抛错。之前点了没反应，因为读回来的永远是旧值。"""
    result = _run_in_chrome(page(mixed), before=QUOTA, after=PROBE +
        'q(\'[data-seen="2"]\').click();var a=state(2);q(\'[data-seen="2"]\').click();var b=state(2);'
        'document.title="RESULT:"+JSON.stringify({a:a,b:b});')
    assert result["a"]["pressed"] == "true" and result["a"]["card"] and result["a"]["row"]
    assert result["b"]["pressed"] == "false" and not result["b"]["card"]


@browser
def test_browser_hide_chip_works_when_storage_is_unavailable(mixed):
    result = _run_in_chrome(page(mixed), before=DENIED, after=PROBE +
        'q(\'[data-seen="1"]\').click();var chip=q("[data-hide-seen]");chip.click();'
        'document.title="RESULT:"+JSON.stringify({pressed:chip.getAttribute("aria-pressed"),root:document.documentElement.classList.contains("hide-seen"),'
        'card:getComputedStyle(document.getElementById("film-1")).display});')
    assert result == {"pressed": "true", "root": True, "card": "none"}


@browser
def test_browser_a_leftover_hide_preference_does_not_swallow_the_first_mark(mixed):
    """上次在别的页面打开了「隐藏已看过」，这一页还没有任何已看过的片：标记第一部时它不能立刻消失。"""
    result = _run_in_chrome(page(mixed), before='localStorage.setItem("film-radar:hide-seen:v1","1");', after=PROBE +
        'q(\'[data-seen="2"]\').click();document.title="RESULT:"+JSON.stringify({card:getComputedStyle(document.getElementById("film-2")).display,'
        'pressed:state(2).pressed,hide:localStorage.getItem("film-radar:hide-seen:v1")});')
    assert result["card"] != "none" and result["pressed"] == "true" and result["hide"] == "0"


@browser
def test_browser_marking_in_hide_mode_keeps_keyboard_focus(mixed):
    result = _run_in_chrome(page(mixed), before=SEED({"1": 1}, hide="1"), after=PROBE +
        'var b=q(\'[data-seen="2"]\');b.focus();b.click();'
        'document.title="RESULT:"+JSON.stringify({onChip:document.activeElement===q("[data-hide-seen]"),'
        'gone:getComputedStyle(document.getElementById("film-2")).display});')
    assert result == {"onChip": True, "gone": "none"}              # 卡片消失了，焦点落在「显示已看过」上，没有掉到 body


@browser
def test_browser_changes_are_announced_politely(mixed):
    result = _run_in_chrome(page(mixed), after=PROBE +
        'q(\'[data-seen="1"]\').click();var a=q("[data-live]").textContent;q(\'[data-seen="1"]\').click();var b=q("[data-live]").textContent;'
        'document.title="RESULT:"+JSON.stringify({a:a,b:b});')
    assert "Must One" in result["a"] and "标为已看过" in result["a"]
    assert "Must One" in result["b"] and "撤销" in result["b"]


@browser
def test_browser_state_is_carried_by_aria_pressed_not_by_a_changing_name(mixed):
    result = _run_in_chrome(page(mixed), before=SEED({"1": 1}), after=
        'var q=function(s){return document.querySelector(s)};var b=q(\'[data-seen="1"]\'),c=q("[data-hide-seen]");'
        'document.title="RESULT:"+JSON.stringify({bLabel:b.getAttribute("aria-label"),bText:b.textContent,bPressed:b.getAttribute("aria-pressed"),'
        'cLabel:c.getAttribute("aria-label"),cPressed:c.getAttribute("aria-pressed")});c.click();')
    assert result == {"bLabel": "我已经看过", "bText": "✓ 已看过", "bPressed": "true", "cLabel": "隐藏已看过（1 部）", "cPressed": "false"}


@browser
def test_browser_storage_clear_and_bfcache_restore_resync_the_page(mixed):
    result = _run_in_chrome(page(mixed), before=SEED({"1": 1}), after=PROBE +
        'localStorage.clear();window.dispatchEvent(new StorageEvent("storage",{key:null}));var cleared=state(1).pressed;'
        'localStorage.setItem("film-radar:seen:v1",JSON.stringify({"2":1}));window.dispatchEvent(new PageTransitionEvent("pageshow",{persisted:true}));'
        'document.title="RESULT:"+JSON.stringify({cleared:cleared,restored:state(2).pressed});')
    assert result == {"cleared": "false", "restored": "true"}


@browser
def test_browser_pseudo_element_text_renders_what_the_css_says(mixed):
    result = _run_in_chrome(page(mixed), before=SEED({"1": 1}), after=
        'var q=function(s){return document.querySelector(s)};var card=document.getElementById("film-1");'
        'var det=document.querySelector("#film-2 details");det.open=true;'
        'var probe=document.createElement("i");probe.style.color="var(--green)";document.body.appendChild(probe);'
        'document.title="RESULT:"+JSON.stringify({stamp:getComputedStyle(card.querySelector(".eyebrow"),"::after").content,'
        'minus:getComputedStyle(det.querySelector("summary"),"::after").content,numContent:getComputedStyle(document.querySelector("h2"),"::before").content,inc:getComputedStyle(document.querySelector("h2")).counterIncrement,reset:getComputedStyle(document.querySelector("main")).counterReset,'
        'pressedBg:getComputedStyle(q(\'[data-seen="1"]\')).backgroundColor===getComputedStyle(probe).color});')
    assert result["stamp"] == '"✓ 已看过"' and result["minus"] == '"−"' and result["numContent"] == "counter(sec, decimal-leading-zero)"
    assert result["inc"] == "sec 1" and result["reset"] == "sec 0"             # 章节序号：main 归零、每个 h2 加一'
    assert result["pressedBg"] is True                                     # 已看过的按钮底色就是 --green
