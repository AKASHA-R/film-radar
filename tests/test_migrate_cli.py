import json
import shutil
from datetime import date

import pytest

from film_radar import main as main_module
from film_radar.main import main
from film_radar.watched import Issue, dump_watched, parse_issue
from helpers import ROOT, FakeGitHub, build_edition, recommended, skipped

OLD = ("第 2 期重点推荐：\n\n- **B**（在映第 1 周）：一句话定位。\n\n可以看 0 部，跳过 1 部。\n\n"
       "完整页面：https://akasha-r.github.io/film-radar/\n\ncc @AKASHA-R\n")


@pytest.fixture
def root(tmp_path, settings):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    editions = tmp_path / "data" / "editions"
    editions.mkdir(parents=True)
    for edition in (build_edition(settings, [recommended(1, "A")], run_date=date(2026, 10, 3)),
                    build_edition(settings, [recommended(2, "B"), skipped(3, "C")], run_date=date(2026, 10, 8))):
        (editions / f"{edition['edition_id']}.json").write_text(json.dumps(edition, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def use_github(monkeypatch, github):
    monkeypatch.setattr(main_module, "github_client", lambda settings: github)
    return github


def migrate(root, *args):
    return main(["--root", str(root), "migrate-issues", *args])


def test_dry_run_prints_the_new_body_and_changes_nothing(root, monkeypatch, capsys):
    github = use_github(monkeypatch, FakeGitHub({5: OLD}))
    assert migrate(root, "--map", "5=2026-10-08") == 0
    out = capsys.readouterr().out
    assert "<!-- film-radar:edition 2026-10-08 -->" in out and "加 --apply 才改写" in out
    assert github.updates == [] and github.bodies[5] == OLD
    assert not (root / "out" / "migrate-backup").exists()


def test_apply_backs_up_first_then_rewrites_in_the_checkbox_format(root, monkeypatch):
    def backup_exists(number, body):
        assert (root / "out" / "migrate-backup" / f"{number}.md").read_text(encoding="utf-8") == OLD

    github = use_github(monkeypatch, FakeGitHub({5: OLD}, before_update=backup_exists))
    assert migrate(root, "--map", "5=2026-10-08", "--apply") == 0
    new = github.bodies[5]
    parsed = parse_issue(Issue(5, new))
    assert parsed.edition_id == "2026-10-08" and [l.film_id for l in parsed.lines] == [2]
    assert not parsed.lines[0].checked                                 # 名单为空：都不勾
    assert "第 2 期重点推荐：" in new                                   # 期号按数据顺序算
    assert new.endswith("\ncc @AKASHA-R\n")


def test_apply_uses_the_current_watched_list(root, monkeypatch):
    (root / "data" / "watched.json").write_text(dump_watched({2: {"title": "B", "since": "s", "ids": [2]}}), encoding="utf-8")
    github = use_github(monkeypatch, FakeGitHub({5: OLD}))
    assert migrate(root, "--map", "5=2026-10-08", "--apply") == 0
    assert parse_issue(Issue(5, github.bodies[5])).lines[0].checked


def test_an_issue_already_in_the_new_format_is_never_overwritten(root, monkeypatch, capsys):
    """中途失败重跑时，不能把用户在已迁移 Issue 里打的勾清掉。没有强制覆盖的选项。"""
    migrated = "<!-- film-radar:edition 2026-10-08 -->\n- [x] **B** · 在映第 1 周 <!-- film:2 bot:0 -->\n"
    github = use_github(monkeypatch, FakeGitHub({5: migrated}))
    assert migrate(root, "--map", "5=2026-10-08", "--apply") == 0
    assert github.updates == [] and "跳过" in capsys.readouterr().out


def test_a_migrated_issue_with_a_user_note_above_the_marker_is_still_skipped(root, monkeypatch, capsys):
    """用户在标记上面加了一行字：标记不在第一行，但这仍是已迁移的 Issue，里面的勾不能被覆盖。"""
    noted = "我的备注\n<!-- film-radar:edition 2026-10-08 -->\n- [x] **B** · 在映第 1 周 <!-- film:2 bot:0 -->\n"
    github = use_github(monkeypatch, FakeGitHub({5: noted}))
    assert migrate(root, "--map", "5=2026-10-08", "--apply") == 0
    assert github.updates == [] and github.bodies[5] == noted and "跳过" in capsys.readouterr().out
    assert not (root / "out" / "migrate-backup").exists()


def test_an_unknown_edition_fails_before_touching_github(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({5: OLD}))
    assert migrate(root, "--map", "5=2026-10-09", "--apply") == 1
    failure = (root / "out" / "failure.txt").read_text(encoding="utf-8")
    assert "失败环节：迁移旧 Issue" in failure and "2026-10-09" in failure
    assert github.calls == []


def test_a_badly_written_map_is_rejected(root, capsys):
    with pytest.raises(SystemExit):
        migrate(root, "--map", "5:2026-10-08")
    assert "Issue编号=期号" in capsys.readouterr().err
