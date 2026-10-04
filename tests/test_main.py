import json
import shutil
from dataclasses import replace
from datetime import date, timedelta

import pytest

from film_radar import main as main_module
from film_radar.cineplex import CineplexError
from film_radar.llm import LLMResult
from film_radar.main import (
    PipelineError, ReviewError, attach_details, check_sanity, collect, load_editions, main, previous_edition,
    run_pipeline, should_run, summarize_usage,
)
from film_radar.triage import TRIAGE_SCHEMA
from helpers import ROOT, build_edition, fixture_json, llm_reply, make_candidate, make_card, recommended

MOVIES = fixture_json("cineplex", "movies_v2.json")["items"]
_T = fixture_json("cineplex", "theatres.json")
THEATRES = _T["nearbyTheatres"] + _T["otherTheatres"]
RUN = date(2026, 10, 3)
SRC = "https://example.com/review"
TASTE = "口味档案"
DAY_ONE = [38459, 38401, 37885, 61994, 61995]
EXPECTED_CANDIDATES = [37885, 38401, 38459, 61994, 62103, 62106, 62154, 62163, 62181]


class FakeCineplex:
    def __init__(self, movies=None, showtimes=None, bookable=None, failing_details=()):
        self._movies = MOVIES if movies is None else movies
        self._showtimes = {(7130, date(2026, 10, 4)): DAY_ONE} if showtimes is None else showtimes
        self._bookable = {7130: [RUN + timedelta(days=n) for n in range(20)]} if bookable is None else bookable
        self._failing = set(failing_details)
        self.showtime_calls = []

    def movies(self):
        return self._movies

    def theatres(self, lat, lon):
        return THEATRES

    def bookable_dates(self, theatre_id):
        return self._bookable.get(theatre_id, [])

    def showtimes(self, theatre_id, day):
        self.showtime_calls.append((theatre_id, day))
        return self._showtimes.get((theatre_id, day), [])

    def movie_details(self, film_url):
        if film_url in self._failing:
            raise CineplexError(f"详情页 {film_url}: HTTP 500")
        return {"synopsis": f"Synopsis of {film_url}", "director": "D", "starring": "S"}


class ScriptedCaller:
    """按请求内容作答的假 caller：粗筛、调查、整理三种请求各有固定答法。"""

    def __init__(self, keep=(), fail_research=()):
        self.keep = set(keep)
        self.fail_research = set(fail_research)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        user = kwargs["user"]
        if kwargs.get("schema") is TRIAGE_SCHEMA:
            sent = json.loads(user.split("<candidates>")[1].split("</candidates>")[0])
            return llm_reply({"verdicts": [
                {"film_id": c["film_id"], "keep": c["film_id"] in self.keep,
                 "rank": 1 if c["film_id"] in self.keep else None, "category": "horror", "reason": "粗筛理由"}
                for c in sent
            ]})
        film_id = json.loads(user.split("<film>")[1].split("</film>")[0])["film_id"]
        if kwargs.get("tools"):
            if film_id in self.fail_research:
                return llm_reply("", stop="max_tokens")
            return llm_reply("调查笔记。", blocks=[
                {"type": "server_tool_use", "id": "s", "name": "web_search", "input": {"query": "q"}},
                {"type": "web_search_tool_result", "tool_use_id": "s", "content": [
                    {"type": "web_search_result", "url": SRC, "title": "t", "encrypted_content": "x", "page_age": None}]},
                {"type": "text", "text": "调查笔记。"},
            ])
        return llm_reply(make_card(tier="ok", sources=[{"title": "影评", "url": SRC}]))


def pipeline(settings, client=None, caller=None, previous=None):
    return run_pipeline(
        client=client or FakeCineplex(), caller=caller or ScriptedCaller(keep={61994, 38459}),
        settings=settings, taste=TASTE, run_date=RUN, previous=previous,
        generated_at="2026-10-03T07:05:00-04:00",
    )


