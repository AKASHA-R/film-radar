import json
import shutil

import pytest

from film_radar import main as main_module
from film_radar.main import main
from film_radar.watched import Issue, Line, load_watched_file, parse_issue
from helpers import ROOT, FakeGitHub, task_issue, toggle

TITLES = {1: "One", 2: "Two", 3: "Three"}


@pytest.fixture
def root(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    editions = tmp_path / "data" / "editions"
    editions.mkdir(parents=True)
    for edition_id, ids in (("2026-10-03", [1, 2]), ("2026-10-08", [1, 3])):
        films = [{"film_id": i, "title": TITLES[i], "versions": [{"film_id": i}]} for i in ids]
        (editions / f"{edition_id}.json").write_text(json.dumps({"edition_id": edition_id, "films": films}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "gh_summary"))
    monkeypatch.setattr(main_module.time, "sleep", lambda seconds: None)
    return tmp_path


def use_github(monkeypatch, github):
    monkeypatch.setattr(main_module, "github_client", lambda settings: github)
    return github


def sync_watched(root):
    return main(["--root", str(root), "sync-watched"])


def apply_rewrites(root):
    return main(["--root", str(root), "apply-watched-rewrites"])


def lines(github, number):
    return parse_issue(Issue(number, github.bodies[number])).lines


def read(path):
    return path.read_text(encoding="utf-8")


def test_a_tick_is_recorded_and_spread_to_every_issue(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({2: task_issue("2026-10-03", (1, True, False)),
                                                 5: task_issue("2026-10-08", (1, False, False), (3, False, False))}))
    assert sync_watched(root) == 0
    films = load_watched_file(root / "data" / "watched.json")
    assert list(films) == [1] and films[1]["title"] == "One" and films[1]["since"][-6] in "+-"
    assert "changed=true" in read(root / "gh_output")
    assert "#2 勾上 1" in read(root / "gh_summary")
    assert apply_rewrites(root) == 0
    assert lines(github, 2) == (Line(1, True, True),)
    assert lines(github, 5) == (Line(1, True, True), Line(3, False, False))

    before = read(root / "data" / "watched.json")
    github.updates.clear()
    assert sync_watched(root) == 0 and apply_rewrites(root) == 0       # 第二轮：没有操作、没有改写
    assert github.updates == [] and read(root / "data" / "watched.json") == before
    assert json.loads(read(root / "out" / "watched_plan.json")) == {"rewrites": []}
    assert "changed=false" in read(root / "gh_output").splitlines()[-1]


def test_nothing_to_do_creates_no_list(root, monkeypatch):
    use_github(monkeypatch, FakeGitHub({5: task_issue("2026-10-08", (1, False, False))}))
    assert sync_watched(root) == 0
    assert not (root / "data" / "watched.json").exists()


def test_an_unparsable_issue_is_reported_and_the_rest_still_sync(root, monkeypatch):
    unparsable = task_issue("2026-10-03", (1, True, False)).replace("bot:0", "bot:9")
    use_github(monkeypatch, FakeGitHub({4: unparsable, 5: task_issue("2026-10-08", (3, True, False))}))
    assert sync_watched(root) == 0
    assert list(load_watched_file(root / "data" / "watched.json")) == [3]
    problem = read(root / "out" / "problems" / "issue-4.md").split("\n")
    assert problem[0] == "已看过同步：Issue #4 无法解析"
    assert any("格式不对" in row for row in problem)
    assert "Issue #4 无法解析" in read(root / "gh_summary")


def test_a_malformed_list_fails_and_changes_nothing(root, monkeypatch):
    (root / "data" / "watched.json").write_text("{not json", encoding="utf-8")
    use_github(monkeypatch, FakeGitHub({5: task_issue("2026-10-08", (3, True, False))}))
    assert sync_watched(root) == 1
    assert "失败环节：读取已看过名单" in read(root / "out" / "failure.txt")
    assert read(root / "data" / "watched.json") == "{not json"
    assert not (root / "out" / "watched_plan.json").exists()


def test_failed_rewrites_fail_the_run_and_the_next_sync_repairs_them(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({2: task_issue("2026-10-03", (1, True, False)),
                                                 5: task_issue("2026-10-08", (1, False, False))}, fail_updates=3))
    assert sync_watched(root) == 0
    assert apply_rewrites(root) == 1
    failure = read(root / "out" / "failure.txt")
    assert "失败环节：GitHub 接口" in failure and "#2" in failure and "不要在这几个 Issue 里撤销" in failure
    assert github.calls.count(("update_body", 2)) == 3                 # 每个 Issue 最多试三次
    assert lines(github, 5) == (Line(1, True, True),)                  # 别的 Issue 照常改写

    assert sync_watched(root) == 0 and apply_rewrites(root) == 0
    assert lines(github, 2) == (Line(1, True, True),)


def test_a_change_made_between_sync_and_rewrite_is_kept(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({5: task_issue("2026-10-08", (1, True, False))}))
    assert sync_watched(root) == 0
    github.bodies[5] = toggle(github.bodies[5], 1)                     # 计算之后、改写之前用户又取消了
    assert apply_rewrites(root) == 0
    assert lines(github, 5) == (Line(1, False, True),)
    assert sync_watched(root) == 0
    assert load_watched_file(root / "data" / "watched.json") == {}


def test_an_issue_broken_between_sync_and_rewrite_is_skipped_and_reported(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({2: task_issue("2026-10-03", (1, True, False)),
                                                 5: task_issue("2026-10-08", (1, False, False))}))
    assert sync_watched(root) == 0
    github.bodies[5] = github.bodies[5].replace("bot:0", "bot:8")
    assert apply_rewrites(root) == 0
    assert ("update_body", 5) not in github.calls
    assert read(root / "out" / "problems" / "issue-5.md").startswith("已看过同步：Issue #5 无法解析\n")


def test_an_untick_in_one_issue_is_spread_to_the_others_with_their_own_observed_state(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({2: task_issue("2026-10-03", (1, True, False)),
                                                 5: task_issue("2026-10-08", (1, False, False))}))
    assert sync_watched(root) == 0 and apply_rewrites(root) == 0
    assert lines(github, 2) == (Line(1, True, True),) and lines(github, 5) == (Line(1, True, True),)
    github.bodies[5] = toggle(github.bodies[5], 1)                     # 在较新的一期里取消
    assert sync_watched(root) == 0
    assert load_watched_file(root / "data" / "watched.json") == {}
    assert apply_rewrites(root) == 0
    assert lines(github, 2) == (Line(1, False, False),)                # 每个 Issue 只按自己的改写计划合并
    assert lines(github, 5) == (Line(1, False, False),)


def test_an_issue_that_lost_its_marker_between_sync_and_rewrite_is_skipped_and_reported(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({2: task_issue("2026-10-03", (1, True, False)),
                                                 5: task_issue("2026-10-08", (1, False, False))}))
    assert sync_watched(root) == 0
    github.bodies[5] = ""                                              # 用户把正文清空了
    assert apply_rewrites(root) == 0
    assert ("update_body", 5) not in github.calls
    assert lines(github, 2) == (Line(1, True, True),)
    problem = read(root / "out" / "problems" / "issue-5.md")
    assert problem.startswith("已看过同步：Issue #5 无法解析\n") and "edition 标记不见了" in problem
