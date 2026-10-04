"""口味档案是喂给模型的提示词输入，类别要和代码里的枚举对得上：
档案里没写的类别，模型不知道用户喜欢，枚举里没有的类别，模型填了也会被 schema 拒绝。"""
from film_radar.triage import CATEGORIES
from helpers import ROOT

HEADINGS = {
    "scifi": "科幻", "thriller": "惊悚", "political_historical": "政治、历史", "chinese": "中国电影",
    "horror": "恐怖", "japanese": "日本电影", "crime": "犯罪",
}
NUMERALS = "零一二三四五六七八九十"


def inside_categories():
    return [c for c in CATEGORIES if c != "outside"]


def profile():
    return (ROOT / "config" / "taste_profile.md").read_text(encoding="utf-8")


def test_every_category_has_a_numbered_section_in_order():
    inside = inside_categories()
    assert set(HEADINGS) == set(inside)
    text = profile()
    positions = []
    for n, key in enumerate(inside, 1):
        heading = f"## {n}. {HEADINGS[key]}"
        assert heading in text, f"口味档案里没有「{heading}」"
        positions.append(text.index(heading))
    assert positions == sorted(positions)


def test_intro_counts_the_categories():
    text = profile()
    assert f"下面{NUMERALS[len(inside_categories())]}类" in text