# ---- 双周门控 ----

@pytest.mark.parametrize("day, expected", [
    (date(2026, 10, 8), True),     # 锚点当天
    (date(2026, 10, 15), False),   # 隔周
    (date(2026, 10, 22), True),
    (date(2026, 10, 9), True),     # 定时任务晚了一天，仍算同一周
    (date(2026, 10, 1), False),    # 锚点前一周
    (date(2026, 9, 24), True),     # 锚点前两周
    (date(2026, 12, 31), True),    # 第 12 周
    (date(2027, 1, 7), False),     # 跨年后第 13 周
    (date(2027, 1, 14), True),     # 第 14 周
])
def test_should_run_alternates_weeks_across_new_year(day, expected):
    assert should_run(day, date(2026, 10, 8), manual=False) is expected


def test_manual_run_ignores_the_gate():
    assert should_run(date(2026, 10, 15), date(2026, 10, 8), manual=True) is True


# ---- 抓取 ----

def test_collect_queries_only_bookable_days_inside_the_window(settings):
    client = FakeCineplex()
    movies, theatres, showtimes = collect(client, settings, RUN)
    assert len(movies) == 29
    assert len(theatres) == 22
    days = [day for _, day in client.showtime_calls]
    assert days == [RUN + timedelta(days=n) for n in range(14)]
    assert {theatre for theatre, _ in client.showtime_calls} == {7130}
    assert showtimes == [{
        "theatre_id": 7130, "theatre_name": "Cineplex Cinemas Yonge-Dundas and VIP",
        "date": "2026-10-04", "film_ids": DAY_ONE,
    }]


def test_collect_ignores_theatres_outside_the_radius(settings):
    client = FakeCineplex(bookable={7130: [RUN], 7285: [RUN]})   # 7285 Milton，41 公里
    collect(client, settings, RUN)
    assert {theatre for theatre, _ in client.showtime_calls} == {7130}


# ---- 数据核对 ----

def test_sanity_passes_on_healthy_data():
    check_sanity(MOVIES, THEATRES[:3], [{"film_ids": [1]}], [make_candidate(1)])


@pytest.mark.parametrize("movies, theatres, showtimes, candidates, message", [
    (MOVIES[:19], THEATRES, [{}], [make_candidate(1)], "片单只有 19 部"),
    ([dict(m, isNowPlaying=False) for m in MOVIES], THEATRES, [{}], [make_candidate(1)], "在映片为 0"),
    (MOVIES, [], [{}], [make_candidate(1)], "GTA 影院为 0"),
    (MOVIES, THEATRES, [], [make_candidate(1)], "GTA 排片为 0"),
    (MOVIES, THEATRES, [{}], [], "候选为 0"),
])
def test_sanity_rejects_suspicious_data(movies, theatres, showtimes, candidates, message):
    with pytest.raises(PipelineError, match=message):
        check_sanity(movies, theatres, showtimes, candidates)


def test_sanity_reports_every_problem_at_once():
    with pytest.raises(PipelineError) as info:
        check_sanity(MOVIES, [], [], [])
    assert all(text in str(info.value) for text in ("GTA 影院为 0", "GTA 排片为 0", "候选为 0"))


# ---- 详情页 ----

def test_attach_details_fills_fields():
    candidates = [make_candidate(1, synopsis="", details_missing=True)]
    attach_details(FakeCineplex(), candidates)
    assert candidates[0]["synopsis"] == "Synopsis of film-1"
    assert candidates[0]["director"] == "D"
    assert candidates[0]["details_missing"] is False


def test_attach_details_tolerates_a_minority_of_failures():
    candidates = [make_candidate(i, synopsis="", details_missing=True) for i in (1, 2, 3)]
    attach_details(FakeCineplex(failing_details={"film-2"}), candidates)
    assert [c["details_missing"] for c in candidates] == [False, True, False]
    assert candidates[1]["synopsis"] == ""


