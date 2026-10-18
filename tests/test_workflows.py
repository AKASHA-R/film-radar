"""工作流结构测试。这些顺序和条件是防丢勾的护栏：写在文档里，被改坏了没人会发现（spec 2026-10-17 第 6、13 节）。"""
import yaml

from helpers import ROOT


def workflow(name):
    data = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))          # PyYAML 按 YAML 1.1 把键 on 读成 True
    return data


SYNC = workflow("watched-sync.yml")
EDITION = workflow("edition.yml")


def steps(wf, job):
    return wf["jobs"][job]["steps"]


def step(wf, job, step_id):
    return next(s for s in steps(wf, job) if s.get("id") == step_id)


def position(wf, job, step_id):
    return [s.get("id") for s in steps(wf, job)].index(step_id)


def failure_script(wf, job):
    return next(s for s in steps(wf, job) if s.get("if") == "failure()")["run"]


def test_sync_checks_out_the_latest_main():
    """排队的运行在创建时就固定了提交；不写 ref 会按几分钟前的旧名单把 Issue 改回去。"""
    checkout = steps(SYNC, "sync")[0]
    assert checkout["uses"].startswith("actions/checkout@") and checkout["with"]["ref"] == "main"


def test_sync_commits_the_list_before_it_rewrites_issues():
    assert position(SYNC, "sync", "sync") < position(SYNC, "sync", "commit") < position(SYNC, "sync", "apply")
    assert "sync-watched" in step(SYNC, "sync", "sync")["run"]
    assert "apply-watched-rewrites" in step(SYNC, "sync", "apply")["run"]
    assert step(SYNC, "sync", "apply")["if"] == "steps.commit.outcome == 'success'"


def test_sync_deploys_every_run_once_the_list_is_committed():
    assert SYNC["jobs"]["sync"]["environment"]["name"] == "github-pages"
    build = step(SYNC, "sync", "build")
    assert build["if"] == "always() && steps.commit.outcome == 'success'"
    assert build["run"].index("git pull") < build["run"].index("build-site")
    assert position(SYNC, "sync", "apply") < position(SYNC, "sync", "build") < position(SYNC, "sync", "deploy")
    assert step(SYNC, "sync", "pages")["if"] == "always() && steps.build.outcome == 'success'"
    assert step(SYNC, "sync", "upload")["if"] == "always() && steps.pages.outcome == 'success'"
    assert step(SYNC, "sync", "deploy")["if"] == "always() && steps.upload.outcome == 'success'"
    assert step(SYNC, "sync", "deploy")["uses"].startswith("actions/deploy-pages@")


def test_sync_runs_for_every_issue_edit_without_a_job_filter():
    assert SYNC["on"]["issues"]["types"] == ["edited"] and "workflow_dispatch" in SYNC["on"]
    assert "if" not in SYNC["jobs"]["sync"]


def test_the_two_workflows_do_not_share_a_concurrency_group():
    assert SYNC["concurrency"] == {"group": "watched-sync", "cancel-in-progress": False}
    assert EDITION["concurrency"] == {"group": "edition", "cancel-in-progress": False}


def test_sync_permissions():
    assert SYNC["permissions"] == {"contents": "write", "issues": "write", "pages": "write", "id-token": "write"}


def test_edition_no_longer_deploys_pages():
    job = EDITION["jobs"]["edition"]
    assert not [s for s in job["steps"] if "pages" in s.get("uses", "")]
    assert "environment" not in job
    assert EDITION["permissions"] == {"contents": "write", "issues": "write", "actions": "write"}


def test_edition_reads_github_and_triggers_the_sync():
    assert step(EDITION, "edition", "run")["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    dispatch = step(EDITION, "edition", "dispatch")
    assert dispatch["if"] == "always() && steps.commit.outcome == 'success'"
    assert "gh workflow run watched-sync.yml" in dispatch["run"] and "--ref main" in dispatch["run"]
    assert position(EDITION, "edition", "commit") < position(EDITION, "edition", "issue") < position(EDITION, "edition", "dispatch")


def test_edition_failure_wording_checks_the_sync_trigger_first():
    script = failure_script(EDITION, "edition")
    order = [script.index(text) for text in
             ("同步没有触发", "通知 Issue 也没开成", "只是通知 Issue 没开成", "提交数据这一步没完成", "cat out/failure.txt")]
    assert order == sorted(order)
    assert "部署失败" not in script and "scripts/open_issue_once.sh" in script


def test_sync_failure_wording():
    script = failure_script(SYNC, "sync")
    order = [script.index(text) for text in
             ('"$APPLY_OUTCOME" = "failure"', "名单和 Issue 已经更新", "推送三次都被拒", '"$SYNC_OUTCOME" = "failure"')]
    assert order == sorted(order)
    assert 'scripts/open_issue_once.sh "已看过同步失败"' in script


def test_unparsable_issues_are_reported_every_run():
    report = next(s for s in steps(SYNC, "sync") if s.get("name") == "Report unparsable issues")
    assert report["if"] == "always()" and "out/problems" in report["run"] and "open_issue_once.sh" in report["run"]
