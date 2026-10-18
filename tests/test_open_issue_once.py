import os
import shlex
import subprocess

from helpers import ROOT

SCRIPT = ROOT / "scripts" / "open_issue_once.sh"


def run_script(tmp_path, title, open_titles=(), listing_fails=False):
    """用一个假的 gh 跑脚本：api 子命令吐出 open_titles（或失败），其余子命令记下参数、把 --body-file 拷出来。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh.log"
    listing = "  exit 1\n" if listing_fails else f"  printf '%s\\n' {' '.join(shlex.quote(t) for t in open_titles)}\n  exit 0\n"
    (bin_dir / "gh").write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {shlex.quote(str(log))}\n'
        'if [ "$1" = "api" ]; then\n' + listing + "fi\n"
        "while [ $# -gt 0 ]; do\n"
        f'  if [ "$1" = "--body-file" ]; then cp "$2" {shlex.quote(str(tmp_path / "created.md"))}; fi\n'
        "  shift\n"
        "done\n",
        encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    body = tmp_path / "body.md"
    body.write_text("出错了\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "GITHUB_REPOSITORY": "AKASHA-R/film-radar", "GITHUB_REPOSITORY_OWNER": "AKASHA-R"}
    result = subprocess.run(["sh", str(SCRIPT), title, str(body)], env=env, capture_output=True, text=True)
    return result, (log.read_text(encoding="utf-8") if log.exists() else "")


def test_opens_a_failure_issue_with_a_cc_line(tmp_path):
    result, log = run_script(tmp_path, "已看过同步失败", open_titles=["film-radar 运行失败 2026-10-22"])
    assert result.returncode == 0, result.stderr
    assert "repos/AKASHA-R/film-radar/issues?labels=failure&state=open" in log        # REST 列表，不用搜索接口
    assert "issue create --repo AKASHA-R/film-radar --title 已看过同步失败" in log and "--label failure" in log
    assert (tmp_path / "created.md").read_text(encoding="utf-8") == "出错了\n\ncc @AKASHA-R\n"


def test_does_not_open_a_second_one_while_the_first_is_open(tmp_path):
    result, log = run_script(tmp_path, "已看过同步失败", open_titles=["已看过同步失败"])
    assert result.returncode == 0 and "issue create" not in log and "不重复开" in result.stdout


def test_only_an_exact_title_counts_as_a_duplicate(tmp_path):
    _, log = run_script(tmp_path, "已看过同步失败", open_titles=["已看过同步失败（旧）"])
    assert "issue create" in log


def test_still_opens_when_listing_fails(tmp_path):
    """列不出来时宁可重复，也不能漏报。"""
    _, log = run_script(tmp_path, "已看过同步失败", listing_fails=True)
    assert "issue create" in log