def test_attach_details_fails_when_most_pages_fail():
    candidates = [make_candidate(i) for i in (1, 2, 3)]
    with pytest.raises(PipelineError, match="3 部候选里有 2 部详情页失败"):
        attach_details(FakeCineplex(failing_details={"film-1", "film-2"}), candidates)


def test_attach_details_allows_exactly_half():
    candidates = [make_candidate(i) for i in (1, 2)]
    attach_details(FakeCineplex(failing_details={"film-1"}), candidates)


# ---- 用量 ----

def test_summarize_usage(settings):
    priced = replace(settings, price_input_per_mtok=4.0, price_output_per_mtok=20.0)   # 算术与线上单价无关
    results = [LLMResult("end_turn", "", [], 1_000_000, 100_000), LLMResult("end_turn", "", [], 500_000, 50_000)]
    assert summarize_usage(results, 7, priced) == {
        "calls": 2, "input_tokens": 1_500_000, "output_tokens": 150_000, "searches": 7,
        "estimated_token_cost_usd": 9.0,
    }


# ---- 整条流水线 ----

def test_pipeline_happy_path(settings):
    caller = ScriptedCaller(keep={61994, 38459})
    edition = pipeline(settings, caller=caller)
    assert [f["film_id"] for f in edition["films"]] == EXPECTED_CANDIDATES
    assert edition["counts"] == {"must": 0, "ok": 2, "skip": 7, "review_failed": 0}
    assert edition["edition_id"] == "2026-10-03"
    assert {e["film_id"] for e in edition["filtered_events"]} == {61729, 61851, 61903, 61929, 62088}
    assert edition["orphan_ids"] == []
    assert edition["usage"]["calls"] == 5          # 粗筛 1 次 + 两部片各 2 次
    assert edition["usage"]["searches"] == 2
    ninja = next(f for f in edition["films"] if f["film_id"] == 61994)
    assert ninja["synopsis"] == "Synopsis of ninja-scroll-4k"
    assert ninja["details_missing"] is False
    assert ninja["outcome"] == "ok"
    json.dumps(edition, ensure_ascii=False)


def test_triage_sees_the_synopsis_fetched_from_detail_pages(settings):
    caller = ScriptedCaller()
    pipeline(settings, caller=caller)
    assert "Synopsis of ninja-scroll-4k" in caller.calls[0]["user"]


def test_pipeline_with_nothing_shortlisted_is_valid(settings):
    caller = ScriptedCaller(keep=set())
    edition = pipeline(settings, caller=caller)
    assert edition["counts"] == {"must": 0, "ok": 0, "skip": 9, "review_failed": 0}
    assert len(caller.calls) == 1


def test_pipeline_keeps_a_minority_of_failed_reviews_visible(settings):
    edition = pipeline(settings, caller=ScriptedCaller(keep={61994, 38459}, fail_research={38459}))
    assert edition["counts"] == {"must": 0, "ok": 1, "skip": 7, "review_failed": 1}
    failed = next(f for f in edition["films"] if f["film_id"] == 38459)
    assert failed["outcome"] == "review_failed"
    assert "max_tokens" in failed["review_error"]


def test_pipeline_fails_when_most_reviews_fail(settings):
    caller = ScriptedCaller(keep={61994, 38459, 38401}, fail_research={61994, 38459})
    with pytest.raises(ReviewError, match="3 部入围片里有 2 部精评失败") as info:
        pipeline(settings, caller=caller)
    assert "调查阶段 stop_reason 为 max_tokens ×2" in str(info.value)    # 失败原因要进报错，不然失败 Issue 没法排查


def test_pipeline_fails_on_suspicious_data_before_calling_claude(settings):
    caller = ScriptedCaller()
    with pytest.raises(PipelineError, match="GTA 排片为 0"):
        pipeline(settings, client=FakeCineplex(showtimes={}), caller=caller)
    assert caller.calls == []


