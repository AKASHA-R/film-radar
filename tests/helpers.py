"""测试共用：夹具读取与假的 HTTP 会话。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def fixture_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def fixture_json(*parts: str):
    return json.loads(fixture_text(*parts))


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """按完整 URL 查表返回响应。表里的值可以是 FakeResponse，也可以是 (url, headers) -> FakeResponse 的函数。

    没登记的 `_next/static` 脚本返回空脚本，其余没登记的 URL 返回 404。
    """

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None):
        headers = dict(headers or {})
        self.calls.append((url, headers))
        if url in self.routes:
            route = self.routes[url]
            return route(url, headers) if callable(route) else route
        if "/_next/static/" in url:
            return FakeResponse(200, "")
        return FakeResponse(404, "")


# ---- 任务 6 起用到的构造函数 ----

from film_radar.llm import LLMResult  # noqa: E402


def make_candidate(film_id: int, title: str | None = None, **overrides) -> dict:
    """构造一个候选。键必须与 candidates.build_candidates 的产出一致（test_helpers_shape.py 守着）。"""
    title = title or f"Film {film_id}"
    candidate = {
        "film_id": film_id,
        "title": title,
        "film_url": f"film-{film_id}",
        "versions": [{"film_id": film_id, "name": title, "language": "English", "subtitle": ""}],
        "status": "now_playing",
        "is_event": False,
        "release_date": "2026-10-02",
        "runtime": 120,
        "genres": ["Drama"],
        "film_categories": ["Drama", "Film Presentation"],
        "distributor": "ELEVATION PICTURES CORP.",
        "poster_url": "https://mediafiles.cineplex.com/poster.jpg",
        "detail_url": f"https://www.cineplex.com/movie/film-{film_id}",
        "gta_theatres": ["Scotiabank Theatre Toronto"],
        "gta_dates": ["2026-10-04"],
        "weeks_in_release": 1,
        "hurry": False,
        "rating_on": None,
        "synopsis": "A synopsis.",
        "director": "A Director",
        "starring": "An Actor",
        "details_missing": False,
    }
    candidate.update(overrides)
    return candidate


def llm_reply(obj, stop: str = "end_turn", blocks=None, tokens=(100, 50)) -> LLMResult:
    """把一个对象包成 LLMResult。obj 是字符串时原样当作文本，否则序列化成 JSON。"""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return LLMResult(stop_reason=stop, text=text, blocks=list(blocks or []),
                     input_tokens=tokens[0], output_tokens=tokens[1])


class FakeCaller:
    """按顺序吐出预设回复的假 caller。回复是异常实例时抛出它。"""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.replies:
            raise AssertionError("FakeCaller 的预设回复用完了：被多调用了一次")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


# ---- 任务 7 起用到 ----

def make_card(**overrides) -> dict:
    """模型返回的一张合法卡片（白名单处理之前的样子）。"""
    card = {
        "tier": "must",
        "strength": 4,
        "category": "scifi",
        "one_liner": "一句话定位。",
        "premise": "讲什么。",
        "why_for_you": "为什么对胃口。",
        "reception": "口碑如何。",
        "background": "创作背景。",
        "caveats": "可能踩雷。",
        "skip_reason": None,
        "evidence": "ample",
        "title_zh": None,
        "title_zh_source": None,
        "scores": [],
        "sources": [{"title": "影评", "url": "https://example.com/review"}],
    }
    card.update(overrides)
    return card


# ---- 任务 8 起用到 ----

from datetime import date as _date  # noqa: E402

USAGE = {"calls": 3, "input_tokens": 1000, "output_tokens": 500, "searches": 4,
         "estimated_token_cost_usd": 0.014}


def make_verdict(film_id: int, keep: bool = True, rank=1, category: str = "scifi", reason: str = "粗筛理由") -> dict:
    return {"film_id": film_id, "keep": keep, "rank": rank if keep else None, "category": category, "reason": reason}


def ok_review(film_id: int, **card_overrides) -> dict:
    card = make_card(**card_overrides)
    card["film_id"] = film_id
    card.setdefault("sources_dropped", 0)
    return {"film_id": film_id, "ok": True, "card": card, "error": None, "searches": 2}


def failed_review(film_id: int, error: str = "调查阶段 stop_reason 为 max_tokens") -> dict:
    return {"film_id": film_id, "ok": False, "card": None, "error": error, "searches": 0}


def recommended(film_id: int, title: str, candidate: dict | None = None, **card_overrides):
    """一部入围且精评成功的片：返回 (候选, 判定, 精评结果)。"""
    return (make_candidate(film_id, title, **(candidate or {})), make_verdict(film_id), ok_review(film_id, **card_overrides))


def skipped(film_id: int, title: str, reason: str = "不对口味"):
    """一部粗筛就没入围的片。"""
    return (make_candidate(film_id, title), make_verdict(film_id, keep=False, reason=reason), None)


def broken(film_id: int, title: str, error: str = "调查阶段 stop_reason 为 max_tokens"):
    """一部入围但精评失败的片。"""
    return (make_candidate(film_id, title), make_verdict(film_id), failed_review(film_id, error))


def build_edition(settings, entries, previous=None, filtered_events=(), orphan_ids=(),
                  run_date=_date(2026, 10, 8), generated_at="2026-10-08T07:05:00-04:00") -> dict:
    from film_radar.assemble import assemble

    return assemble(
        candidates=[e[0] for e in entries],
        verdicts=[e[1] for e in entries],
        reviews=[e[2] for e in entries if e[2] is not None],
        previous=previous,
        filtered_events=list(filtered_events),
        orphan_ids=list(orphan_ids),
        usage=dict(USAGE),
        run_date=run_date,
        generated_at=generated_at,
        settings=settings,
    )


# ---- 「已看过」同步用到 ----

def task_issue(edition_id: str, *rows) -> str:
    """一个最小的 edition Issue 正文。rows 是 (film_id, 当前勾选, bot)。"""
    from film_radar.watched import edition_marker, task_line

    lines = [edition_marker(edition_id), "", "第 N 期重点推荐：", ""]
    for film_id, checked, bot in rows:
        line = task_line(f"**Film {film_id}** · 在映第 1 周", film_id, bot)
        if checked != bot:
            line = f"- [{'x' if checked else ' '}]" + line[5:]
        lines.append(line)
    return "\n".join(lines) + "\n\ncc @AKASHA-R\n"


def toggle(body: str, film_id: int) -> str:
    """模拟用户在网页上点一下某一行的勾选框。"""
    rows = body.split("\n")
    for i, row in enumerate(rows):
        if f"<!-- film:{film_id} " in row:
            rows[i] = ("- [x]" if row.startswith("- [ ]") else "- [ ]") + row[5:]
    return "\n".join(rows)


class FakeGitHub:
    """github.GitHubClient 的替身：Issue 正文存在内存里（{编号: 正文}）。方法与真客户端一致（test_github.py 守着）。

    fail_updates：接下来这么多次 update_body 抛 GitHubError。before_update(number, body)：真正写入前回调，
    用来断言「改写前已经写好备份」这类顺序。"""

    def __init__(self, bodies=None, fail_updates=0, before_update=None):
        self.bodies = dict(bodies or {})
        self.fail_updates = fail_updates
        self.before_update = before_update
        self.updates: list[tuple[int, str]] = []
        self.calls: list = []

    def edition_issues(self):
        from film_radar.watched import Issue

        self.calls.append("edition_issues")
        return [Issue(number, body) for number, body in sorted(self.bodies.items())]

    def issue_body(self, number):
        self.calls.append(("issue_body", number))
        return self.bodies[number]

    def update_body(self, number, body):
        from film_radar.github import GitHubError

        self.calls.append(("update_body", number))
        if self.fail_updates:
            self.fail_updates -= 1
            raise GitHubError(f"PATCH issues/{number}: HTTP 502")
        if self.before_update:
            self.before_update(number, body)
        self.updates.append((number, body))
        self.bodies[number] = body
