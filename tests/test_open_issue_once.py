import os
import shlex
import subprocess

from helpers import ROOT

SCRIPT = ROOT / "scripts" / "open_issue_once.sh"
REPO = "AKASHA-R/film-radar"


def run_script(tmp_path, title, open_issues=(), listing_fails=False, comment_fails=False, mode=None):
    """用一个假的 gh 跑脚本。api 子命令吐出「编号<Tab>标题」行（真 gh 由 --jq 生成这个格式）或失败；
    其余子命令记下参数，把 --body-file 拷成 sent.md。open_issues 是 (编号, 标题) 列表。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh.log"
    listing = tmp_path / "listing.txt"
    listing.write_text("".join(f"{number}\t{t}\n" for number, t in open_issues), encoding="utf-8")
    (bin_dir / "gh").write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$*" >> {shlex.quote(str(log))}\n'          # 不用 echo：macOS 的 sh 会把 \\t 转成制表符
        'if [ "$1" = "api" ]; then\n'
        + ("  exit 1\n" if listing_fails else f"  cat {shlex.quote(str(listing))}\n  exit 0\n")
        + "fi\n"
        + ('if [ "$1 $2" = "issue comment" ]; then exit 1; fi\n' if comment_fails else "")
        + "while [ $# -gt 0 ]; do\n"
        f'  if [ "$1" = "--body-file" ]; then cp "$2" {shlex.quote(str(tmp_path / "sent.md"))}; fi\n'
        "  shift\n"
        "done\n",
        encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    body = tmp_path / "body.md"
    body.write_text("出错了\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "GITHUB_REPOSITORY": REPO, "GITHUB_REPOSITORY_OWNER": "AKASHA-R"}
    args = ["sh", str(SCRIPT), title, str(body)] + ([mode] if mode else [])
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    return result, (log.read_text(encoding="utf-8") if log.exists() else "")


def sent(tmp_path):
    return (tmp_path / "sent.md").read_text(encoding="utf-8")


def test_opens_a_failure_issue_with_a_cc_line(tmp_path):
    result, log = run_script(tmp_path, "已看过同步失败", open_issues=[(12, "film-radar 运行失败 2026-10-22")])
    assert result.returncode == 0, result.stderr
    assert f"repos/{REPO}/issues?labels=failure&state=open" in log        # REST 列表，不用搜索接口
    assert r'.[] | "\(.number)\t\(.title)"' in log                        # 假 gh 吐的格式就是这个 --jq 的输出
    assert f"issue create --repo {REPO} --title 已看过同步失败" in log and "--label failure" in log
    assert "issue comment" not in log
    assert sent(tmp_path) == "出错了\n\ncc @AKASHA-R\n"


def test_a_duplicate_title_gets_the_new_body_as_a_comment(tmp_path):
    """失败 Issue 没有程序去关。只「不重复开」的话，一个旧的失败 Issue 会让之后同标题的失败全部悄无声息。"""
    result, log = run_script(tmp_path, "已看过同步失败",
                             open_issues=[(12, "film-radar 运行失败 2026-10-22"), (9, "已看过同步失败")])
    assert result.returncode == 0, result.stderr
    assert f"issue comment 9 --repo {REPO} --body-file" in log
    assert "issue create" not in log
    assert sent(tmp_path) == "出错了\n\ncc @AKASHA-R\n"                    # 评论也 cc，评论会通知
    assert "#9 还开着，把这次的情况追加为评论" in result.stdout


def test_skip_if_open_neither_opens_nor_comments_on_a_duplicate(tmp_path):
    """「Issue 无法解析」提醒内容稳定，每次编辑 Issue 都会跑一轮；评论会刷屏。"""
    result, log = run_script(tmp_path, "#5 无法解析", open_issues=[(9, "#5 无法解析")], mode="skip-if-open")
    assert result.returncode == 0, result.stderr
    assert "issue create" not in log and "issue comment" not in log
    assert "不重复开" in result.stdout


def test_skip_if_open_still_opens_when_there_is_no_duplicate(tmp_path):
    _, log = run_script(tmp_path, "#5 无法解析", open_issues=[(9, "#6 无法解析")], mode="skip-if-open")
    assert "issue create" in log and "issue comment" not in log


def test_only_an_exact_title_counts_as_a_duplicate(tmp_path):
    _, log = run_script(tmp_path, "已看过同步失败", open_issues=[(9, "已看过同步失败（旧）"), (10, "旧已看过同步失败")])
    assert "issue create" in log and "issue comment" not in log


def test_still_opens_when_listing_fails(tmp_path):
    """列不出来时宁可重复，也不能漏报。"""
    _, log = run_script(tmp_path, "已看过同步失败", listing_fails=True)
    assert "issue create" in log


def test_opens_a_new_one_when_commenting_fails(tmp_path):
    """评论不上（比如那个 Issue 被锁了）也不能漏报：改开一个新的。"""
    result, log = run_script(tmp_path, "已看过同步失败", open_issues=[(9, "已看过同步失败")], comment_fails=True)
    assert result.returncode == 0, result.stderr
    assert "issue comment 9" in log and f"issue create --repo {REPO} --title 已看过同步失败" in log
    assert sent(tmp_path) == "出错了\n\ncc @AKASHA-R\n"                    # cc 只追加一次