def test_pipeline_passes_previous_edition_through(settings):
    previous = build_edition(settings, [recommended(61994, "Ninja Scroll 4K")], run_date=date(2026, 9, 19))
    edition = pipeline(settings, previous=previous)
    seen = {f["film_id"]: f["seen_before"] for f in edition["films"]}
    assert seen[61994] is True
    assert seen[38459] is False


def test_pipeline_respects_shortlist_cap(settings):
    caller = ScriptedCaller(keep=set(EXPECTED_CANDIDATES))
    edition = pipeline(replace(settings, shortlist_cap=2), caller=caller)
    assert edition["counts"]["ok"] == 2
    assert edition["counts"]["skip"] == 7
    assert sum(1 for c in caller.calls if c.get("tools")) == 2


# ---- 往期数据 ----

def write_edition(root, edition):
    directory = root / "data" / "editions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{edition["edition_id"]}.json').write_text(json.dumps(edition, ensure_ascii=False), encoding="utf-8")


def test_load_editions_sorts_by_id(settings, tmp_path):
    for day in (date(2026, 10, 3), date(2026, 9, 5), date(2026, 9, 19)):
        write_edition(tmp_path, build_edition(settings, [recommended(1, "A")], run_date=day))
    ids = [e["edition_id"] for e in load_editions(tmp_path / "data" / "editions")]
    assert ids == ["2026-09-05", "2026-09-19", "2026-10-03"]


def test_load_editions_on_missing_directory(tmp_path):
    assert load_editions(tmp_path / "nope") == []


def test_previous_edition_skips_same_day_and_later(settings):
    editions = [build_edition(settings, [recommended(1, "A")], run_date=day)
                for day in (date(2026, 9, 5), date(2026, 9, 19), date(2026, 10, 3), date(2026, 10, 17))]
    assert previous_edition(editions, date(2026, 10, 3))["edition_id"] == "2026-09-19"
    assert previous_edition(editions, date(2026, 9, 5)) is None
    assert previous_edition([], date(2026, 10, 3)) is None


# ---- 命令行 ----

@pytest.fixture
def root(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "gh_summary"))
    return tmp_path


def use_fakes(monkeypatch, client=None, caller=None):
    pair = (client or FakeCineplex(), caller or ScriptedCaller(keep={61994, 38459}))
    monkeypatch.setattr(main_module, "build_clients", lambda settings: pair)
    return pair


def output(root):
    path = root / "gh_output"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_cli_skip_week_does_nothing(root, monkeypatch):
    def explode(settings):
        raise AssertionError("跳过周不应该创建任何客户端")

    monkeypatch.setattr(main_module, "build_clients", explode)
    assert main(["--root", str(root), "run", "--date", "2026-10-15"]) == 0
    assert output(root) == "skipped=true\n"
    assert not (root / "data").exists()
    assert not (root / "site").exists()
    assert not (root / "out").exists()


def test_cli_success_writes_everything(root, monkeypatch):
    _, caller = use_fakes(monkeypatch)
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 0
    assert "我想在电影院看什么" in caller.calls[0]["user"]     # 口味档案原样送进了粗筛的提示词

    edition = json.loads((root / "data" / "editions" / "2026-10-03.json").read_text(encoding="utf-8"))
    assert edition["counts"]["ok"] == 2
    assert edition["generated_at"].startswith("20")
    assert edition["generated_at"][-6] in "+-"                # 带时区偏移
    assert (root / "site" / "index.html").exists()
    assert (root / "site" / "editions" / "2026-10-03.html").exists()
    assert (root / "out" / "issue_title.txt").read_text(encoding="utf-8") == "第 1 期 10/3：本期没有重点推荐"
    assert "https://akasha-r.github.io/film-radar/" in (root / "out" / "issue_body.md").read_text(encoding="utf-8")
    assert output(root) == "skipped=false\nedition_id=2026-10-03\n"
    summary = (root / "gh_summary").read_text(encoding="utf-8")
    assert "第 1 期 2026-10-03" in summary
    assert "模型调用 5 次" in summary
    assert not (root / "out" / "failure.txt").exists()


