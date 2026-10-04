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
    match = re.search(rf'<article class="film" data-film="{film_id}">.*?</article>', html, re.S)
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
    assert "<script>" not in archived


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
    assert html.count(escaped) == 22      # 每个字段都真的被渲染了，且都被转义了