def test_cli_failure_leaves_no_edition_and_no_site(root, monkeypatch, capsys):
    class Blocked(FakeCineplex):
        def movies(self):
            raise CineplexError("首页: HTTP 403")

    use_fakes(monkeypatch, client=Blocked())
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 1
    failure = (root / "out" / "failure.txt").read_text(encoding="utf-8")
    assert "失败环节：Cineplex 抓取" in failure
    assert "首页: HTTP 403" in failure
    assert "首页: HTTP 403" in capsys.readouterr().err
    assert not (root / "data").exists()
    assert not (root / "site").exists()
    assert "skipped" not in output(root)


@pytest.mark.parametrize("caller, stage", [
    (ScriptedCaller(keep={61994, 38459, 38401}, fail_research={61994, 38459}), "联网精评"),
])
def test_cli_names_the_failing_stage(root, monkeypatch, caller, stage):
    use_fakes(monkeypatch, caller=caller)
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 1
    failure = (root / "out" / "failure.txt").read_text(encoding="utf-8")
    assert f"失败环节：{stage}" in failure
    assert "max_tokens" in failure                  # 具体原因也要写进去
    assert not (root / "data").exists()


def test_cli_unexpected_exception_still_writes_failure_txt(root, monkeypatch, capsys):
    """没列入 STAGES 的异常（缺密钥的 TypeError、网络层异常、往期数据损坏……）也要留下 failure.txt。
    否则工作流的失败 Issue 会误报成"失败发生在流水线之外的步骤"。"""
    class Exploding(FakeCineplex):
        def movies(self):
            raise RuntimeError("boom")

    use_fakes(monkeypatch, client=Exploding())
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 1
    failure = (root / "out" / "failure.txt").read_text(encoding="utf-8")
    assert "失败环节：未预期的错误" in failure
    assert "RuntimeError: boom" in failure
    assert "Traceback" in capsys.readouterr().err
    assert not (root / "data").exists()
    assert not (root / "site").exists()


def test_cli_bad_settings_fail_cleanly(root, monkeypatch):
    path = root / "config" / "settings.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("showtime_days = 14", "showtime_days = 7"), encoding="utf-8")
    use_fakes(monkeypatch)
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 1
    assert "失败环节：读取配置" in (root / "out" / "failure.txt").read_text(encoding="utf-8")


def test_cli_same_day_rerun_compares_with_the_edition_before(root, monkeypatch, settings):
    write_edition(root, build_edition(settings, [recommended(61994, "Ninja Scroll 4K")], run_date=date(2026, 9, 19)))
    write_edition(root, build_edition(settings, [recommended(38459, "Digger")], run_date=date(2026, 10, 3)))
    use_fakes(monkeypatch)
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 0
    edition = json.loads((root / "data" / "editions" / "2026-10-03.json").read_text(encoding="utf-8"))
    seen = {f["film_id"]: f["seen_before"] for f in edition["films"]}
    assert seen[61994] is True      # 上一期（9-19）推荐过
    assert seen[38459] is False     # 只在被覆盖的当天旧数据里出现过，不算
    assert (root / "out" / "issue_title.txt").read_text(encoding="utf-8").startswith("第 2 期 10/3：")


def test_cli_build_site_rebuilds_from_data(root, settings):
    write_edition(root, build_edition(settings, [recommended(1, "A")], run_date=date(2026, 9, 19)))
    write_edition(root, build_edition(settings, [recommended(2, "B")], run_date=date(2026, 10, 3)))
    assert main(["--root", str(root), "build-site"]) == 0
    assert "第 2 期" in (root / "site" / "index.html").read_text(encoding="utf-8")
    assert (root / "site" / "editions" / "2026-09-19.html").exists()
